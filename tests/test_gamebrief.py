import json

from coach.agent import instructions_for
from coach.gamebrief import GameBriefStore
from coach.memory import MatchMemory
from coach.tools import Session, run_tool


class FakeClient:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def post_json(self, path, payload):
        self.calls += 1
        assert "Rocket Rally" in json.dumps(payload)
        return {"id": "b1", "output": [{"type": "message", "content": [{"type": "output_text", "text": self.text}]}], "usage": {}}


BRIEF = ("HOW IT PLAYS: cars hit a ball into the goal. WORDS: boost = speed, demo = wreck a car. MODES AND LEVELS: 3v3 ranked. "
         "FIRST HOUR: learn to rotate. ROOKIE MISTAKES: ball chasing. DANGER SIGNS: empty net behind you.")


def test_brief_is_written_once_and_reaches_the_instructions(tmp_path):
    store = GameBriefStore(tmp_path / "briefs")
    client = FakeClient(BRIEF)
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"), match="live session", client=client, briefs=store)
    assert "GAME BRIEF" not in instructions_for(s)
    assert run_tool(s, "set_game", '{"name": "Rocket Rally"}') == "game set to Rocket Rally; brief ready"
    text = instructions_for(s)
    assert "GAME: Rocket Rally" in text and "GAME BRIEF for Rocket Rally" in text and "boost = speed" in text
    assert client.calls == 1
    store.ensure("Rocket Rally", client)      # cached: no second model call
    assert client.calls == 1
    assert (tmp_path / "briefs" / "rocket-rally.json").exists()


def test_unknown_game_is_remembered_as_unknown_and_not_retried(tmp_path):
    store = GameBriefStore(tmp_path / "briefs")
    client = FakeClient("UNKNOWN GAME")
    assert store.ensure("Rocket Rally", client) == "" and store.known("Rocket Rally")
    assert store.ensure("Rocket Rally", client) == "" and client.calls == 1
    assert store.as_prompt("Rocket Rally") == ""


def test_playbook_wins_over_the_brief(tmp_path):
    from coach.playbook import Playbook
    store = GameBriefStore(tmp_path / "briefs")
    store.ensure("Rocket Rally", FakeClient(BRIEF))
    s = Session(work_dir=tmp_path, memory=MatchMemory(tmp_path / "m.json"), match="live session", briefs=store,
                playbook=Playbook(game="Rocket Rally", goal="score"))
    text = instructions_for(s)
    assert "PLAYBOOK for Rocket Rally" in text and "GAME BRIEF" not in text


def test_model_failure_leaves_no_brief_and_no_crash(tmp_path):
    class Boom:
        def post_json(self, *a):
            raise RuntimeError("down")
    store = GameBriefStore(tmp_path / "briefs")
    assert store.ensure("Rocket Rally", Boom()) == "" and not store.known("Rocket Rally")
