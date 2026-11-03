"""Gate 13c: player profile. Controls, sound, display per game; tools; instructions."""
import json

import pytest

from coach.agent import CoachAgent, LIVE_TICK_TOOLS, WATCH_PROMPT, instructions_for
from coach.config import load_settings
from coach.memory import MatchMemory
from coach.meta_api import MetaClient
from coach.playbook import Playbook
from coach.profile import PlayerProfile
from coach.tools import Session, TOOLS, run_tool

ENV = {"META_API_KEY": "k", "META_BASE_URL": "https://x.example/v1"}


def test_set_get_forget_and_persist(tmp_path):
    p = PlayerProfile(tmp_path / "p.json")
    rec = p.set("Kid Kart", "controls", "Invert Y", "on")
    assert rec["game"] == "kid kart" and rec["name"] == "invert y"
    p.set("Kid Kart", "sound", "master_volume", "40%")
    p.set("any game", "display", "brightness", "high")
    with pytest.raises(ValueError):
        p.set("Kid Kart", "weather", "x", "y")
    with pytest.raises(ValueError):
        p.set("Kid Kart", "sound", "", "y")
    again = PlayerProfile(tmp_path / "p.json")
    assert again.get("kid kart")["master_volume"]["value"] == "40%" and again.games() == ["any game", "kid kart"]
    assert again.forget("Kid Kart", "invert y") == 1 and "invert y" not in again.get("kid kart")
    assert again.forget("Kid Kart") == 1 and again.games() == ["any game"]


def test_prompt_merges_general_and_game(tmp_path):
    p = PlayerProfile(tmp_path / "p.json")
    p.set("any game", "display", "brightness", "high")
    p.set("Arena", "controls", "look_sensitivity", "6")
    p.set("Arena", "sound", "music", "off")
    text = p.as_prompt("Arena")
    assert "PLAYER PROFILE for arena" in text and "controls: look_sensitivity=6" in text
    assert "display: brightness=high" in text and "sound: music=off" in text and "offer to set it up" in text
    assert p.as_prompt("Other") and "brightness=high" in p.as_prompt("Other")   # general prefs apply everywhere
    assert PlayerProfile(tmp_path / "empty.json").as_prompt("Arena") == ""


def test_cap_per_game_evicts_oldest(tmp_path):
    p = PlayerProfile(tmp_path / "p.json")
    for i in range(30):
        p.set("G", "play", f"k{i}", "v")
    assert len(p.get("G")) == 24 and "k0" not in p.get("G") and "k29" in p.get("G")


def test_tools_and_instructions(tmp_path):
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"), profile=PlayerProfile(tmp_path / "p.json"),
                playbook=Playbook(game="Kid Kart"))
    assert "remember_preference" in TOOLS and "my_preferences" in TOOLS and "my_preferences" in LIVE_TICK_TOOLS
    assert run_tool(s, "my_preferences", {}) == "nothing saved yet"
    out = run_tool(s, "remember_preference", {"category": "controls", "name": "invert_y", "value": "on"})
    assert out == "saved for kid kart: controls invert_y = on"
    assert run_tool(s, "remember_preference", {"category": "nope", "name": "a", "value": "b"}).startswith("error")
    assert "invert_y (controls) = on" in run_tool(s, "my_preferences", {})
    assert "PLAYER PROFILE for kid kart" in instructions_for(s)
    s2 = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m2.json"))
    assert run_tool(s2, "remember_preference", {"category": "sound", "name": "x", "value": "y"}) == "no profile store attached"


class Scripted:
    def __init__(self, responses):
        self.responses, self.payloads = list(responses), []

    def __call__(self, method, url, headers, body):
        self.payloads.append(json.loads(body))
        return 200, json.dumps(self.responses.pop(0)).encode()


def test_agent_saves_a_preference_from_the_player(tmp_path):
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"), profile=PlayerProfile(tmp_path / "p.json"),
                playbook=Playbook(game="Arena"))
    t = Scripted([
        {"id": "r1", "output": [{"type": "function_call", "name": "remember_preference", "call_id": "c1", "status": "completed",
                                 "arguments": json.dumps({"category": "sound", "name": "master_volume", "value": "40%"})}],
         "usage": {"input_tokens": 1, "output_tokens": 1}},
        {"id": "r2", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Got it, 40 percent from now on."}]}],
         "usage": {"input_tokens": 1, "output_tokens": 1}},
    ])
    CoachAgent(MetaClient(load_settings(ENV), t), s).turn("keep the volume at 40 percent for this game")
    assert s.profile.get("Arena")["master_volume"]["value"] == "40%"
    assert "PLAYER PROFILE" not in t.payloads[0]["instructions"]     # nothing known on the first call
    t2 = Scripted([{"id": "r3", "output": [{"type": "message", "content": [{"type": "output_text", "text": "quiet"}]}],
                    "usage": {"input_tokens": 1, "output_tokens": 1}}])
    CoachAgent(MetaClient(load_settings(ENV), t2), s).turn(WATCH_PROMPT)
    assert "master_volume=40%" in t2.payloads[0]["instructions"]      # known next time
