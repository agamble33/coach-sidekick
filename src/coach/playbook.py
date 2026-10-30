"""Gate 7a: the studio playbook. Rules, controls and goals a studio gives Coach so it
can teach new players inside the game. Stored as one JSON file; injected into the
agent's instructions; validated and capped so a bad upload can't break a session.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_CHARS = 6000
SECTIONS = ("goal", "controls", "rules", "tips", "mistakes")


class PlaybookError(ValueError):
    pass


@dataclass(frozen=True)
class Playbook:
    game: str
    goal: str = ""
    controls: str = ""
    rules: str = ""
    tips: str = ""
    mistakes: str = ""

    def as_prompt(self) -> str:
        parts = [f"PLAYBOOK for {self.game}. Use it to teach a new player while they play. "
                 "Teach one thing at a time, in the moment it matters, in one or two sentences."]
        for name in SECTIONS:
            text = getattr(self, name).strip()
            if text:
                parts.append(f"{name.upper()}: {text}")
        return "\n".join(parts)

    def total_chars(self) -> int:
        return sum(len(getattr(self, n)) for n in SECTIONS) + len(self.game)


def _clean(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def make_playbook(data: dict) -> Playbook:
    if not isinstance(data, dict):
        raise PlaybookError("playbook must be an object")
    game = _clean(data.get("game"), 80)
    if not game:
        raise PlaybookError("game name is required")
    pb = Playbook(game=game, **{n: _clean(data.get(n), MAX_CHARS) for n in SECTIONS})
    if pb.total_chars() > MAX_CHARS:
        raise PlaybookError(f"playbook is longer than {MAX_CHARS} characters")
    if not any(getattr(pb, n) for n in SECTIONS):
        raise PlaybookError("add at least one section: goal, controls, rules, tips or mistakes")
    return pb


class PlaybookStore:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    def load(self) -> Playbook | None:
        if not self.path.is_file():
            return None
        try:
            return make_playbook(json.loads(self.path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            return None

    def save(self, data: dict) -> Playbook:
        pb = make_playbook(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(pb), indent=1), encoding="utf-8")
        return pb

    def clear(self) -> None:
        if self.path.is_file():
            self.path.unlink()
