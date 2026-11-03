import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from coach.agent import TurnResult  # noqa: E402
from coach.memory import MatchMemory  # noqa: E402
from coach.voice import Transcript  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA", str(tmp_path / "data"))
    import importlib
    import web.app as webapp
    importlib.reload(webapp)
    webapp.app.state.memory = MatchMemory(tmp_path / "data" / "memory.json")
    from coach.playbook import PlaybookStore
    webapp.app.state.playbooks = PlaybookStore(tmp_path / "data" / "playbook.json")
    from coach.annotations import AnnotationStore
    webapp.app.state.annotations = AnnotationStore(tmp_path / "data" / "annotations" / "records.jsonl")
    webapp._agents.clear(); webapp._live.clear()

    class FakeMeta:                       # stands in for MetaClient; agent is faked below
        def post_json(self, path, payload):
            return {"id": "r1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    webapp.app.state.client_factory = lambda: FakeMeta()
    webapp.app.state.transcribe = lambda c, wav, mode, kw: Transcript("push left", 1200, (), "s")
    tc = TestClient(webapp.app)
    # every test runs as a player who already agreed to the pilot terms; test_consent_gate
    # drops the header to prove the server refuses without it
    cid = tc.post("/api/consent", json={"version": webapp.CONSENT_VERSION, "see": True, "hear": True, "age_ok": True}).json()["consent_id"]
    tc.headers["X-Coach-Consent"] = cid
    return tc, webapp


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
    from coach.meta_api import MetaAPIError

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
    from coach.meta_api import MetaAPIError

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
    from coach.agent import WATCH_PROMPT
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
    from coach.agent import TEACH_PROMPT
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


def test_consent_gate(client, tmp_path):
    c, webapp = client
    v = webapp.CONSENT_VERSION
    assert c.get("/api/consent/version").json() == {"version": v}
    t = c.get("/terms")
    assert t.status_code == 200 and "pilot" in t.text.lower() and "18 or older" in t.text
    # the three capture endpoints refuse without a consent id, or with an unknown one
    for hdr in ({}, {"X-Coach-Consent": "not-a-real-id"}):
        bare = TestClient(webapp.app)
        bare.headers.update(hdr)
        assert bare.post("/api/live/start").status_code == 403
        assert bare.post("/api/transcribe", files={"file": ("s.webm", b"x" * 10, "audio/webm")}).status_code == 403
        assert bare.post("/api/match", files={"file": ("m.mp4", b"x" * 10, "video/mp4")}).status_code == 403
    # consent must be the current version with all three boxes
    assert c.post("/api/consent", json={"version": "old", "see": True, "hear": True, "age_ok": True}).status_code == 400
    assert c.post("/api/consent", json={"version": v, "see": True, "hear": False, "age_ok": True}).status_code == 400
    r = c.post("/api/consent", json={"version": v, "see": True, "hear": True, "age_ok": True})
    assert r.status_code == 200 and r.json()["version"] == v
    cid = r.json()["consent_id"]
    fresh = TestClient(webapp.app)
    fresh.headers["X-Coach-Consent"] = cid
    assert fresh.post("/api/live/start").status_code == 200
    # consents are written to disk and survive a restart of the app module
    lines = (tmp_path / "data" / "consents.jsonl").read_text().splitlines()
    recs = [json.loads(l) for l in lines]
    assert any(x["consent_id"] == cid and x["version"] == v and x["see"] and x["hear"] and x["age_ok"] for x in recs)
    webapp._consents.clear(); webapp._consents_loaded = False
    assert fresh.post("/api/live/start").status_code == 200
    # the sample match captures nothing from the player, so it stays open
    assert TestClient(webapp.app).post("/api/match/sample").status_code == 200


def test_overlay_page_and_state(client):
    c, webapp = client
    r = c.get("/overlay")
    assert r.status_code == 200 and "Coach overlay" in r.text
    assert c.get("/api/overlay/nope").status_code == 404
    lid = c.post("/api/live/start").json()["live_id"]
    empty = c.get(f"/api/overlay/{lid}").json()
    assert empty["highlights"] == [] and empty["tasks"] == [] and empty["callout"] == ""
    assert TestClient(webapp.app).post(f"/api/overlay/{lid}/demo").status_code == 403   # consent-gated
    demo = c.post(f"/api/overlay/{lid}/demo").json()
    assert len(demo["highlights"]) == 2 and demo["highlights"][0]["label"] == "Enemy here"
    assert [t["done"] for t in demo["tasks"]] == [True, False, False] and demo["callout"].startswith("Push left")
    again = c.get(f"/api/overlay/{lid}").json()
    assert again["tasks"] == demo["tasks"] and again["callout"] == demo["callout"]
    c.post(f"/api/live/{lid}/stop")
    assert c.get(f"/api/overlay/{lid}").status_code == 404


def test_transcribe_accepts_wav_upload(client, clip, tmp_path):
    # Regression: a .wav upload was converted onto its own path and failed with 400.
    from coach.voice import to_wav_24k
    c, webapp = client
    wav = to_wav_24k(clip, tmp_path / "speech.wav")
    webapp.app.state.transcribe = lambda cl, w, mode, kw: Transcript("hold high ground", 800, (), "s")
    r = c.post("/api/transcribe", files={"file": ("speech.wav", wav.read_bytes(), "audio/wav")})
    assert r.status_code == 200 and r.json()["transcript"] == "hold high ground"


def test_overlay_settings_layout_and_hidden(client):
    c, webapp = client
    lid = c.post("/api/live/start").json()["live_id"]
    st = c.get(f"/api/overlay/{lid}").json()
    assert st["hidden"] is False and st["layout"] == {"tasks": "bl", "callout": "top", "badge": "tl"}
    assert TestClient(webapp.app).post(f"/api/overlay/{lid}/settings", json={"hidden": True}).status_code == 403
    r = c.post(f"/api/overlay/{lid}/settings", json={"hidden": True, "layout": {"tasks": "tr", "callout": "bottom", "badge": "off"}})
    assert r.status_code == 200 and r.json() == {"hidden": True, "layout": {"tasks": "tr", "callout": "bottom", "badge": "off"},
                                                 "spice": "mild", "pack": "classic", "avatar": "muse_bot", "guide": False,
                                                 "reactions": r.json()["reactions"]}
    st = c.get(f"/api/overlay/{lid}").json()
    assert st["hidden"] is True and st["layout"]["tasks"] == "tr"
    assert c.post(f"/api/overlay/{lid}/settings", json={"layout": {"tasks": "middle"}}).status_code == 400
    assert c.post(f"/api/overlay/{lid}/settings", json={"layout": {"minimap": "tl"}}).status_code == 400
    assert c.post("/api/overlay/nope/settings", json={"hidden": False}).status_code == 404
    c.post(f"/api/overlay/{lid}/settings", json={"hidden": False})
    assert c.get(f"/api/overlay/{lid}").json()["hidden"] is False


def test_incident_routes_and_admin_token(client, monkeypatch):
    c, webapp = client
    assert c.get("/admin/incidents").status_code == 200 and "safety reports" in c.get("/admin/incidents").text
    inc = webapp.app.state.incidents.add("bullying", "medium", "chat: 'uninstall, trash'", who="p2", game="G", frame_jpeg=JPEG)
    j = c.get("/api/incidents?status=open").json()
    assert j["stats"]["open"] == 1 and j["incidents"][0]["id"] == inc.id and j["incidents"][0]["frame"] == inc.frame
    assert c.get(f"/api/incidents/frame/{inc.frame}").status_code == 200
    assert c.get("/api/incidents/frame/..%2Fsecret.jpg").status_code in (400, 404)
    r = c.post(f"/api/incidents/{inc.id}/status", json={"status": "confirmed", "note": "told the studio"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert c.post("/api/incidents/nope/status", json={"status": "open"}).status_code == 404
    assert c.post(f"/api/incidents/{inc.id}/status", json={"status": "banned"}).status_code == 422
    # with a token set, every incident route needs it
    monkeypatch.setenv("COACH_ADMIN_TOKEN", "s3cret")
    assert c.get("/api/incidents").status_code == 401
    assert c.get("/api/incidents", headers={"X-Coach-Admin": "wrong"}).status_code == 401
    assert c.get("/api/incidents", headers={"X-Coach-Admin": "s3cret"}).status_code == 200


def test_playbook_audience_round_trip_and_prompt(client):
    c, webapp = client
    assert c.put("/api/playbook", json={"game": "Kid Kart", "goal": "race", "audience": "grownups"}).status_code == 400
    r = c.put("/api/playbook", json={"game": "Kid Kart", "goal": "race", "audience": "kids"})
    assert r.status_code == 200
    pb = webapp.app.state.playbooks.load()
    assert pb.audience == "kids" and "AUDIENCE: children" in pb.as_prompt() and "report_concern" in pb.as_prompt()
    assert c.get("/api/playbook").json()["playbook"]["audience"] == "kids"


def test_reactions_assets_settings_and_demo(client):
    c, webapp = client
    # static assets are mounted where engine payloads point
    assert c.get("/reactions/images/cackle.png").status_code == 200
    assert c.get("/reactions/images/classic/horse_judge.png").status_code == 200
    assert c.get("/reactions/sounds/womp.mp3").status_code == 200
    lid = c.post("/api/live/start").json()["live_id"]
    # demo fills in a reaction card alongside the highlights and tasks
    demo = c.post(f"/api/overlay/{lid}/demo").json()
    assert demo["reaction"] and demo["reaction"]["trigger"] == "missed_jump"
    assert demo["reaction"]["image"] == "/reactions/images/classic/cackle.png" and demo["reaction"]["sound"].endswith(".mp3")
    # settings: spice and pack round-trip, bad values are 400
    r = c.post(f"/api/overlay/{lid}/settings", json={"spice": "unhinged", "pack": "classic"})
    assert r.status_code == 200 and r.json()["spice"] == "unhinged" and r.json()["pack"] == "classic"
    assert c.post(f"/api/overlay/{lid}/settings", json={"spice": "nuclear"}).status_code == 400
    assert c.post(f"/api/overlay/{lid}/settings", json={"pack": "vhs"}).status_code == 400
    # overlay page carries the reaction card markup
    assert 'id="reaction"' in c.get("/overlay").text
    c.post(f"/api/live/{lid}/stop")


def test_reactions_avatar_test_button_and_catalog(client):
    c, webapp = client
    cat = c.get("/api/reactions").json()
    assert cat["avatar"] == "muse_bot" and set(cat["avatars"]) == {"muse_bot", "coach", "dog"} and "missed_jump" in cat["triggers"]
    assert c.get("/reactions/avatars/muse_bot.png").status_code == 200
    lid = c.post("/api/live/start").json()["live_id"]
    # overlay state carries the avatar for the badge
    st = c.get(f"/api/overlay/{lid}").json()
    assert st["avatar_url"] == "/reactions/avatars/muse_bot.png" and st["avatar_label"] == "Muse Bot"
    r = c.post(f"/api/overlay/{lid}/settings", json={"avatar": "dog"})
    assert r.status_code == 200 and r.json()["avatar"] == "dog" and r.json()["reactions"]["avatar_label"] == "Dog"
    assert c.get(f"/api/overlay/{lid}").json()["avatar_label"] == "Dog"
    assert c.post(f"/api/overlay/{lid}/settings", json={"avatar": "cat"}).status_code == 400
    # the Test button: consent-gated, fires once, then reports the cooldown calmly
    assert TestClient(webapp.app).post(f"/api/overlay/{lid}/react", json={"trigger": "whiff"}).status_code == 403
    r = c.post(f"/api/overlay/{lid}/react", json={"trigger": "whiff"}).json()
    assert r["fired"] and r["reaction"]["trigger"] == "whiff" and r["reaction"]["avatar"] == "dog"
    assert c.get(f"/api/overlay/{lid}").json()["reaction"]["trigger"] == "whiff"
    r2 = c.post(f"/api/overlay/{lid}/react", json={"trigger": "whiff"}).json()
    assert r2 == {"fired": False, "reason": "global cooldown"}
    # off switch: spice off means the test button fires nothing
    c.post(f"/api/overlay/{lid}/settings", json={"spice": "off"})
    assert c.post(f"/api/overlay/{lid}/react", json={"trigger": "clutch"}).json()["fired"] is False
    # settings page carries the guide
    page = c.get("/").text
    assert 'id="rx_on"' in page and "Meme reactions" in page and "Test reaction" in page
    c.post(f"/api/live/{lid}/stop")


def test_guide_me_settings_point_and_demo(client):
    c, webapp = client
    lid = c.post("/api/live/start").json()["live_id"]
    st = c.get(f"/api/overlay/{lid}").json()
    assert st["guide"] is False and st["pointers"] == [] and st["route"] == []
    # off by default: the test arrow is refused calmly
    r = c.post(f"/api/overlay/{lid}/point", json={"label": "Go here"}).json()
    assert r["ok"] is False and "guide mode is off" in r["result"]
    # on: arrow lands in the overlay state; demo adds a route
    r = c.post(f"/api/overlay/{lid}/settings", json={"guide": True})
    assert r.status_code == 200 and r.json()["guide"] is True
    r = c.post(f"/api/overlay/{lid}/point", json={"x": 0.72, "y": 0.4, "label": "Go here"}).json()
    assert r["ok"] and r["overlay"]["pointers"][0]["label"] == "Go here"
    assert c.get(f"/api/overlay/{lid}").json()["pointers"][0]["x"] == 0.72
    demo = c.post(f"/api/overlay/{lid}/demo").json()
    assert [w["label"] for w in demo["route"]] == ["Courtyard", "Fountain", "East gate"]
    assert any(p["direction"] == "left" for p in demo["pointers"])
    # consent-gated like the other overlay writes
    assert TestClient(webapp.app).post(f"/api/overlay/{lid}/point", json={}).status_code == 403
    # off again clears everything
    c.post(f"/api/overlay/{lid}/settings", json={"guide": False})
    st = c.get(f"/api/overlay/{lid}").json()
    assert st["pointers"] == [] and st["route"] == []
    page = c.get("/overlay").text
    assert 'id="routeSvg"' in page and 'id="guideTag"' in page
    assert 'id="gd_on"' in c.get("/").text
    c.post(f"/api/live/{lid}/stop")


def test_game_sdk_state_directives_and_reactions(client):
    c, webapp = client
    lid = c.post("/api/live/start").json()["live_id"]
    assert c.get(f"/api/game/{lid}/directives").status_code == 200
    assert c.get("/api/game/nope/directives").status_code == 404
    # consent-gated write
    assert TestClient(webapp.app).post(f"/api/game/{lid}/state", json={"objective": "x"}).status_code == 403
    c.post(f"/api/overlay/{lid}/settings", json={"guide": True, "spice": "mild"})
    body = {"game": "Fake Game", "player": {"pos": [1, 0, 2], "hp": 50}, "objective": "Find the east gate key",
            "landmarks": [{"id": "fountain", "label": "Fountain", "visible": True, "screen": [0.52, 0.55]},
                          {"id": "east_gate", "label": "East gate", "dir": "right"}],
            "events": [{"type": "fell", "detail": "missed the ledge"}]}
    r = c.post(f"/api/game/{lid}/state", json=body).json()
    assert r["ok"] and r["landmarks"] == 2 and r["reactions_fired"] == ["missed_jump"] and r["fresh"]
    assert c.post(f"/api/game/{lid}/state", json=[1, 2]).status_code in (400, 422)
    # the reaction fired from the event lands in the overlay for the page and the game alike
    d = c.get(f"/api/game/{lid}/directives").json()
    assert d["overlay"]["reaction"]["trigger"] == "missed_jump"
    assert d["game"]["objective"] == "Find the east gate key" and set(d["game"]["landmarks"]) == {"fountain", "east_gate"}
    # a hand-drawn arrow on a landmark carries the id so the game can draw it in the world
    from coach.tools import run_tool
    s = webapp._agents[f"live:{lid}"].session
    assert run_tool(s, "point", {"x": 0, "y": 0, "landmark": "east_gate"}).startswith("pointed East gate (off screen, right)")
    d = c.get(f"/api/game/{lid}/directives").json()
    assert d["overlay"]["pointers"][0]["landmark"] == "east_gate"
    assert c.get(f"/api/game/{lid}/state").json()["posts"] == 1
    c.post(f"/api/live/{lid}/stop")
    assert c.get(f"/api/game/{lid}/directives").status_code == 404


def test_game_sdk_box_and_docs_present(client):
    c, webapp = client
    page = c.get("/").text
    assert 'id="sdk_copy"' in page and "Game SDK" in page
    from pathlib import Path
    root = Path(webapp.__file__).resolve().parent.parent
    assert (root / "docs" / "game-sdk.md").is_file()
    assert (root / "sdk" / "unity" / "CoachClient.cs").is_file() and (root / "sdk" / "unity" / "CoachArrow.cs").is_file()


def test_guard_caps_turns_and_frames(client, monkeypatch):
    from coach.guard import Guard, Limits
    c, webapp = client
    webapp.app.state.guard = Guard(webapp.DATA / "budget-test.json", Limits(turns_per_min=2, frames_per_min=1))
    assert c.get("/api/guard").json()["per_minute"]["turns"] == 2
    lid = c.post("/api/live/start").json()["live_id"]
    jpeg = b"\xff\xd8" + b"\x00" * 100
    assert c.post(f"/api/live/{lid}/frame", files={"file": ("f.jpg", jpeg, "image/jpeg")}).status_code == 200
    r = c.post(f"/api/live/{lid}/frame", files={"file": ("f.jpg", jpeg, "image/jpeg")})
    assert r.status_code == 429 and "breather" in r.json()["detail"]
    # turns: the cap fires before any model call
    for _ in range(2):
        c.post("/api/turn", json={"live_id": lid, "text": "hi"})
    r = c.post("/api/turn", json={"live_id": lid, "text": "hi"})
    assert r.status_code == 429
    webapp.app.state.guard.disabled = True
    assert c.post("/api/turn", json={"live_id": lid, "text": "hi"}).status_code == 503
    webapp.app.state.guard.disabled = False
    c.post(f"/api/live/{lid}/stop")


def test_profile_api(client):
    c, webapp = client
    assert c.get("/api/profile").json() == {"games": {}}
    r = c.put("/api/profile", json={"game": "Kid Kart", "category": "controls", "name": "invert_y", "value": "on"})
    assert r.status_code == 200 and r.json()["game"] == "kid kart"
    assert c.put("/api/profile", json={"game": "x", "category": "weather", "name": "a", "value": "b"}).status_code == 400
    assert c.get("/api/profile").json()["games"]["kid kart"]["invert_y"]["value"] == "on"
    assert c.delete("/api/profile", params={"game": "Kid Kart", "name": "invert_y"}).json()["removed"] == 1
    assert c.get("/api/profile").json() == {"games": {}}


def test_bad_model_config_is_a_clear_503_not_a_crash(client):
    from coach.config import ConfigError
    c, webapp = client
    lid = c.post("/api/live/start").json()["live_id"]
    def broken():
        raise ConfigError("META_BASE_URL must be an https URL")
    old = webapp.app.state.client_factory
    webapp.app.state.client_factory = broken
    try:
        r = c.post(f"/api/overlay/{lid}/settings", json={"guide": True})
        assert r.status_code == 503 and "https" in r.json()["detail"]
    finally:
        webapp.app.state.client_factory = old
    c.post(f"/api/live/{lid}/stop")


def test_page_scripts_parse():
    """A single stray quote once killed every button on the dashboard. Parse each page's script with node."""
    import re, shutil, subprocess, tempfile
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    for page in ("index.html", "overlay.html"):
        html = (Path(__file__).resolve().parents[1] / "web" / "static" / page).read_text(encoding="utf-8")
        js = "\n".join(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S))
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
        assert r.returncode == 0, f"{page}: {r.stderr[:400]}"


def test_go_live_reachable_after_a_match_loads(client):
    """The hero (with Go live) hides once a match loads; the match card must offer Go live too."""
    c, _ = client
    html = c.get("/").text
    i = html.index('id="matchCard"'); j = html.index("</div>", html.index('id="sample2"'))
    assert 'id="golive2"' in html[i:j + 200] and "$('golive2').onclick=goLive" in html


def test_auto_callouts_wait_for_a_scene_change(client):
    """The watch tick is the expensive call; the page must skip it when the shared screen has not changed."""
    html = client[0].get("/").text
    assert "sceneDiff(" in html and "state.sceneChanged" in html and "WATCH_EVERY_MS=30000" in html


def test_one_coach_turn_at_a_time_per_session(client):
    """Loop safety: a second turn (or a watch tick) on a session that is still answering is refused, never queued."""
    import threading
    c, webapp = client
    lid = c.post("/api/live/start").json()["live_id"]
    gate = threading.Event()

    class SlowMeta:
        def post_json(self, path, payload):
            gate.wait(5)
            return {"id": "r1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}
    webapp.app.state.client_factory = lambda: SlowMeta()
    webapp._agents.clear()
    out = {}
    def first():
        with c.stream("POST", "/api/turn", json={"live_id": lid, "text": "hi"}) as r:
            out["status"] = r.status_code; out["body"] = "".join(r.iter_text())
    t = threading.Thread(target=first); t.start()
    for _ in range(50):          # wait until the first turn is marked busy
        if f"live:{lid}" in webapp._busy:
            break
        __import__("time").sleep(0.02)
    assert f"live:{lid}" in webapp._busy
    r2 = c.post("/api/turn", json={"live_id": lid, "text": "again"})
    assert r2.status_code == 409 and "still answering" in r2.json()["detail"]
    r3 = c.post("/api/turn", json={"live_id": lid, "watch": True})
    assert r3.status_code == 409
    gate.set(); t.join(10)
    assert out["status"] == 200 and "event: done" in out["body"] and '"game": "live session"' in out["body"]
    assert f"live:{lid}" not in webapp._busy
    assert c.post("/api/turn", json={"live_id": lid, "text": "free again"}).status_code == 200


def test_dashboard_hands_free_and_player_readable_steps(client):
    html = client[0].get("/").text
    assert 'id="listen"' in html and "Coach, stop talking" in html and "Coach, talk to me" in html
    assert "function plainStep(" in html and 'id="details"' in html and 'id="gameTag"' in html
    assert 'id="howto"' in html and "docs/vr.md" in html and "docs/pc-overlay.md" in html


def test_coach_windows_open_on_go_live_and_by_voice(client):
    html = client[0].get("/").text
    assert 'id="autoopen"' in html and "function showCoachWindows(" in html and 'id="openPrompt"' in html
    assert "Coach, show overlay" in html
    assert "v.play().catch(()=>{});   // not awaited" in html     # a frameless share must not stall go live


def test_overlay_is_embedded_in_the_live_view_and_theater_exists(client):
    """The recording lesson: arrows, tasks and memes must be visible inside the dashboard itself."""
    html = client[0].get("/").text
    assert 'id="ovFrame"' in html and "/overlay?live='+state.live+'&embed=1'" in html
    assert 'id="theater"' in html and "body.theater" in html and 'id="theaterExit"' in html
    assert "openCorner(false)" in html and "navigator.userActivation" in html
    ov = client[0].get("/overlay?live=x&embed=1").text
    assert "embed=q.get('embed')" in ov or "q.get('embed')" in ov


def test_access_codes_gate_the_api_and_budget_per_code(tmp_path, monkeypatch):
    """Hosted demo: with COACH_ACCESS_CODES set, every /api call needs a code; health stays open; the code is the budget subject."""
    monkeypatch.setenv("COACH_DATA", str(tmp_path / "data")); monkeypatch.setenv("COACH_ACCESS_CODES", "judge-one, judge-two")
    import importlib, web.app as webapp
    importlib.reload(webapp)
    c = TestClient(webapp.app)
    assert c.get("/").status_code == 200                       # the page itself loads
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/access").json() == {"required": True, "ok": False}
    assert c.get("/api/reactions").status_code == 401
    assert c.post("/api/access", json={"code": "nope"}).status_code == 403
    r = c.post("/api/access", json={"code": "judge-one"})
    assert r.status_code == 200 and "coach_code" in r.cookies
    assert c.get("/api/access").json() == {"required": True, "ok": True}
    assert c.get("/api/reactions").status_code == 200
    class Req:  # subject is the code, so budgets are per judge
        cookies = {"coach_code": "judge-one"}; headers = {}; client = None
    assert webapp._subject(Req()) == "code:judge-one"
    monkeypatch.delenv("COACH_ACCESS_CODES"); importlib.reload(webapp)
    assert TestClient(webapp.app).get("/api/access").json() == {"required": False, "ok": True}


def test_hero_banner_and_big_start_buttons(client):
    c, _ = client
    html = c.get("/").text
    assert 'class="banner" src="/static/banner.jpg"' in html and c.get("/static/banner.jpg").status_code == 200
    for label in ("Play with Coach", "Try a demo match", "Load my video"):
        assert label in html
    assert 'class="btn big"' in html and "#gameTag[hidden]{display:none}" in html
