import json

import pytest

from muse_replay.agent import AGENT_SYSTEM, CoachAgent, MAX_ROUNDS
from muse_replay.config import load_settings
from muse_replay.memory import MatchMemory
from muse_replay.meta_api import MetaAPIError, MetaClient
from muse_replay.tools import Session

ENV = {"META_API_KEY": "k", "META_BASE_URL": "https://x.example/v1"}


def msg(text, rid="resp_1"):
    return {"id": rid, "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5}}


def call(name, args, cid="call_1", rid="resp_1"):
    return {"id": rid, "output": [{"type": "function_call", "name": name, "arguments": json.dumps(args),
                                   "call_id": cid, "status": "completed"}],
            "usage": {"input_tokens": 10, "output_tokens": 5}}


class Scripted:
    """Transport that returns canned responses in order and records every payload."""
    def __init__(self, responses, fail_first_with=None):
        self.responses, self.payloads, self.fail = list(responses), [], fail_first_with

    def __call__(self, method, url, headers, body):
        self.payloads.append(json.loads(body))
        if self.fail is not None:
            status, self.fail = self.fail, None
            return status, b'{"error": {"message": "unknown previous_response_id"}}'
        return 200, json.dumps(self.responses.pop(0)).encode()


def make_agent(tmp_path, transport, match=None):
    session = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"), match="t",
                      video=str(match) if match else None)
    return CoachAgent(MetaClient(load_settings(ENV), transport), session)


def test_plain_text_turn(tmp_path):
    t = Scripted([msg("Nice, keep it up.")])
    r = make_agent(tmp_path, t).turn("we won that round")
    assert r.text == "Nice, keep it up." and r.rounds == 1 and r.tool_calls == []
    p = t.payloads[0]
    assert p["instructions"] == AGENT_SYSTEM and p["tool_choice"] == "auto"
    assert {x["name"] for x in p["tools"]} >= {"look", "cut_clip", "remember", "recall", "callout"}
    assert "previous_response_id" not in p


def test_tool_round_trip_uses_previous_response_id(tmp_path):
    t = Scripted([call("remember", {"note": "they rush B early"}, rid="r1"), msg("Noted.", rid="r2")])
    agent = make_agent(tmp_path, t)
    r = agent.turn("remember that they rush B early")
    assert r.text == "Noted." and r.rounds == 2
    assert r.tool_calls == [{"name": "remember", "arguments": '{"note": "they rush B early"}',
                             "output": "saved: they rush B early"}]
    second = t.payloads[1]
    assert second["previous_response_id"] == "r1"
    assert second["input"] == [{"type": "function_call_output", "call_id": "call_1", "output": "saved: they rush B early"}]
    assert agent.last_response_id == "r2"
    assert len(agent.session.memory) == 1


def test_parallel_calls_each_get_output(tmp_path):
    two = {"id": "r1", "output": [
        {"type": "function_call", "name": "callout", "arguments": '{"text": "push"}', "call_id": "a"},
        {"type": "function_call", "name": "nope", "arguments": "{}", "call_id": "b"},
    ], "usage": {}}
    t = Scripted([two, msg("done", rid="r2")])
    r = make_agent(tmp_path, t).turn("go")
    outs = {i["call_id"]: i["output"] for i in t.payloads[1]["input"]}
    assert outs["a"] == "said (muted): push" and outs["b"].startswith("error: unknown tool")
    assert r.rounds == 2


def test_round_cap_stops_runaway(tmp_path):
    t = Scripted([call("recall", {}, rid=f"r{i}") for i in range(MAX_ROUNDS + 3)])
    r = make_agent(tmp_path, t).turn("loop forever")
    assert r.rounds == MAX_ROUNDS and "pause" in r.text


def test_stale_thread_retries_without_previous(tmp_path):
    t = Scripted([msg("fresh", rid="r9")], fail_first_with=400)
    agent = make_agent(tmp_path, t)
    agent.last_response_id = "expired"
    r = agent.turn("hey")
    assert r.text == "fresh" and t.payloads[0]["previous_response_id"] == "expired"
    assert "previous_response_id" not in t.payloads[1]


