"""Gate 12: Game SDK. A fake game posts state; Coach reasons on it, points at landmarks, reacts to events."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coach.agent import CoachAgent, WATCH_PROMPT, instructions_for
from coach.config import load_settings
from coach.gamestate import EVENT_ALIASES, GameState, Landmark
from coach.memory import MatchMemory
from coach.meta_api import MetaClient
from coach.tools import Session, run_tool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
import fake_game  # noqa: E402

ENV = {"META_API_KEY": "k", "META_BASE_URL": "https://x.example/v1"}


def test_landmark_parse_normalises_ids_and_validates_screen():
    lm = Landmark.parse({"id": "East Gate", "visible": True, "screen": [1.4, 0.2], "dir": "nowhere"})
    assert lm.id == "east_gate" and lm.label == "east_gate" and lm.visible is False and lm.screen is None and lm.dir == ""
    assert Landmark.parse({"label": "no id"}) is None


def test_update_maps_events_and_keeps_prompt_factual():
    g = GameState()
    trig = g.update({"game": "X", "player": {"pos": [1, 2, 3], "hp": 9, "secret": "nope"}, "objective": "find key",
                     "landmarks": [{"id": "door", "label": "Door", "visible": True, "screen": [0.7, 0.4]},
                                   {"id": "key", "dir": "left"}],
                     "events": [{"type": "fell"}, {"type": "clutch"}, {"type": "unknown thing"}]})
    assert trig == ["missed_jump", "clutch", "unknown_thing"]
    assert "secret" not in g.player and g.fresh()
    p = g.as_prompt()
    assert "GAME STATE" in p and "door (Door) on screen at x=0.70 y=0.40" in p and "key (key) off screen, left" in p
    assert "recent events: fell, clutch, unknown_thing" in p
    for k, v in EVENT_ALIASES.items():
        assert v in {"missed_jump", "near_death", "slow_reaction", "dumb_play", "clutch"}


def test_stale_state_is_not_in_prompt():
    g = GameState()
    g.update({"objective": "x"})
    g.updated -= 100
    assert g.as_prompt() == "" and not g.fresh()


def test_point_resolves_landmark_on_screen_and_off(tmp_path):
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"))
    s.overlay.guide = True
    s.game_state.update({"landmarks": [{"id": "fountain", "label": "Fountain", "visible": True, "screen": [0.52, 0.55]},
                                 {"id": "east_gate", "label": "East gate", "dir": "right"}]})
    out = run_tool(s, "point", {"x": 0, "y": 0, "landmark": "fountain"})
    assert out.startswith("pointed Fountain (here) at (0.52, 0.55)")
    out2 = run_tool(s, "point", {"x": 0, "y": 0, "landmark": "East Gate"})
    assert "off screen, right" in out2
    ptrs = s.overlay.snapshot()["pointers"]
    assert ptrs[0]["landmark"] == "fountain" and ptrs[1]["landmark"] == "east_gate" and ptrs[1]["x"] == 0.94
    assert run_tool(s, "point", {"x": 0, "y": 0, "landmark": "moon"}).startswith("error: unknown landmark 'moon'")
    out3 = run_tool(s, "route", {"steps": [{"x": 0, "y": 0, "landmark": "fountain"}, {"x": 0, "y": 0, "landmark": "east_gate"}]})
    assert out3.startswith("route with 2 steps")
    assert [w["landmark"] for w in s.overlay.snapshot()["route"]] == ["fountain", "east_gate"]


def test_instructions_carry_game_state_only_when_fresh(tmp_path):
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"))
    assert "GAME STATE" not in instructions_for(s)
    s.game_state.update({"objective": "reach the gate"})
    assert "objective: reach the gate" in instructions_for(s)


class Scripted:
    def __init__(self, responses):
        self.responses, self.payloads = list(responses), []

    def __call__(self, method, url, headers, body):
        self.payloads.append(json.loads(body))
        return 200, json.dumps(self.responses.pop(0)).encode()


def test_agent_points_at_a_landmark_end_to_end(tmp_path):
    """Scripted model: on a watch tick it calls point with a landmark id, then says quiet."""
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"))
    s.overlay.guide = True
    s.game_state.update({"landmarks": [{"id": "east_gate", "label": "East gate", "dir": "right"}]})
    t = Scripted([
        {"id": "r1", "output": [{"type": "function_call", "name": "point", "call_id": "c1", "status": "completed",
                                 "arguments": json.dumps({"x": 0, "y": 0, "landmark": "east_gate"})}],
         "usage": {"input_tokens": 1, "output_tokens": 1}},
        {"id": "r2", "output": [{"type": "message", "content": [{"type": "output_text", "text": "quiet"}]}],
         "usage": {"input_tokens": 1, "output_tokens": 1}},
    ])
    CoachAgent(MetaClient(load_settings(ENV), t), s).turn(WATCH_PROMPT)
    assert "GAME STATE" in t.payloads[0]["instructions"]
    ptr = s.overlay.snapshot()["pointers"][0]
    assert ptr["landmark"] == "east_gate" and ptr["direction"] == "right"


def test_fake_game_projection():
    vis, scr, d = fake_game.project(0, 0, 0, 0, 10)       # straight ahead
    assert vis and abs(scr[0] - 0.5) < 0.01
    vis, scr, d = fake_game.project(0, 0, 0, -10, 0)      # to the left
    assert not vis and d == "left"
    vis, scr, d = fake_game.project(0, 0, 0, 0, -10)      # behind
    assert not vis and d == "behind"
    st = fake_game.state_at(7.2)
    assert st["events"] and st["events"][0]["type"] == "fell" and len(st["landmarks"]) == 3
