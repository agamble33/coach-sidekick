"""Gate 12: structured game state from a game that integrates the Coach SDK.

A game posts a small JSON document every second or so (player, objective, landmarks it knows
about, recent events). Coach reads it as text in its instructions, so it reasons on facts before
spending a vision call, and the point / route tools can anchor on a landmark id the game can
resolve to a world position. Game events that match a reaction trigger fire the meme reaction
directly, no model round trip.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

MAX_LANDMARKS = 40
MAX_EVENTS = 20
FRESH_S = 15.0
DIRECTIONS = ("left", "right", "up", "down", "behind", "ahead")

# game event type -> reaction trigger (event types that already equal a trigger pass straight through)
EVENT_ALIASES = {
    "fell": "missed_jump", "fall": "missed_jump", "missed_platform": "missed_jump",
    "died": "near_death", "respawn": "near_death", "low_hp": "near_death",
    "idle": "slow_reaction", "afk": "slow_reaction",
    "friendly_fire": "dumb_play", "wasted_ult": "dumb_play",
    "kill_streak": "clutch", "objective_done": "clutch", "boss_down": "clutch", "headshot": "clutch", "ace": "clutch", "comeback": "clutch",
    "missed_shot": "whiff", "miss": "whiff", "teamkill": "dumb_play", "flirt": "rizz_detected", "ignored_hint": "ignored_callout",
    "revive_needed": "near_death", "downed": "near_death",
}


def _text(v, n=80) -> str:
    return " ".join(str(v if v is not None else "").split())[:n]


def _vec(v) -> list[float] | None:
    if not isinstance(v, (list, tuple)) or not 2 <= len(v) <= 3:
        return None
    try:
        return [round(float(x), 2) for x in v]
    except (TypeError, ValueError):
        return None


@dataclass
class Landmark:
    id: str
    label: str
    pos: list[float] | None = None     # world position, the game's own units
    visible: bool = False
    screen: list[float] | None = None  # [x, y] fractions of the screen when visible
    dir: str = ""                      # which way to turn when not visible

    @classmethod
    def parse(cls, raw: dict) -> "Landmark | None":
        lid = _text(raw.get("id"), 40).replace(" ", "_").lower()
        if not lid:
            return None
        screen = _vec(raw.get("screen"))
        if screen is not None and not (len(screen) == 2 and 0 <= screen[0] <= 1 and 0 <= screen[1] <= 1):
            screen = None
        d = _text(raw.get("dir"), 10).lower()
        return cls(id=lid, label=_text(raw.get("label") or lid, 40), pos=_vec(raw.get("pos")),
                   visible=bool(raw.get("visible")) and screen is not None, screen=screen,
                   dir=d if d in DIRECTIONS else "")


@dataclass
class GameState:
    game: str = ""
    player: dict = field(default_factory=dict)
    objective: str = ""
    landmarks: dict[str, Landmark] = field(default_factory=dict)
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    updated: float = 0.0
    posts: int = 0

    def update(self, raw: dict) -> list[str]:
        """Merge one post from the game. Returns the reaction triggers its events map to."""
        if not isinstance(raw, dict):
            raise ValueError("state must be a JSON object")
        if "game" in raw:
            self.game = _text(raw.get("game"), 60)
        if isinstance(raw.get("player"), dict):
            p = raw["player"]
            self.player = {k: (_vec(v) if k == "pos" else (_text(v, 40) if isinstance(v, str) else v))
                           for k, v in p.items() if k in ("pos", "yaw", "hp", "state", "name", "level")}
        if "objective" in raw:
            self.objective = _text(raw.get("objective"), 120)
        if isinstance(raw.get("landmarks"), list):
            for item in raw["landmarks"][:MAX_LANDMARKS]:
                if isinstance(item, dict):
                    lm = Landmark.parse(item)
                    if lm:
                        self.landmarks[lm.id] = lm
            if len(self.landmarks) > MAX_LANDMARKS:
                for k in list(self.landmarks)[: len(self.landmarks) - MAX_LANDMARKS]:
                    del self.landmarks[k]
        triggers: list[str] = []
        if isinstance(raw.get("events"), list):
            for ev in raw["events"][:MAX_EVENTS]:
                if not isinstance(ev, dict):
                    continue
                kind = _text(ev.get("type"), 40).lower().replace(" ", "_")
                if not kind:
                    continue
                self.events.append({"t": float(ev.get("t") or time.time()), "type": kind,
                                    "detail": _text(ev.get("detail"), 80)})
                triggers.append(EVENT_ALIASES.get(kind, kind))
        self.updated = time.time()
        self.posts += 1
        return triggers

    def fresh(self, now: float | None = None) -> bool:
        return self.updated > 0 and ((now or time.time()) - self.updated) < FRESH_S

    def landmark(self, lid: str) -> Landmark | None:
        return self.landmarks.get(_text(lid, 40).replace(" ", "_").lower())

    def as_prompt(self) -> str:
        """Compact text for Coach's instructions. Facts the game reported, nothing inferred."""
        if not self.fresh():
            return ""
        parts = [f"GAME STATE (from the game itself, {time.time() - self.updated:.0f}s old"
                 + (f", {self.game}" if self.game else "") + "):"]
        if self.player:
            parts.append("player: " + ", ".join(f"{k}={v}" for k, v in self.player.items()))
        if self.objective:
            parts.append("objective: " + self.objective)
        if self.landmarks:
            lm = []
            for l in list(self.landmarks.values())[:12]:
                if l.visible and l.screen:
                    lm.append(f"{l.id} ({l.label}) on screen at x={l.screen[0]:.2f} y={l.screen[1]:.2f}")
                else:
                    lm.append(f"{l.id} ({l.label}) off screen" + (f", {l.dir}" if l.dir else ""))
            parts.append("landmarks: " + "; ".join(lm))
        if self.events:
            recent = list(self.events)[-6:]
            parts.append("recent events: " + ", ".join(e["type"] + (f" ({e['detail']})" if e["detail"] else "") for e in recent))
        parts.append("When you point or draw a route, pass the landmark id so the game can draw it in the world.")
        return "\n".join(parts)

    def snapshot(self) -> dict:
        return {"game": self.game, "player": dict(self.player), "objective": self.objective,
                "landmarks": {k: {"id": v.id, "label": v.label, "pos": v.pos, "visible": v.visible,
                                  "screen": v.screen, "dir": v.dir} for k, v in self.landmarks.items()},
                "events": list(self.events), "updated": self.updated, "posts": self.posts, "fresh": self.fresh()}
