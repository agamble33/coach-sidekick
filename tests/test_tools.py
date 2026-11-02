import json
from pathlib import Path

import pytest

from coach.memory import MatchMemory
from coach.tools import TOOLS, Session, run_tool, tool_specs


@pytest.fixture
def session(tmp_path, match):
    return Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "mem.json"), match="test-1", video=str(match))


def test_specs_are_responses_api_shaped():
    specs = tool_specs()
    assert {s["type"] for s in specs} == {"function"}
    for s in specs:
        assert set(s) == {"type", "name", "description", "parameters"}
        assert s["parameters"]["type"] == "object" and s["parameters"]["additionalProperties"] is False
        assert "." not in s["name"]
    assert tool_specs(["callout"])[0]["name"] == "callout"


def test_unknown_tool_and_bad_args(session):
    assert run_tool(session, "nope", {}).startswith("error: unknown tool")
    assert run_tool(session, "cut_clip", "{not json").startswith("error:")
    assert run_tool(session, "cut_clip", 42).startswith("error:")
    assert run_tool(session, "cut_clip", {"start": "x", "end": 2}) == "error: start must be a number"
    assert run_tool(session, "cut_clip", {"start": 5, "end": 2}).startswith("error:")
    assert run_tool(session, "cut_clip", {"start": 0, "end": 999}).startswith("error:")

def test_cut_clip_cap(tmp_path):
    from coach.ingest import VideoInfo
    from coach.tools import t_cut_clip
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"), video="x.mp4")
    s._info = VideoInfo("x.mp4", 600.0, 30.0, 320, 240, True)
    with pytest.raises(ValueError, match="capped at 60"):
        t_cut_clip(s, {"start": 0, "end": 61})


def test_video_info_and_no_video(session, tmp_path):
    info = json.loads(run_tool(session, "video_info", {}))
    assert info["duration_s"] == pytest.approx(30, abs=0.2)
    bare = Session(work_dir=tmp_path, memory=session.memory)
    assert run_tool(bare, "video_info", {}) == "error: no video loaded for this session"


def test_find_moments_and_cut_clip_real(session):
    found = json.loads(run_tool(session, "find_moments", {"top": 3}))
    assert found["events"] >= 3 and 1 <= len(found["moments"]) <= 3
    m = found["moments"][0]
    out = json.loads(run_tool(session, "cut_clip", {"start": m["start"], "end": m["end"], "label": "big play!!"}))
    p = session.work_dir / "clips" / out["clip"]
    assert p.is_file() and p.stat().st_size > 0 and p.name.startswith("bigplay_")
    assert "/" not in out["clip"] and "\\" not in out["clip"]
    assert run_tool(session, "cut_clip", {"start": 0, "end": 31}).startswith("error: end must be between")


def test_look_without_client_captures_frame(session):
    out = run_tool(session, "look", {"t": 12})
    assert out.startswith("(no model client) frame at 12.0s captured")
    assert run_tool(session, "look", {"t": 999}).startswith("error:")
    assert run_tool(session, "look", {}) == "error: missing argument 't'"


