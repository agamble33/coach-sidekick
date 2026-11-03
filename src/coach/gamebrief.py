"""Game brief: what Coach knows about a game from the model's own training, written once per game
and cached. Built the moment Coach names the game (set_game) so it can talk the game's language,
know the modes and levels, and watch for rookie mistakes without a studio playbook. A studio
playbook, when present, takes priority in the instructions."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from .coach_llm import DEFAULT_MODEL, parse_reply

BRIEF_PROMPT = (
    "Write a compact coaching brief for the video game {game}, from what you know. Plain text, no markdown, "
    "no em dashes. Six short sections, each one line starting with the label: "
    "HOW IT PLAYS: the core loop and what winning means. "
    "WORDS: 8 to 12 terms and callouts players actually use, with a two or three word meaning each. "
    "MODES AND LEVELS: the main modes, maps, worlds or levels, and how progress works. "
    "FIRST HOUR: what a brand new player should do first. "
    "ROOKIE MISTAKES: four common ones. "
    "DANGER SIGNS: what on screen means the player is about to die or lose, so a teammate would call it out. "
    "If you are not confident you know this game, write exactly: UNKNOWN GAME and nothing else. "
    "Keep the whole brief under 220 words."
)
MAX_BRIEF_CHARS = 2500


def _key(game: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", game.strip().lower()).strip("-")[:60] or "unknown"


class GameBriefStore:
    def __init__(self, path: Path, model: str = DEFAULT_MODEL):
        self.path, self.model = Path(path), model
        self._lock = threading.Lock()
        self._pending: set[str] = set()

    def _file(self, game: str) -> Path:
        return self.path / f"{_key(game)}.json"

    def get(self, game: str) -> str:
        """The cached brief text, or '' if none (or the model did not know the game)."""
        try:
            raw = json.loads(self._file(game).read_text(encoding="utf-8"))
            return str(raw.get("brief", ""))
        except (OSError, ValueError):
            return ""

    def known(self, game: str) -> bool:
        return self._file(game).exists()

    def ensure(self, game: str, client) -> str:
        """Return the brief, writing it with one model call if this is the first time we see the game."""
        game = " ".join(game.split())[:60]
        if not game:
            return ""
        with self._lock:
            if self.known(game):
                return self.get(game)
            if client is None or _key(game) in self._pending:
                return ""
            self._pending.add(_key(game))
        try:
            payload = {"model": self.model, "instructions": "You are a precise esports coach writing notes for a teammate.",
                       "input": [{"role": "user", "content": [{"type": "input_text", "text": BRIEF_PROMPT.format(game=game)}]}],
                       "reasoning": {"effort": "low"}, "stream": False}
            text = parse_reply(client.post_json("/responses", payload)).text.strip()
            brief = "" if text.upper().startswith("UNKNOWN GAME") else text[:MAX_BRIEF_CHARS]
            self.path.mkdir(parents=True, exist_ok=True)
            self._file(game).write_text(json.dumps({"game": game, "brief": brief, "model": self.model, "at": time.time()}, indent=1), encoding="utf-8")
            return brief
        except Exception:
            return ""
        finally:
            with self._lock:
                self._pending.discard(_key(game))

    def as_prompt(self, game: str) -> str:
        brief = self.get(game)
        if not brief:
            return ""
        return (f"GAME BRIEF for {game} (from your own knowledge; the screen and the player's words win when they disagree):\n"
                f"{brief}\nUse the game's own words in callouts. Teach one thing at a time.")
