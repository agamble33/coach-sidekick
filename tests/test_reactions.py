import json
import sys
from pathlib import Path

import pytest

from coach.reactions.engine import ReactionEngine, ReactionError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "src" / "coach" / "reactions"


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def tick(self, s):
        self.t += s


@pytest.fixture
def clk():
    return Clock()


@pytest.fixture
def eng(clk):
    return ReactionEngine(clock=clk, spice="unhinged")


def test_every_trigger_has_real_assets():
    eng = ReactionEngine()
    assert eng.check_assets() == []
    assert len(eng.reactions) >= 9


def test_config_shape():
    raw = json.loads((ROOT / "reactions.json").read_text())
    trig = [r["trigger"] for r in raw["reactions"]]
    assert len(trig) == len(set(trig)), "duplicate triggers"
    for r in raw["reactions"]:
        assert r["lines"], f"{r['trigger']} has no lines"
        assert r["image"].startswith("images/") and r["sound"].startswith("sounds/")


def test_fire_returns_payload(eng):
    p = eng.fire("missed_jump", "fell off the ledge")
    assert p and p["type"] == "reaction"
    assert p["image"] == "/reactions/images/classic/cackle.png"  # classic (the original memes) is the default pack
    assert p["sound"] == "/reactions/sounds/womp.mp3"
    assert p["line"] in eng.reactions["missed_jump"].lines
    assert p["show_ms"] == 2600 and p["context"] == "fell off the ledge"


def test_unknown_trigger_is_safe(eng):
    assert eng.fire("nope") is None
    assert eng.handle_tool_call({"trigger": "nope"}) == {"fired": False, "reason": "unknown trigger 'nope'"}


def test_trigger_cooldown(eng, clk):
    assert eng.fire("dumb_play")
    assert eng.fire("dumb_play") is None
    clk.tick(7.9)
    assert eng.fire("dumb_play") is None
    clk.tick(0.2)
    assert eng.fire("dumb_play")


def test_global_cooldown_between_different_triggers(eng, clk):
    assert eng.fire("whiff")
    assert eng.fire("clutch") is None, "global cooldown should block a different trigger"
    clk.tick(3.0)
    assert eng.fire("clutch")


def test_spice_off_blocks_everything(clk):
    e = ReactionEngine(clock=clk, spice="off")
    assert all(e.fire(t) is None for t in e.reactions)


def test_spice_mild_hides_unhinged_only(clk):
    e = ReactionEngine(clock=clk, spice="mild")
    assert e.fire("shocked") is None
    assert e.can_fire("shocked")[1].startswith("spice level")
    assert e.fire("missed_jump")


def test_set_spice_validates(eng):
    with pytest.raises(ReactionError):
        eng.set_spice("nuclear")
    eng.set_spice("off")
    assert eng.fire("whiff") is None


def test_missing_asset_is_caught(tmp_path):
    cfg = json.loads((ROOT / "reactions.json").read_text())
    cfg["reactions"][0]["image"] = "images/does_not_exist.png"
    p = tmp_path / "r.json"
    p.write_text(json.dumps(cfg))
    with pytest.raises(ReactionError, match="does_not_exist"):
        ReactionEngine(config_path=p)


def test_tool_schema_lists_all_triggers(eng):
    s = eng.tool_schema()
    assert s["function"]["name"] == "react"
    assert set(s["function"]["parameters"]["properties"]["trigger"]["enum"]) == set(eng.reactions)
    for t in eng.reactions:
        assert t in s["function"]["description"]


def test_handle_tool_call_roundtrip(eng):
    r = eng.handle_tool_call({"trigger": "rizz_detected", "context": "player said 'hey girl' in voice"})
    assert r["fired"] and r["payload"]["trigger"] == "rizz_detected"
    r2 = eng.handle_tool_call({"trigger": "rizz_detected"})
    assert r2 == {"fired": False, "reason": "global cooldown"}
    eng.clock.tick(4)  # past global (3s), still inside trigger cooldown (8s)
    r3 = eng.handle_tool_call({"trigger": "rizz_detected"})
    assert r3 == {"fired": False, "reason": "trigger cooldown"}


