"""Safety incidents: what Coach saw that a human should look at.

Coach watches the player's screen and hears the player's own mic, nothing else. So it can
notice cheating or a hack on screen, a game-breaking bug, bullying or harassment in on-screen
chat, and an adult trying to get personal contact with a child (in a game marked for kids).
It cannot hear other players unless the game audio is shared.

Every report is a record with the evidence frame, kept for a human to review. Coach never acts
against anyone on its own: no bans, no mutes, no messages to other players. A report goes to
the studio or admin (the incidents page and an optional webhook) and that is all.
"""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

CATEGORIES = ("cheating", "hack", "bug", "bullying", "adult_contact", "other")
SEVERITIES = ("low", "medium", "high")
STATUSES = ("open", "reviewing", "confirmed", "dismissed")
MAX_TEXT = 500


def _clip(text, limit: int = MAX_TEXT) -> str:
    return " ".join(str(text or "").split())[:limit]


@dataclass
class Incident:
    id: str
    ts: float
    category: str
    severity: str
    summary: str          # what Coach saw, in its words
    who: str              # on-screen name or description of who was involved, if any
    game: str
    mode: str             # live, match or teach
    live_id: str
    frame: str            # evidence jpeg file name, or ""
    audience: str         # the playbook audience at the time (kids, teens, adults or "")
    status: str = "open"
    note: str = ""
    alerted: bool = False
    extra: dict = field(default_factory=dict)


class IncidentStore:
    """Append-only JSONL plus evidence frames, with status updates written as new lines."""

    def __init__(self, path: str | os.PathLike, frames_dir: str | os.PathLike | None = None):
        self.path = Path(path)
        self.frames_dir = Path(frames_dir) if frames_dir else self.path.parent / "frames"
        self._items: dict[str, Incident] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("op") == "status":
                inc = self._items.get(obj.get("id", ""))
                if inc:
                    inc.status = obj.get("status", inc.status); inc.note = obj.get("note", inc.note)
                continue
            try:
                inc = Incident(**{k: v for k, v in obj.items() if k in Incident.__dataclass_fields__})
            except TypeError:
                continue
            self._items[inc.id] = inc

    def _append(self, obj: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def add(self, category: str, severity: str, summary: str, *, who: str = "", game: str = "",
            mode: str = "live", live_id: str = "", audience: str = "", frame_jpeg: bytes | None = None,
            extra: dict | None = None) -> Incident:
        if category not in CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(CATEGORIES)}")
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
        summary = _clip(summary)
        if not summary:
            raise ValueError("say what you saw")
        iid = secrets.token_hex(6)
        frame = ""
        if frame_jpeg and frame_jpeg[:2] == b"\xff\xd8":
            self.frames_dir.mkdir(parents=True, exist_ok=True)
            frame = f"{iid}.jpg"
            (self.frames_dir / frame).write_bytes(frame_jpeg)
        inc = Incident(id=iid, ts=time.time(), category=category, severity=severity, summary=summary,
                       who=_clip(who, 120), game=_clip(game, 80) or "unknown", mode=mode, live_id=live_id,
                       frame=frame, audience=_clip(audience, 20), extra=extra or {})
        self._items[iid] = inc
        self._append(asdict(inc))
        return inc

    def set_status(self, iid: str, status: str, note: str = "") -> Incident:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        inc = self._items.get(iid)
        if inc is None:
            raise KeyError(iid)
        inc.status, inc.note = status, _clip(note, 300)
        self._append({"op": "status", "id": iid, "status": status, "note": inc.note, "ts": time.time()})
        return inc

    def get(self, iid: str) -> Incident | None:
        return self._items.get(iid)

    def recent(self, limit: int = 50, status: str | None = None, category: str | None = None) -> list[Incident]:
        items = [i for i in self._items.values() if (status is None or i.status == status)
                 and (category is None or i.category == category)]
        items.sort(key=lambda i: i.ts, reverse=True)
        return items[:limit]

    def stats(self) -> dict:
        out = {"total": len(self._items), "open": 0, "by_category": {c: 0 for c in CATEGORIES}}
        for i in self._items.values():
            out["open"] += i.status == "open"
            out["by_category"][i.category] = out["by_category"].get(i.category, 0) + 1
        return out

    def mark_alerted(self, iid: str) -> None:
        inc = self._items.get(iid)
        if inc:
            inc.alerted = True


def send_alert(inc: Incident, webhook: str | None = None, timeout: float = 5.0) -> bool:
    """POST the incident (without the frame bytes) to COACH_ALERT_WEBHOOK, if set.
    A Slack or Discord incoming webhook works: both accept a JSON body with a text field.
    Returns True when the webhook answered 2xx. Never raises; alerts must not break a turn."""
    url = webhook if webhook is not None else os.environ.get("COACH_ALERT_WEBHOOK", "")
    if not url:
        return False
    text = (f"Coach safety report [{inc.severity} {inc.category}] in {inc.game}: {inc.summary}"
            + (f" (who: {inc.who})" if inc.who else "") + f" id={inc.id}")
    body = {"text": text, "content": text, "incident": {k: v for k, v in asdict(inc).items() if k != "extra"}}
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "coach-sidekick"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False
