import json

import pytest

from coach.incidents import CATEGORIES, Incident, IncidentStore, send_alert

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40 + b"\xff\xd9"


def test_store_add_status_and_reload(tmp_path):
    s = IncidentStore(tmp_path / "inc" / "incidents.jsonl")
    inc = s.add("bullying", "high", "  Chat says 'kill yourself noob'  repeated 3 times ", who="xXslayerXx",
                game="Regrade Arena", live_id="abc", audience="kids", frame_jpeg=JPEG)
    assert inc.summary == "Chat says 'kill yourself noob' repeated 3 times" and inc.status == "open"
    assert (tmp_path / "inc" / "frames" / inc.frame).read_bytes() == JPEG
    s.add("bug", "low", "Player clipped through the east wall", frame_jpeg=b"not a jpeg")
    assert s.recent()[0].category == "bug" and s.recent()[0].frame == ""
    assert [i.id for i in s.recent(status="open", category="bullying")] == [inc.id]
    s.set_status(inc.id, "confirmed", "reported to the studio")
    assert s.stats() == {"total": 2, "open": 1, "by_category": {**{c: 0 for c in CATEGORIES}, "bullying": 1, "bug": 1}}
    # a fresh store reads the records and the status update back from disk
    s2 = IncidentStore(tmp_path / "inc" / "incidents.jsonl")
    assert s2.get(inc.id).status == "confirmed" and s2.get(inc.id).note == "reported to the studio"
    assert s2.stats()["total"] == 2
    with pytest.raises(ValueError):
        s.add("gossip", "low", "x")
    with pytest.raises(ValueError):
        s.add("bug", "urgent", "x")
    with pytest.raises(ValueError):
        s.add("bug", "low", "   ")
    with pytest.raises(ValueError):
        s.set_status(inc.id, "deleted")
    with pytest.raises(KeyError):
        s.set_status("nope", "open")


def test_send_alert_posts_json_and_never_raises(monkeypatch):
    inc = Incident(id="i1", ts=1.0, category="hack", severity="high", summary="Speed hack, player crossed the map in 1 s",
                   who="", game="G", mode="live", live_id="L", frame="i1.jpg", audience="")
    seen = {}

    class R:
        status = 204
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_open(req, timeout=0):
        seen["url"] = req.full_url; seen["body"] = json.loads(req.data.decode()); seen["ct"] = req.get_header("Content-type")
        return R()

    monkeypatch.setattr("coach.incidents.urllib.request.urlopen", fake_open)
    assert send_alert(inc, "https://hooks.example/abc") is True
    assert seen["url"] == "https://hooks.example/abc" and seen["ct"] == "application/json"
    assert "Speed hack" in seen["body"]["text"] and seen["body"]["incident"]["id"] == "i1" and "extra" not in seen["body"]["incident"]
    assert send_alert(inc, "") is False                      # no webhook configured
    monkeypatch.setattr("coach.incidents.urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert send_alert(inc, "https://hooks.example/abc") is False   # failure is swallowed