def test_lines_rotate(eng, clk):
    seen = set()
    for _ in range(40):
        seen.add(eng.fire("clutch")["line"])
        clk.tick(10)
    assert len(seen) == len(eng.reactions["clutch"].lines)


def test_pack_classic_uses_polished_original_when_present(clk):
    e = ReactionEngine(clock=clk, spice="unhinged", pack="classic")
    p = e.fire("dumb_play")  # horse has a classic version
    assert p["image"] == "/reactions/images/classic/horse_judge.png" and p["pack"] == "classic"
    assert (ROOT / "assets/images/classic/horse_judge.png").is_file()


def test_pack_classic_falls_back_to_3d_when_missing(clk):
    e = ReactionEngine(clock=clk, spice="unhinged", pack="classic")
    p = e.fire("rizz_detected")  # no safe original for this one
    assert p["image"] == "/reactions/images/rizz.png"
    assert not (ROOT / "assets/images/classic/rizz.png").exists()


def test_set_pack_validates(eng):
    with pytest.raises(ReactionError):
        eng.set_pack("vhs")
    eng.set_pack("classic")
    assert eng.fire("slow_reaction")["image"].endswith("classic/sleepy_dog.png")


def test_every_classic_card_is_512_square():
    PIL = pytest.importorskip("PIL.Image")
    for p in (ROOT / "assets/images/classic").glob("*.png"):
        assert PIL.open(p).size == (512, 512), p


# ---- integration with Coach's tools / overlay ----

def test_react_tool_updates_overlay_and_annotations(tmp_path):
    from coach.tools import Session, run_tool, TOOLS
    from coach.memory import MatchMemory
    from coach.annotations import AnnotationStore
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "mem.json"), annotations=AnnotationStore(tmp_path / "ann.jsonl"))
    s.reactions.set_spice("unhinged")
    assert "react" in TOOLS and "trigger" in TOOLS["react"].parameters["properties"]
    out = run_tool(s, "react", {"trigger": "missed_jump", "context": "fell off the ledge"})
    assert out.startswith("reacted missed_jump:")
    snap = s.overlay.snapshot()
    assert snap["reaction"]["trigger"] == "missed_jump" and snap["reaction"]["image"].startswith("/reactions/images/")
    # second call inside the cooldown is a calm "no reaction", never an error
    out2 = run_tool(s, "react", {"trigger": "missed_jump"})
    assert out2.startswith("no reaction (")
    assert run_tool(s, "react", {"trigger": "not_a_thing"}).startswith("no reaction (unknown trigger")


def test_react_is_a_live_tick_tool():
    from coach.agent import LIVE_TICK_TOOLS
    assert "react" in LIVE_TICK_TOOLS


def test_avatar_default_and_switch(clk):
    e = ReactionEngine(clock=clk, spice="mild")
    assert e.avatar == "muse_bot" and e.avatar_url() == "/reactions/avatars/muse_bot.png"
    assert set(e.state()["avatars"]) == {"muse_bot", "coach", "dog"}
    for a in ("coach", "dog"):
        e.set_avatar(a)
        p = e.fire("whiff"); clk.tick(10)
        assert p["avatar"] == a and p["avatar_url"] == f"/reactions/avatars/{a}.png"
        assert (ROOT / "assets" / "avatars" / f"{a}.png").is_file()
    with pytest.raises(ReactionError):
        e.set_avatar("cat")


def test_state_reports_enabled():
    e = ReactionEngine(spice="off")
    assert e.state()["enabled"] is False
    e.set_spice("mild")
    assert e.state()["enabled"] is True and e.state()["spice"] == "mild"


def test_packaged_assets_are_declared():
    # Render pip-installs the project; without package-data the cards would 404 in production.
    txt = (ROOT.parent.parent.parent / "pyproject.toml").read_text()
    assert '"coach.reactions"' in txt and "assets/**/*.png" in txt and "assets/**/*.mp3" in txt


def test_classic_is_default_and_rizz_falls_back_to_3d(eng):
    assert eng.pack == "classic"
    assert eng.fire("clutch")["image"] == "/reactions/images/classic/big_brain.png"
    eng._last_any = float("-inf")  # skip the global cooldown
    p = eng.fire("rizz_detected")
    assert p and p["image"] == "/reactions/images/rizz.png"