def test_other_errors_propagate(tmp_path):
    t = Scripted([], fail_first_with=500)
    with pytest.raises(MetaAPIError):
        make_agent(tmp_path, t).turn("hey")


def test_empty_input_rejected(tmp_path):
    with pytest.raises(ValueError):
        make_agent(tmp_path, Scripted([])).turn("   ")


def test_agent_cuts_a_real_clip_when_asked(tmp_path, match):
    t = Scripted([call("find_moments", {"top": 1}, rid="r1"),
                  call("cut_clip", {"start": 20, "end": 26, "label": "best"}, cid="c2", rid="r2"),
                  msg("Saved the best moment.", rid="r3")])
    r = make_agent(tmp_path, t, match).turn("clip the best moment")
    assert r.text == "Saved the best moment." and [c["name"] for c in r.tool_calls] == ["find_moments", "cut_clip"]
    out = json.loads(r.tool_calls[1]["output"])
    assert (tmp_path / "clips").joinpath("best_0020.0-0026.0.mp4").is_file() and out["seconds"] == 6


def test_cli_play(monkeypatch, tmp_path, capsys):
    from muse_replay import __main__ as cli
    from muse_replay.agent import TurnResult
    monkeypatch.setenv("META_API_KEY", "k")
    monkeypatch.setenv("META_BASE_URL", "https://x.example/v1")

    class FakeAgent:
        def __init__(self, client, session):
            assert session.match == "m7" and session.video is None
        def turn(self, text):
            return TurnResult(text="On it.", tool_calls=[{"name": "callout", "arguments": "{}", "output": "said"}], rounds=2)

    monkeypatch.setattr(cli, "CoachAgent", FakeAgent)
    assert cli.main(["play", "go", "--work", str(tmp_path), "--match", "m7"]) == 0
    out = capsys.readouterr().out
    assert "[tool] callout" in out and out.strip().endswith("On it.")


def test_agent_records_callouts_and_replies_with_frames(tmp_path):
    from muse_replay.annotations import AnnotationStore
    from muse_replay.tools import LiveFeed
    JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"
    t = Scripted([
        {"id": "r1", "output": [{"type": "function_call", "name": "callout", "arguments": '{"text": "Rotate back"}', "call_id": "a"}], "usage": {}},
        msg("Rotating. Watch the far post.", rid="r2"),
    ])
    agent = make_agent(tmp_path, t)
    agent.session.annotations = AnnotationStore(tmp_path / "ann.jsonl")
    agent.session.live = LiveFeed(); agent.session.live.push(JPEG)
    agent.session.last_observation = "ball in our half, goal empty"
    events = []; agent.on_event = lambda k, d: events.append((k, d))
    r = agent.turn("what now?")
    st = agent.session.annotations
    recs = st.recent()
    assert [x.kind for x in recs] == ["callout", "reply"]
    assert recs[0].text == "Rotate back" and recs[0].observation == "ball in our half, goal empty" and recs[0].frame.endswith(".jpg")
    assert recs[1].player_text == "what now?" and recs[1].mode == "live"
    tool_result = [d for k, d in events if k == "tool_result"][0]
    assert tool_result["record_id"] == recs[0].id and r.record_id == recs[1].id
    # rating feeds the next request's instructions
    st.label(recs[0].id, "up")
    t2 = Scripted([msg("ok", rid="r3")]); agent.client = MetaClient(load_settings(ENV), t2)
    agent.turn("again")
    assert 'Good callout: "Rotate back"' in t2.payloads[0]["instructions"]


def test_watch_tick_quiet_is_not_recorded(tmp_path):
    from muse_replay.agent import WATCH_PROMPT
    from muse_replay.annotations import AnnotationStore
    agent = make_agent(tmp_path, Scripted([msg("quiet", rid="r1")]))
    agent.session.annotations = AnnotationStore(tmp_path / "ann.jsonl")
    r = agent.turn(WATCH_PROMPT)
    assert r.record_id == "" and agent.session.annotations.stats()["records"] == 0
