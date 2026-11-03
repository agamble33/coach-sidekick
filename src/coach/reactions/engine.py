"""Coach reaction engine (Gate 6).

Maps agent-detected gameplay moments to a meme card + sound sting + spoken line,
with per-trigger and global cooldowns and a spice level (off / mild / unhinged).

Framework-agnostic: returns plain dicts. Wire `ReactionEngine.fire()` to the
agent's `react` tool and push the payload to the UI over your existing
websocket / SSE channel.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
CONFIG = HERE / "reactions.json"


class ReactionError(ValueError):
    pass


@dataclass
class Reaction:
    trigger: str
    description: str
    min_spice: str
    image: str
    sound: str
    lines: list[str]
    cooldown_s: float
    show_ms: int


@dataclass
class ReactionEngine:
    config_path: Path = CONFIG
    assets_dir: Path = ASSETS
    spice: str = "mild"
    pack: str = "3d"  # original rendered cards (the only pack)
    avatar: str = ""  # who Coach looks like on the overlay badge and reaction card; "" = config default
    clock: Callable[[], float] = time.monotonic
    rng: random.Random = field(default_factory=random.Random)
    validate_assets: bool = True

    def __post_init__(self):
        raw = json.loads(Path(self.config_path).read_text(encoding="utf-8"))
        self.levels: list[str] = raw["spice_levels"]
        d = raw["defaults"]
        self.global_cooldown_s: float = float(d.get("global_cooldown_s", 0))
        self.show_ms: int = int(d.get("show_ms", 2500))
        self.volume: float = float(d.get("volume", 0.8))
        self.reactions: dict[str, Reaction] = {}
        for r in raw["reactions"]:
            rx = Reaction(
                trigger=r["trigger"],
                description=r.get("description", ""),
                min_spice=r.get("min_spice", "mild"),
                image=r["image"],
                sound=r["sound"],
                lines=list(r.get("lines") or [""]),
                cooldown_s=float(r.get("cooldown_s", d.get("cooldown_s", 0))),
                show_ms=int(r.get("show_ms", self.show_ms)),
            )
            if rx.trigger in self.reactions:
                raise ReactionError(f"duplicate trigger: {rx.trigger}")
            if rx.min_spice not in self.levels:
                raise ReactionError(f"{rx.trigger}: unknown min_spice {rx.min_spice!r}")
            self.reactions[rx.trigger] = rx
        if self.spice not in self.levels:
            raise ReactionError(f"unknown spice level {self.spice!r}")
        self.packs: dict[str, str] = raw.get("packs", {"3d": "images"})
        if self.pack not in self.packs:
            raise ReactionError(f"unknown pack {self.pack!r}; use one of {sorted(self.packs)}")
        self.default_pack: str = raw.get("default_pack", "3d")
        self.avatars: dict[str, dict] = raw.get("avatars", {})
        self.avatar = self.avatar or raw.get("default_avatar", next(iter(self.avatars), ""))
        if self.avatars and self.avatar not in self.avatars:
            raise ReactionError(f"unknown avatar {self.avatar!r}; use one of {sorted(self.avatars)}")
        if self.validate_assets:
            self.check_assets()
        self._last_fired: dict[str, float] = {}
        self._last_any: float = float("-inf")

    # ---- config checks ---------------------------------------------------
    def check_assets(self) -> list[str]:
        missing = []
        for rx in self.reactions.values():
            for rel in (rx.image, rx.sound):
                if not (Path(self.assets_dir) / rel).is_file():
                    missing.append(f"{rx.trigger}: {rel}")
        for name, av in self.avatars.items():
            if not (Path(self.assets_dir) / av["image"]).is_file():
                missing.append(f"avatar {name}: {av['image']}")
        if missing:
            raise ReactionError("missing assets:\n  " + "\n  ".join(missing))
        return missing

    # ---- runtime ---------------------------------------------------------
    def set_spice(self, level: str) -> None:
        if level not in self.levels:
            raise ReactionError(f"unknown spice level {level!r}; use one of {self.levels}")
        self.spice = level

    def set_pack(self, pack: str) -> None:
        if pack not in self.packs:
            raise ReactionError(f"unknown pack {pack!r}; use one of {sorted(self.packs)}")
        self.pack = pack

    def set_avatar(self, avatar: str) -> None:
        if avatar not in self.avatars:
            raise ReactionError(f"unknown avatar {avatar!r}; use one of {sorted(self.avatars)}")
        self.avatar = avatar

    def avatar_url(self) -> str:
        av = self.avatars.get(self.avatar)
        return f"/reactions/{av['image']}" if av else ""

    def state(self) -> dict:
        """Player-facing settings snapshot (for the settings panel and the overlay badge)."""
        return {"enabled": self.spice != "off", "spice": self.spice, "pack": self.pack, "avatar": self.avatar,
                "avatar_url": self.avatar_url(), "avatar_label": self.avatars.get(self.avatar, {}).get("label", "Coach"),
                "spice_levels": list(self.levels), "packs": sorted(self.packs),
                "avatars": {k: v["label"] for k, v in self.avatars.items()}, "triggers": sorted(self.reactions)}

    def image_for(self, rx: Reaction) -> str:
        """Image path (relative to assets) for the active pack, falling back to the default pack."""
        fname = Path(rx.image).name
        for pack in (self.pack, self.default_pack):
            rel = f"{self.packs[pack]}/{fname}"
            if (Path(self.assets_dir) / rel).is_file():
                return rel
        return rx.image

    def _spice_ok(self, rx: Reaction) -> bool:
        if self.spice == "off":
            return False
        return self.levels.index(self.spice) >= self.levels.index(rx.min_spice)

    def can_fire(self, trigger: str) -> tuple[bool, str]:
        rx = self.reactions.get(trigger)
        if rx is None:
            return False, f"unknown trigger {trigger!r}"
        if not self._spice_ok(rx):
            return False, f"spice level {self.spice!r} below {rx.min_spice!r}"
        now = self.clock()
        if now - self._last_any < self.global_cooldown_s:
            return False, "global cooldown"
        if now - self._last_fired.get(trigger, float("-inf")) < rx.cooldown_s:
            return False, "trigger cooldown"
        return True, "ok"

    def fire(self, trigger: str, context: Optional[str] = None) -> Optional[dict]:
        """Return a UI payload, or None if suppressed. Never raises on unknown triggers."""
        ok, why = self.can_fire(trigger)
        if not ok:
            return None
        rx = self.reactions[trigger]
        now = self.clock()
        self._last_fired[trigger] = now
        self._last_any = now
        return {
            "type": "reaction",
            "trigger": trigger,
            "image": f"/reactions/{self.image_for(rx)}",
            "pack": self.pack,
            "avatar": self.avatar,
            "avatar_url": self.avatar_url(),
            "avatar_label": self.avatars.get(self.avatar, {}).get("label", "Coach"),
            "sound": f"/reactions/{rx.sound}",
            "line": self.rng.choice(rx.lines),
            "show_ms": rx.show_ms,
            "volume": self.volume,
            "context": context or "",
            "ts": now,
        }

    # ---- agent tool ------------------------------------------------------
    def tool_schema(self) -> dict:
        """OpenAI/Llama-style function schema for the agent's `react` tool."""
        enum = sorted(self.reactions)
        desc = "\n".join(f"- {t}: {self.reactions[t].description}" for t in enum)
        return {
            "type": "function",
            "function": {
                "name": "react",
                "description": (
                    "Show a quick meme reaction card and play a sound when the player has a "
                    "moment worth reacting to. Use sparingly (max one per notable moment). Triggers:\n" + desc
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trigger": {"type": "string", "enum": enum},
                        "context": {"type": "string", "description": "One short sentence on what happened."},
                    },
                    "required": ["trigger"],
                    "additionalProperties": False,
                },
            },
        }

    def handle_tool_call(self, args: dict) -> dict:
        """Call from the agent loop. Returns a tool result the model can read."""
        trig = str(args.get("trigger", ""))
        payload = self.fire(trig, args.get("context"))
        if payload is None:
            _, why = self.can_fire(trig)
            return {"fired": False, "reason": why}
        return {"fired": True, "line": payload["line"], "payload": payload}
