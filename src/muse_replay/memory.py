"""Gate 4a: match memory. A small JSON file so Coach remembers your last match."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_NOTES = 200


@dataclass(frozen=True)
class Note:
    ts: float
    match: str
    text: str


class MatchMemory:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._notes: list[Note] = []
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._notes = [Note(float(n["ts"]), str(n["match"]), str(n["text"])) for n in raw]
            except (ValueError, KeyError, TypeError):
                self._notes = []          # corrupt file: start fresh rather than crash mid-game

    def remember(self, match: str, text: str) -> Note:
        text = " ".join(text.split())[:500]
        if not text:
            raise ValueError("note is empty")
        note = Note(time.time(), match.strip()[:100] or "unknown", text)
        self._notes.append(note)
        self._notes = self._notes[-MAX_NOTES:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(n) for n in self._notes], indent=1), encoding="utf-8")
        return note

    def recall(self, match: str | None = None, limit: int = 10) -> list[Note]:
        notes = [n for n in self._notes if match is None or n.match == match]
        return notes[-max(1, limit):]

    def matches(self) -> list[str]:
        seen: dict[str, None] = {}
        for n in self._notes:
            seen.setdefault(n.match, None)
        return list(seen)

    def __len__(self) -> int:
        return len(self._notes)
