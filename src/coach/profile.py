"""Gate 13c: the player's Coach profile. What they like, per game: controls, sound, display, and a
few free-form preferences. Small JSON file, same shape as match memory. Coach reads it into its
instructions when the game is known and offers to set things the way the player likes.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

CATEGORIES = ("controls", "sound", "display", "play", "skills")   # play = pace, tone, how much Coach talks; skills = what Coach has seen them do well or struggle with
MAX_PER_GAME = 24
MAX_VALUE = 120


def _clean(v, n=MAX_VALUE) -> str:
    return " ".join(str(v if v is not None else "").split())[:n]


class PlayerProfile:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._data: dict = {"games": {}, "player": {}}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = {"games": dict(raw.get("games", {})), "player": dict(raw.get("player", {}))}
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=1), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _key(game: str) -> str:
        return _clean(game, 60).lower() or "any game"

    def set(self, game: str, category: str, name: str, value: str) -> dict:
        category = _clean(category, 20).lower()
        if category not in CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(CATEGORIES)}")
        name = _clean(name, 40).lower()
        value = _clean(value)
        if not name or not value:
            raise ValueError("name and value are required")
        g = self._data["games"].setdefault(self._key(game), {})
        entry = {"category": category, "value": value, "updated": time.time()}
        if name not in g and len(g) >= MAX_PER_GAME:
            oldest = min(g, key=lambda k: g[k]["updated"])
            del g[oldest]
        g[name] = entry
        self._save()
        return {"game": self._key(game), "name": name, **entry}

    def forget(self, game: str, name: str = "") -> int:
        key = self._key(game)
        g = self._data["games"].get(key)
        if not g:
            return 0
        if name:
            n = 1 if g.pop(_clean(name, 40).lower(), None) else 0
            if not g:
                del self._data["games"][key]
        else:
            n = len(g)
            del self._data["games"][key]
        self._save()
        return n

    def get(self, game: str) -> dict:
        return dict(self._data["games"].get(self._key(game), {}))

    def games(self) -> list[str]:
        return sorted(self._data["games"])

    def as_prompt(self, game: str) -> str:
        """Instructions block for a known game, or '' when nothing is stored."""
        prefs = self.get(game)
        general = self.get("any game") if self._key(game) != "any game" else {}
        if not prefs and not general:
            return ""
        lines = [f"PLAYER PROFILE for {self._key(game)} (what this player likes; use it, and offer to set it up when the game starts):"]
        for cat in CATEGORIES:
            items = [f"{n}={e['value']}" for n, e in {**general, **prefs}.items() if e["category"] == cat]
            if items:
                lines.append(f"{cat}: " + "; ".join(items))
        lines.append("If a setting looks different from this on screen, say so once and offer to walk them through it. "
                     "When they tell you a new preference, save it with remember_preference.")
        if any(e["category"] == "skills" for e in {**general, **prefs}.values()):
            lines.append("skills are things you have seen this player do well or struggle with. Mention them once when the "
                         "session starts, coach toward the weak spots without nagging, and update them when you see change.")
        return "\n".join(lines)

    def snapshot(self) -> dict:
        return {"games": {g: {n: dict(e) for n, e in prefs.items()} for g, prefs in self._data["games"].items()}}
