"""Gate 11: Guide me. Coach points and draws routes only when the player turned it on."""
import json

from coach.agent import CoachAgent, GUIDE_TOOLS, LIVE_TICK_TOOLS, WATCH_PROMPT, instructions_for
from coach.config import load_settings
from coach.memory import MatchMemory
from coach.meta_api import MetaClient
from coach.tools import Overlay, Session, TOOLS, run_tool

ENV = {"META_API_KEY": "k", "META_BASE_URL": "https://x.example/v1"}


def session(tmp_path, guide):
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "mem.json"))
    s.overlay.guide = guide
    return s


def test_point_and_route_are_gated(tmp_path):
    s = session(tmp_path, guide=False)
    assert run_tool(s, "point", {"x": 0.5, "y": 0.5, "label": "Exit"}).startswith("guide mode is off")
    assert run_tool(s, "route", {"steps": [{"x": 0.1, "y": 0.1}]}).startswith("guide mode is off")
    assert s.overlay.snapshot()["pointers"] == [] and s.overlay.snapshot()["route"] == []


def test_point_draws_arrow_and_edge_arrow(tmp_path):
    s = session(tmp_path, guide=True)
    out = run_tool(s, "point", {"x": 0.72, "y": 0.4, "label": "East gate"})
    assert out.startswith("pointed East gate (here)")
    out2 = run_tool(s, "point", {"x": 0.02, "y": 0.5, "label": "Key", "direction": "left", "seconds": 20})
    assert "off screen, left" in out2
    snap = s.overlay.snapshot()
    assert [p["label"] for p in snap["pointers"]] == ["East gate", "Key"]
    assert snap["pointers"][1]["direction"] == "left" and snap["pointers"][1]["seconds"] == 20
    assert snap["guide"] is True
    # bad direction is an error string, never an exception
    assert run_tool(s, "point", {"x": 0.5, "y": 0.5, "direction": "sideways"}).startswith("error")


def test_pointer_cap_and_min_seconds(tmp_path):
    s = session(tmp_path, guide=True)
    for i in range(5):
        run_tool(s, "point", {"x": 0.1 * i, "y": 0.5, "label": f"p{i}", "seconds": 1})
    snap = s.overlay.snapshot()
    assert len(snap["pointers"]) == Overlay.MAX_POINTERS
    assert all(p["seconds"] >= 8 for p in snap["pointers"]), "floor of 8 s like highlights"


def test_route_numbers_steps_and_caps(tmp_path):
    s = session(tmp_path, guide=True)
    steps = [{"x": 0.1 * i, "y": 0.5, "label": f"s{i}"} for i in range(8)]
    out = run_tool(s, "route", {"steps": steps})
    assert out.startswith("route with 6 steps")
    r = s.overlay.snapshot()["route"]
    assert [w["n"] for w in r] == [1, 2, 3, 4, 5, 6] and r[0]["label"] == "s0"
    assert run_tool(s, "route", {"steps": []}).startswith("error")
    assert run_tool(s, "route", {"steps": [{"x": 2, "y": 0}]}).startswith("error")


def test_turning_guide_off_clears_guidance(tmp_path):
    s = session(tmp_path, guide=True)
    run_tool(s, "point", {"x": 0.5, "y": 0.5})
    run_tool(s, "route", {"steps": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}]})
    s.overlay.guide = False
    assert s.overlay.snapshot()["pointers"] == [] and s.overlay.snapshot()["route"] == []
    s.overlay.clear_guidance()
    s.overlay.guide = True
    assert s.overlay.snapshot()["pointers"] == []


def test_finish_turn_rebases_pointers_and_route(tmp_path):
    s = session(tmp_path, guide=True)
    s.overlay.start_turn()
    run_tool(s, "point", {"x": 0.5, "y": 0.5, "seconds": 8})
    run_tool(s, "route", {"steps": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}], "seconds": 10})
    before = (s.overlay.pointers[0]["until"], s.overlay.route[0]["until"])
    import time; time.sleep(0.05)
    s.overlay.finish_turn()
    assert s.overlay.pointers[0]["until"] > before[0] and s.overlay.route[0]["until"] > before[1]


class Scripted:
    def __init__(self, responses):
        self.responses, self.payloads = list(responses), []

    def __call__(self, method, url, headers, body):
        self.payloads.append(json.loads(body))
        return 200, json.dumps(self.responses.pop(0)).encode()


def msg(text):
    return {"id": "r1", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 1, "output_tokens": 1}}


def test_tick_offers_guide_tools_only_when_on(tmp_path):
    for guide in (False, True):
        s = session(tmp_path, guide=guide)
        t = Scripted([msg("quiet")])
        CoachAgent(MetaClient(load_settings(ENV), t), s).turn(WATCH_PROMPT)
        names = [x["name"] for x in t.payloads[0]["tools"]]
        assert ("point" in names) is guide and ("route" in names) is guide
        assert set(LIVE_TICK_TOOLS) <= set(names)
        assert ("Guide me is ON" in t.payloads[0]["instructions"]) is guide


def test_plain_turn_hides_guide_tools_when_off(tmp_path):
    s = session(tmp_path, guide=False)
    t = Scripted([msg("ok")])
    CoachAgent(MetaClient(load_settings(ENV), t), s).turn("where do I go?")
    names = [x["name"] for x in t.payloads[0]["tools"]]
    assert not (set(GUIDE_TOOLS) & set(names)) and "callout" in names
    assert "point" in TOOLS and "route" in TOOLS
