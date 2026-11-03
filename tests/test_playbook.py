import json

import pytest

from coach.agent import AGENT_SYSTEM, TEACH_PROMPT, CoachAgent, instructions_for
from coach.config import load_settings
from coach.memory import MatchMemory
from coach.meta_api import MetaClient
from coach.playbook import MAX_CHARS, Playbook, PlaybookError, PlaybookStore, make_playbook
from coach.tools import Session

GOOD = {"game": "Rocket Rally", "goal": "Score more goals than the other team in 5 minutes.",
        "controls": "A/D steer, Space boost, Shift drift.", "mistakes": "Chasing the ball while your goal is empty."}


def test_make_playbook_cleans_and_validates():
    pb = make_playbook({"game": "  Rocket   Rally ", "goal": "  Score\n goals  "})
    assert pb.game == "Rocket Rally" and pb.goal == "Score goals" and pb.controls == ""
    for bad in [{}, {"game": "x"}, {"game": "", "goal": "y"}, "nope", {"game": "x", "goal": "y" * (MAX_CHARS + 1)}]:
        with pytest.raises(PlaybookError):
            make_playbook(bad)


def test_as_prompt_only_includes_filled_sections():
    p = make_playbook(GOOD).as_prompt()
    assert p.startswith("PLAYBOOK for Rocket Rally") and "GOAL:" in p and "MISTAKES:" in p
    assert "RULES:" not in p and "TIPS:" not in p


def test_store_round_trip_and_corrupt(tmp_path):
    st = PlaybookStore(tmp_path / "pb.json")
    assert st.load() is None
    st.save(GOOD)
    assert st.load().game == "Rocket Rally"
    (tmp_path / "pb.json").write_text("{broken")
    assert st.load() is None
    st.save(GOOD); st.clear()
    assert st.load() is None


def test_instructions_include_playbook_and_teach(tmp_path):
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"))
    assert instructions_for(s).startswith(AGENT_SYSTEM) and "GAME: unknown" in instructions_for(s)
    s.playbook = make_playbook(GOOD)
    assert "PLAYBOOK for Rocket Rally" in instructions_for(s) and "NEW" not in instructions_for(s)
    s.teach = True
    assert "The player is NEW" in instructions_for(s)


def test_agent_sends_playbook_in_request(tmp_path):
    payloads = []

    def transport(method, url, headers, body):
        payloads.append(json.loads(body))
        return 200, json.dumps({"id": "r1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hold Space to boost."}]}]}).encode()

    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"), playbook=make_playbook(GOOD), teach=True)
    a = CoachAgent(MetaClient(load_settings({"META_API_KEY": "k", "META_BASE_URL": "https://x.example/v1"}), transport), s)
    r = a.turn("how do I go faster?")
    assert r.text == "Hold Space to boost."
    assert "Space boost" in payloads[0]["instructions"] and "The player is NEW" in payloads[0]["instructions"]
    assert "Teach tick" in TEACH_PROMPT and "look_now" in TEACH_PROMPT
