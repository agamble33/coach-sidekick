import json
from pathlib import Path

import pytest

from muse_replay.memory import MatchMemory
from muse_replay.tools import TOOLS, Session, run_tool, tool_specs


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
    from muse_replay.ingest import VideoInfo
    from muse_replay.tools import t_cut_clip
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
    p = Path(out["file"])
    assert p.is_file() and p.stat().st_size > 0 and p.name.startswith("bigplay_")
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