def test_look_sends_image_to_model(session):
    sent = {}

    class FakeClient:
        def post_json(self, path, payload):
            sent.update(path=path, payload=payload)
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Two players mid, one low HP."}]}]}

    session.client = FakeClient()
    assert run_tool(session, "look", {"t": 3, "question": "who is winning?"}) == "Two players mid, one low HP."
    content = sent["payload"]["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "who is winning?"}
    assert content[1]["type"] == "input_image" and content[1]["image_url"].startswith("data:image/jpeg;base64,/9j/")
    assert sent["payload"]["reasoning"] == {"effort": "low"}
    assert "no markdown" in sent["payload"]["instructions"]


def test_memory_tools_round_trip(session):
    assert run_tool(session, "recall", {}) == "no notes yet"
    assert run_tool(session, "remember", {"note": "  we lose when we both push mid  "}) == "saved: we lose when we both push mid"
    assert run_tool(session, "remember", {"note": ""}) == "error: note is empty"
    assert run_tool(session, "recall", {"scope": "this_match"}) == "[test-1] we lose when we both push mid"
    # survives a restart
    again = MatchMemory(session.memory.path)
    assert len(again) == 1 and again.recall()[0].text == "we lose when we both push mid"


def test_callout_records_and_mutes(session):
    assert run_tool(session, "callout", {"text": "  Flank   left now "}) == "said (muted): Flank left now"
    assert session.spoken == ["Flank left now"]
    assert run_tool(session, "callout", {"text": "   "}) == "error: nothing to say"


def test_memory_handles_corrupt_file(tmp_path):
    f = tmp_path / "m.json"
    f.write_text("{not json")
    m = MatchMemory(f)
    assert len(m) == 0
    m.remember("a", "x")
    assert json.loads(f.read_text())[0]["text"] == "x"


def test_memory_caps_and_matches(tmp_path):
    m = MatchMemory(tmp_path / "m.json")
    for i in range(205):
        m.remember("m%d" % (i % 3), "note %d" % i)
    assert len(m) == 200                                   # capped
    assert set(m.matches()) == {"m0", "m1", "m2"}
    last_m0 = m.recall("m0", limit=2)
    assert [n.text for n in last_m0] == ["note 201", "note 204"]
    assert all(n.match == "m0" for n in m.recall("m0", limit=5))


# ---- live mode ----

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


def test_live_feed_validates_and_keeps_latest():
    from coach.tools import LiveFeed
    f = LiveFeed(keep=2)
    assert f.latest() is None and f.age_s() is None
    with pytest.raises(ValueError):
        f.push(b"not a jpeg")
    with pytest.raises(ValueError):
        f.push(b"\xff\xd8" + b"\x00" * (2 * 1024 * 1024 + 1))
    f.push(JPEG, ts=1.0); f.push(JPEG + b"x", ts=2.0); f.push(JPEG + b"xy", ts=3.0)
    assert len(f) == 2 and f.latest()[0] == 3.0


def test_look_now_without_live_or_stale(tmp_path):
    from coach.tools import LiveFeed
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"))
    assert run_tool(s, "look_now", {}) == "error: live mode is off; ask the player to share their screen"
    s.live = LiveFeed(); s.live.push(JPEG, ts=0.0)          # 1970: very stale
    assert run_tool(s, "look_now", {}).startswith("error: last frame is")


def test_look_now_sends_latest_frame(tmp_path):
    from coach.tools import LiveFeed
    sent = {}

    class FakeClient:
        def post_json(self, path, payload):
            sent.update(payload=payload)
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Enemy pushing B, you are low."}]}]}

    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"), client=FakeClient())
    s.live = LiveFeed(); s.live.push(JPEG)
    out = run_tool(s, "look_now", {"question": "any danger?"})
    assert out.endswith("Enemy pushing B, you are low.") and out.startswith("[0s ago]")
    c = sent["payload"]["input"][0]["content"]
    assert c[0]["text"] == "any danger?" and c[1]["image_url"].startswith("data:image/jpeg;base64,/9j/")
    assert "look_now" in {t["name"] for t in tool_specs()}


def test_overlay_tools(session):
    # highlight: fractions of the screen, labelled, expiring; off-screen boxes refused
    out = run_tool(session, "highlight", {"x": 0.6, "y": 0.3, "w": 0.1, "h": 0.2, "label": "  Enemy   here ", "seconds": 5})
    assert out == "highlighted Enemy here at (0.60, 0.30) for 8s"      # 5 requested, floor is 8
    hl = session.overlay.snapshot()["highlights"]
    assert len(hl) == 1 and hl[0]["label"] == "Enemy here" and hl[0]["x"] == 0.6
    assert run_tool(session, "highlight", {"x": 0.95, "y": 0.5, "w": 0.2}).startswith("error:")
    assert run_tool(session, "highlight", {"x": 1.5, "y": 0.5}) == "error: x must be between 0 and 1"
    assert run_tool(session, "highlight", {"y": 0.5}) == "error: missing argument 'x'"
    for i in range(7):
        run_tool(session, "highlight", {"x": 0.1, "y": 0.1, "label": str(i)})
    assert len(session.overlay.highlights) == 5          # capped, oldest dropped
    session.overlay.highlights[0]["until"] = 0            # expired ones vanish from the snapshot
    assert len(session.overlay.snapshot()["highlights"]) == 4
    # tasks: replace, tick, bounds
    assert run_tool(session, "set_tasks", {"tasks": ["Clear the yard", " Get  the key "]}) == "tasks: 1. Clear the yard; 2. Get the key"
    assert run_tool(session, "task_done", {"index": 2}) == "done: Get the key"
    assert [t["done"] for t in session.overlay.tasks] == [False, True]
    assert run_tool(session, "task_done", {"index": 3}).startswith("error: no task 3")
    assert run_tool(session, "set_tasks", {"tasks": []}) == "error: give at least one task"
    assert run_tool(session, "set_tasks", {"tasks": "not a list"}).startswith("error:")
    assert len(run_tool(session, "set_tasks", {"tasks": [str(i) for i in range(9)]}).split(";")) == 6
    # a callout lands on the overlay too
    run_tool(session, "callout", {"text": "Push left"})
    snap = session.overlay.snapshot()
    assert snap["callout"] == "Push left" and snap["callout_at"] > 0


def test_highlight_clock_restarts_when_turn_ends(session, monkeypatch):
    import time as _t
    t0 = 1_000_000.0
    monkeypatch.setattr(_t, "time", lambda: t0)
    session.overlay.start_turn()
    run_tool(session, "highlight", {"x": 0.5, "y": 0.5, "seconds": 8})
    assert session.overlay.highlights[0]["until"] == t0 + 8
    monkeypatch.setattr(_t, "time", lambda: t0 + 20)          # the turn took 20 s
    assert session.overlay.snapshot()["highlights"] == []     # it would have expired...
    session.overlay.finish_turn()
    assert session.overlay.highlights[0]["until"] == t0 + 28  # ...so finish_turn restarts the clock
    assert len(session.overlay.snapshot()["highlights"]) == 1


def test_report_concern_files_incident_with_frame(session, tmp_path, monkeypatch):
    from coach.incidents import IncidentStore
    from coach.tools import LiveFeed
    from coach.playbook import make_playbook
    assert run_tool(session, "report_concern", {"category": "bug", "what_you_saw": "x"}) == "error: reports are not enabled on this server"
    session.incidents = IncidentStore(tmp_path / "inc.jsonl")
    session.live = LiveFeed(); session.live.push(JPEG); session.live_id = "live1"
    session.playbook = make_playbook({"game": "Kid Kart", "goal": "race", "audience": "kids"})
    sent = []
    monkeypatch.setattr("coach.tools.send_alert", lambda inc: sent.append(inc.id) or True)
    out = run_tool(session, "report_concern", {"category": "adult_contact", "severity": "high",
                                               "what_you_saw": "Chat from 'coolguy44': what school do you go to? add me on snap",
                                               "who": "coolguy44"})
    assert out.startswith("reported adult_contact (high) as ") and "Do not confront" in out
    inc = session.incidents.recent()[0]
    assert inc.who == "coolguy44" and inc.game == "Kid Kart" and inc.audience == "kids" and inc.live_id == "live1"
    assert inc.frame and (tmp_path / "frames" / inc.frame).read_bytes() == JPEG and inc.alerted is True and sent == [inc.id]
    assert run_tool(session, "report_concern", {"category": "gossip", "what_you_saw": "x"}).startswith("error: category must be")
    assert run_tool(session, "report_concern", {"category": "bug", "what_you_saw": "  "}) == "error: say what you saw"
    assert run_tool(session, "report_concern", {"category": "bug", "severity": "low", "what_you_saw": "fell through floor"}).startswith("reported bug (low)")
