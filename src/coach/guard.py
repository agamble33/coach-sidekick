"""Gate 13a: abuse and token caps. Small on purpose.

- A token bucket per subject (the consent id, else the client address) for turns, frames and
  transcriptions per minute.
- A daily token budget, global and per subject, counted from the usage the Model API returns.
- A kill switch: COACH_DISABLED=1 makes every model-backed endpoint answer 503.

Over a cap the API answers 429 with a plain sentence; nothing is logged about who, only a counter.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


class GuardError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Limits:
    turns_per_min: int = 20
    frames_per_min: int = 60
    transcribes_per_min: int = 20
    daily_tokens: int = 1_000_000          # everyone together
    daily_tokens_per_subject: int = 300_000

    @classmethod
    def from_env(cls, env=None) -> "Limits":
        env = os.environ if env is None else env
        def n(k, d):
            try:
                return int(env.get(k, d))
            except (TypeError, ValueError):
                return d
        return cls(turns_per_min=n("COACH_TURNS_PER_MIN", 20), frames_per_min=n("COACH_FRAMES_PER_MIN", 60),
                   transcribes_per_min=n("COACH_TRANSCRIBES_PER_MIN", 20), daily_tokens=n("COACH_DAILY_TOKENS", 1_000_000),
                   daily_tokens_per_subject=n("COACH_DAILY_TOKENS_PER_SUBJECT", 300_000))


@dataclass
class Guard:
    path: Path                                   # budget file (survives restarts)
    limits: Limits = field(default_factory=Limits)
    disabled: bool = False
    clock: callable = time.time
    _buckets: dict = field(default_factory=dict)   # (kind, subject) -> list of timestamps in the last minute
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _day: str = ""
    _used: int = 0
    _by_subject: dict = field(default_factory=dict)
    _refused: int = 0

    def __post_init__(self):
        self._load()

    # ---- persistence ----
    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock(), tz=timezone.utc).strftime("%Y-%m-%d")

    def _load(self) -> None:
        try:
            raw = json.loads(Path(self.path).read_text(encoding="utf-8"))
            if raw.get("day") == self._today():
                self._day, self._used = raw["day"], int(raw.get("used", 0))
                self._by_subject = {k: int(v) for k, v in raw.get("by_subject", {}).items()}
                self._refused = int(raw.get("refused", 0))
                return
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self._day, self._used, self._by_subject = self._today(), 0, {}

    def _save(self) -> None:
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.path).write_text(json.dumps({"day": self._day, "used": self._used, "by_subject": self._by_subject,
                                                   "refused": self._refused}), encoding="utf-8")
        except OSError:
            pass

    def _roll_day(self) -> None:
        if self._day != self._today():
            self._day, self._used, self._by_subject, self._refused = self._today(), 0, {}, 0

    # ---- checks ----
    def _bucket(self, kind: str, subject: str, per_min: int) -> None:
        now = self.clock()
        key = (kind, subject)
        stamps = [t for t in self._buckets.get(key, []) if now - t < 60]
        if len(stamps) >= per_min:
            self._refused += 1
            raise GuardError(429, f"Coach needs a breather: more than {per_min} {kind} a minute. Try again in a few seconds.")
        stamps.append(now)
        self._buckets[key] = stamps

    def check(self, kind: str, subject: str) -> None:
        """kind: turns | frames | transcribes. Raises GuardError when the caller should stop."""
        with self._lock:
            if self.disabled:
                raise GuardError(503, "Coach is paused by the operator right now.")
            self._roll_day()
            if kind in ("turns", "transcribes"):
                if self._used >= self.limits.daily_tokens:
                    self._refused += 1
                    raise GuardError(429, "Coach has used today's model budget. It resets at midnight UTC.")
                if self._by_subject.get(subject, 0) >= self.limits.daily_tokens_per_subject:
                    self._refused += 1
                    raise GuardError(429, "You've used today's Coach budget for this session. It resets at midnight UTC.")
            per_min = {"turns": self.limits.turns_per_min, "frames": self.limits.frames_per_min,
                       "transcribes": self.limits.transcribes_per_min}[kind]
            self._bucket(kind, subject, per_min)

    def record_usage(self, subject: str, tokens: int) -> None:
        if tokens <= 0:
            return
        with self._lock:
            self._roll_day()
            self._used += tokens
            self._by_subject[subject] = self._by_subject.get(subject, 0) + tokens
            self._save()

    def status(self) -> dict:
        with self._lock:
            self._roll_day()
            return {"disabled": self.disabled, "day": self._day, "tokens_used": self._used,
                    "daily_tokens": self.limits.daily_tokens, "per_subject": self.limits.daily_tokens_per_subject,
                    "subjects": len(self._by_subject), "refused_today": self._refused,
                    "per_minute": {"turns": self.limits.turns_per_min, "frames": self.limits.frames_per_min,
                                   "transcribes": self.limits.transcribes_per_min}}
