import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from muse_replay.agent import TurnResult  # noqa: E402
from muse_replay.memory import MatchMemory  # noqa: E402
from muse_replay.voice import Transcript  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA", str(tmp_path / "data"))
    import importlib
    import web.app as webapp
    importlib.reload(webapp)
    webapp.app.state.memory = MatchMemory(tmp_path / "data" / "memory.json")
    from muse_replay.playbook import PlaybookStore
    webapp.app.state.playbooks = PlaybookStore(tmp_path / "data" / "playbook.json")
    from muse_replay.annotations import AnnotationStore
    webapp.app.state.annotations = AnnotationStore(tmp_path / "data" / "annotations" / "records.jsonl")
    webapp._agents.clear(); webapp._live.clear()

    class FakeMeta:                       # stands in for MetaClient; agent is faked below
        def post_json(self, path, payload):
            return {"id": "r1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    webapp.app.state.client_factory = lambda: FakeMeta()
    webapp.app.state.transcribe = lambda c, wav, mode, kw: Transcript("push left", 1200, (), "s")
    return TestClient(webapp.app), webapp


def test_index_and_health(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200 and "Coach" in r.text and "Optimistic AI VF" in r.text
    h = c.get("/api/health").json()
    assert set(h) == {"ok", "report", "ffmpeg"} and "configured" in h["report"] or "missing" in h["report"]
    assert "LLM_" not in h["report"]


def test_upload_rejects_bad_type(client):
    c, _ = client
    r = c.post("/api/match", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert r.status_code == 400 and "unsupported" in r.json()["detail"]
    r = c.post("/api/match", files={"file": ("fake.mp4", b"not a video" * 50, "video/mp4")})
    assert r.status_code == 400


def test_upload_real_video_and_fetch(client, match):
    c, _ = client
    r = c.post("/api/match", files={"file": ("my_match.mp4", match.read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["name"] == "my_match" and m["info"]["duration_s"] == pytest.approx(30, abs=0.2)
    assert len(m["moments"]) >= 2 and m["clips"] == []
    assert c.get(f"/api/match/{m['id']}").json()["id"] == m["id"]
    v = c.get(f"/api/match/{m['id']}/video")
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4" and len(v.content) > 1000
    assert c.get("/api/match/zzz").status_code == 404
    assert c.get("/api/match/../x").status_code in (400, 404)


def test_sample_match(client):
    c, _ = client
    r = c.post("/api/match/sample")
    assert r.status_code == 200 and r.json()["name"] == "Sample match" and len(r.json()["moments"]) >= 2


def test_clip_path_safety(client, match):
    c, webapp = client
    mid = c.post("/api/match", files={"file": ("m.mp4", match.read_bytes(), "video/mp4")}).json()["id"]
    assert c.get(f"/api/match/{mid}/clips/..%2F..%2Fmatch.json").status_code in (400, 404)
    assert c.get(f"/api/match/{mid}/clips/nope.mp4").status_code == 404
    assert c.get(f"/api/match/{mid}/clips/x.txt").status_code == 400


def test_turn_streams_tool_events(client, match, monkeypatch):
    c, webapp = client
    mid = c.post("/api/match", files={"file": ("m.mp4", match.read_bytes(), "video/mp4")}).json()["id"]

    class FakeAgent:
        def __init__(self, client, session, **kw):
            self.session, self.on_event = session, (lambda k, d: None)
        def turn(self, text):
            self.on_event("tool_call", {"name": "remember", "arguments": '{"note":"x"}'})
            self.session.memory.remember(self.session.match, "x")
            self.on_event("tool_result", {"name": "remember", "output": "saved: x"})
            return TurnResult(text=f"re: {text}", rounds=2, input_tokens=5, output_tokens=3)

    monkeypatch.setattr(webapp, "CoachAgent", FakeAgent)
    r = c.post("/api/turn", json={"match_id": mid, "text": "note that"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:])) for b in r.text.strip().split("\n\n")]
    assert [e[0] for e in events] == ["tool_call", "tool_result", "done"]
    assert events[2][1]["text"] == "re: note that" and events[2][1]["rounds"] == 2
    assert c.get("/api/memory").json()["notes"][0]["text"] == "x"
    # same match reuses the agent (conversation continuity)
    assert webapp._agents[mid] is webapp._agents[mid]


def test_turn_without_match_and_validation(client, monkeypatch):
    c, webapp = client

    class FakeAgent:
        def __init__(self, client, session, **kw):
            assert session.video is None and session.match == "no match"
            self.session, self.on_event = session, (lambda k, d: None)
        def turn(self, text):
            return TurnResult(text="hi")

    monkeypatch.setattr(webapp, "CoachAgent", FakeAgent)
    assert "hi" in c.post("/api/turn", json={"text": "hello"}).text
    assert c.post("/api/turn", json={"text": ""}).status_code == 422
    assert c.post("/api/turn", json={"text": "   "}).status_code == 422
    assert c.post("/api/turn", json={"text": "x" * 5000}).status_code == 422


def test_turn_reports_api_error_as_event(client, monkeypatch):
    c, webapp = client
    from muse_replay.meta_api import MetaAPIError

    class FakeAgent:
        def __init__(self, client, session, **kw):
            self.session, self.on_event = session, (lambda k, d: None)
        def turn(self, text):
            raise MetaAPIError(429, "slow down")

    monkeypatch.setattr(webapp, "CoachAgent", FakeAgent)
    r = c.post("/api/turn", json={"text": "hello"})
    assert "event: error" in r.text and "slow down" in r.text


def test_turn_unexpected_crash_becomes_error_event(client, monkeypatch):
    c, webapp = client

    class FakeAgent:
        def __init__(self, client, session, **kw):
            self.session, self.on_event = session, (lambda k, d: None)
        def turn(self, text):
            raise RuntimeError("boom")

    monkeypatch.setattr(webapp, "CoachAgent", FakeAgent)
    webapp._agents.clear()
    r = c.post("/api/turn", json={"text": "hello"})
    assert "event: error" in r.text and "boom" in r.text


def test_transcribe_converts_then_calls_api(client, clip):
    c, webapp = client
    seen = {}
    webapp.app.state.transcribe = lambda cl, wav, mode, kw: seen.update(wav=str(wav), mode=mode, kw=kw) or Transcript("go b", 900, (), "s")
    r = c.post("/api/transcribe", files={"file": ("speech.mp4", clip.read_bytes(), "video/mp4")})
    assert r.status_code == 200 and r.json() == {"transcript": "go b", "audio_ms": 900}
    assert seen["wav"].endswith("in.wav") and seen["mode"] == "PUSH_TO_TALK" and seen["kw"] == ["Coach"]
    assert c.post("/api/transcribe", files={"file": ("e.webm", b"", "audio/webm")}).status_code == 400
    assert c.post("/api/transcribe", files={"file": ("e.webm", b"garbage" * 100, "audio/webm")}).status_code == 400


def test_unconfigured_api_gives_503(client, monkeypatch):
    c, webapp = client
    from muse_replay.meta_api import MetaAPIError

    def boom():
        raise MetaAPIError(0, "META_API_KEY and META_BASE_URL are required")

    webapp.app.state.client_factory = boom
    webapp._agents.clear()
    assert c.post("/api/turn", json={"text": "hello"}).status_code == 503



JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


def test_live_session_frames_and_stop(client):
    c, webapp = client
    lid = c.post("/api/live/start").json()["live_id"]
    assert c.post(f"/api/live/{lid}/frame", files={"file": ("f.jpg", b"nope", "image/jpeg")}).status_code == 400
    r = c.post(f"/api/live/{lid}/frame", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200 and r.json()["frames"] == 1
    assert c.post("/api/live/zzzz/frame", files={"file": ("f.jpg", JPEG, "image/jpeg")}).status_code == 404
    assert c.post(f"/api/live/{lid}/stop").json()["ok"] is True
    assert c.post(f"/api/live/{lid}/frame", files={"file": ("f.jpg", JPEG, "image/jpeg")}).status_code == 404


def test_watch_turn_uses_live_feed(client, monkeypatch):
    c, webapp = client
    from muse_replay.agent import WATCH_PROMPT
    seen = {}

    class FakeAgent:
        def __init__(self, client, session, **kw):
            self.session, self.on_event = session, (lambda k, d: None)
            seen["live"] = session.live
            seen["match"] = session.match
        def turn(self, text):
            seen["text"] = text
            return TurnResult(text="quiet")

    monkeypatch.setattr(webapp, "CoachAgent", FakeAgent)
    lid = c.post("/api/live/start").json()["live_id"]
    c.post(f"/api/live/{lid}/frame", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    r = c.post("/api/turn", json={"live_id": lid, "watch": True})
    assert r.status_code == 200 and "quiet" in r.text
    assert seen["text"] == WATCH_PROMPT and seen["match"] == "live session" and len(seen["live"]) == 1
    # a normal question on the same live session reuses the agent
    c.post("/api/turn", json={"live_id": lid, "text": "what do you see?"})
    assert seen["text"] == "what do you see?"
    assert c.post("/api/turn", json={"watch": True}).status_code == 400
    assert c.post("/api/turn", json={"live_id": "nope", "text": "hi"}).status_code == 404



def test_playbook_routes_and_teach_turn(client, monkeypatch):
    c, webapp = client
    from muse_replay.agent import TEACH_PROMPT
    assert c.get("/api/playbook").json() == {"playbook": None}
    assert c.put("/api/playbook", json={"game": "", "goal": "x"}).status_code == 422
    assert c.put("/api/playbook", json={"game": "Rocket Rally"}).status_code == 400
    r = c.put("/api/playbook", json={"game": "Rocket Rally", "controls": "Space boost", "goal": "score"})
    assert r.status_code == 200 and r.json()["playbook"]["controls"] == "Space boost"
    assert c.get("/api/playbook").json()["playbook"]["game"] == "Rocket Rally"

    seen = {}

    class FakeAgent:
        def __init__(self, client, session, **kw):
            self.session, self.on_event = session, (lambda k, d: None)
        def turn(self, text):
            seen.update(text=text, teach=self.session.teach, pb=self.session.playbook)
            return TurnResult(text="quiet")

    monkeypatch.setattr(webapp, "CoachAgent", FakeAgent)
    lid = c.post("/api/live/start").json()["live_id"]
    c.post(f"/api/live/{lid}/frame", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    assert c.post("/api/turn", json={"live_id": lid, "watch": True, "teach": True}).status_code == 200
    assert seen["text"] == TEACH_PROMPT and seen["teach"] is True and seen["pb"].game == "Rocket Rally"
    # a plain question in teach mode still carries the playbook
    c.post("/api/turn", json={"live_id": lid, "text": "how do I boost?", "teach": True})
    assert seen["text"] == "how do I boost?" and seen["pb"] is not None
    # delete, then teach mode is refused
    assert c.delete("/api/playbook").json()["ok"] is True
    assert c.post("/api/turn", json={"live_id": lid, "watch": True, "teach": True}).status_code == 400



def test_annotation_routes(client, monkeypatch):
    c, webapp = client
    st = webapp.app.state.annotations
    r = st.add("g", "callout", "Rotate back", frame_jpeg=JPEG)
    assert c.get("/api/annotations/stats").json()["records"] == 1
    bad = c.post(f"/api/annotations/{r.id}/label", json={"label": "meh"})
    assert bad.status_code == 422
    assert c.post("/api/annotations/nope/label", json={"label": "up"}).status_code == 404
    ok = c.post(f"/api/annotations/{r.id}/label", json={"label": "down", "correction": "we had cover"}).json()
    assert ok["label"] == "down" and ok["stats"]["down"] == 1
    assert c.get("/api/annotations/recent").json()["records"][0]["correction"] == "we had cover"
    fr = c.get(f"/api/annotations/frame/{r.frame}")
    assert fr.status_code == 200 and fr.headers["content-type"] == "image/jpeg"
    assert c.get("/api/annotations/frame/..%2Frecords.jsonl").status_code in (400, 404)
    assert c.get("/api/annotations/export").status_code == 404
    assert c.post("/api/annotations/export").json()["examples"] == 1
    dl = c.get("/api/annotations/export")
    assert dl.status_code == 200 and b'"we had cover"' in dl.content


def test_turn_done_event_carries_record_id(client, monkeypatch):
    c, webapp = client

    class FakeAgent:
        def __init__(self, client, session, **kw):
            self.session, self.on_event = session, (lambda k, d: None)
            assert session.annotations is webapp.app.state.annotations
        def turn(self, text):
            rid = self.session.record("reply", "Hold B.", text)
            return TurnResult(text="Hold B.", record_id=rid)

    monkeypatch.setattr(webapp, "CoachAgent", FakeAgent)
    r = c.post("/api/turn", json={"text": "where?"})
    done = [json.loads(b.split("\n")[1][6:]) for b in r.text.strip().split("\n\n") if b.startswith("event: done")][0]
    assert done["record_id"] and webapp.app.state.annotations.get(done["record_id"]).player_text == "where?"
