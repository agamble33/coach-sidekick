"""Gate 8a: gameplay annotation store. Every Coach observation, callout and reply
becomes a record; players label them with one tap; the best examples feed back
into Coach's instructions, and the whole set exports as training data.

Records live in one JSONL file (append-only) plus optional frame JPEGs, all under
the data folder, never in the repo.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_TEXT = 1000
MAX_RECORDS_IN_MEMORY = 20000
LABELS = ("up", "down")


@dataclass
class Record:
    id: str
    ts: float
    game: str                      # playbook game or match name
    kind: str                      # "callout" | "reply" | "observation"
    text: str                      # what Coach said (or saw, for observation)
    player_text: str = ""          # what the player said that led to it
    observation: str = ""          # look/look_now output behind this record
    playbook: str = ""             # playbook game in force, if any
    frame: str = ""                # saved frame filename, if any
    mode: str = "match"            # "match" | "live" | "teach"
    label: str = ""                # "" | "up" | "down"
    correction: str = ""           # player's one-line fix, if any
    extra: dict = field(default_factory=dict)


def _clip(s: str, n: int = MAX_TEXT) -> str:
    return " ".join(str(s or "").split())[:n]


class AnnotationStore:
    def __init__(self, path: str | os.PathLike, frames_dir: str | os.PathLike | None = None):
        self.path = Path(path)
        self.frames_dir = Path(frames_dir) if frames_dir else self.path.parent / "frames"
        self._records: dict[str, Record] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if d.get("op") == "label":                 # label lines patch earlier records
                        r = self._records.get(d.get("id", ""))
                        if r:
                            r.label = d.get("label", r.label)
                            r.correction = d.get("correction", r.correction)
                    else:
                        d.pop("op", None)
                        known = {k: v for k, v in d.items() if k in Record.__dataclass_fields__}
                        r = Record(**known)
                        self._records[r.id] = r
                except (ValueError, TypeError):
                    continue                                    # skip a corrupt line, keep the rest
        if len(self._records) > MAX_RECORDS_IN_MEMORY:
            for k in list(self._records)[:-MAX_RECORDS_IN_MEMORY]:
                del self._records[k]

    def _append(self, obj: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def add(self, game: str, kind: str, text: str, *, player_text: str = "", observation: str = "",
            playbook: str = "", mode: str = "match", frame_jpeg: bytes | None = None, extra: dict | None = None) -> Record:
        if kind not in ("callout", "reply", "observation", "react"):
            raise ValueError("kind must be callout, reply or observation")
        text = _clip(text)
        if not text:
            raise ValueError("text is empty")
        rid = secrets.token_hex(6)
        frame = ""
        if frame_jpeg and frame_jpeg[:2] == b"\xff\xd8":
            self.frames_dir.mkdir(parents=True, exist_ok=True)
            frame = f"{rid}.jpg"
            (self.frames_dir / frame).write_bytes(frame_jpeg)
        r = Record(id=rid, ts=time.time(), game=_clip(game, 80) or "unknown", kind=kind, text=text,
                   player_text=_clip(player_text), observation=_clip(observation), playbook=_clip(playbook, 80),
                   frame=frame, mode=mode, extra=extra or {})
        self._records[rid] = r
        self._append(asdict(r))
        return r

    def label(self, rid: str, label: str, correction: str = "") -> Record:
        r = self._records.get(rid)
        if r is None:
            raise KeyError("record not found")
        if label not in LABELS:
            raise ValueError("label must be up or down")
        r.label = label
        r.correction = _clip(correction, 300)
        self._append({"op": "label", "id": rid, "label": r.label, "correction": r.correction, "ts": time.time()})
        return r

    def get(self, rid: str) -> Record | None:
        return self._records.get(rid)

    def recent(self, limit: int = 50, game: str | None = None) -> list[Record]:
        rs = [r for r in self._records.values() if game is None or r.game == game]
        return rs[-max(1, limit):]

    def stats(self, game: str | None = None) -> dict:
        rs = [r for r in self._records.values() if game is None or r.game == game]
        return {"records": len(rs), "labeled": sum(1 for r in rs if r.label),
                "up": sum(1 for r in rs if r.label == "up"), "down": sum(1 for r in rs if r.label == "down"),
                "corrections": sum(1 for r in rs if r.correction), "frames": sum(1 for r in rs if r.frame)}

    # ---- feedback loop: what Coach learns, as text for its instructions ----

    def learned_prompt(self, game: str, max_examples: int = 6) -> str:
        rs = [r for r in self._records.values() if r.game == game and r.kind in ("callout", "reply")]
        good = [r for r in rs if r.label == "up"][-max_examples:]
        bad = [r for r in rs if r.label == "down"][-max_examples:]
        if not good and not bad:
            return ""
        lines = [f"LEARNED for {game} (from this player's ratings):"]
        for r in good:
            lines.append(f"- Good callout: \"{r.text}\"" + (f" (when: {r.observation[:120]})" if r.observation else ""))
        for r in bad:
            fix = f" Player said: {r.correction}" if r.correction else ""
            lines.append(f"- Avoid: \"{r.text}\".{fix}")
        return "\n".join(lines)

    # ---- export for training ----

    def export_training(self, out_path: str | os.PathLike, game: str | None = None,
                        include_unlabeled: bool = False) -> int:
        """Chat-tuning JSONL: one line per labeled example. Thumbs-up records become
        (instruction, accepted answer); thumbs-down with a correction become
        (instruction, corrected answer). Frames are referenced by filename."""
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with open(out, "w", encoding="utf-8") as f:
            for r in self._records.values():
                if game is not None and r.game != game:
                    continue
                if r.kind == "observation":
                    continue
                if r.label == "up":
                    answer = r.text
                elif r.label == "down" and r.correction:
                    answer = r.correction
                elif include_unlabeled and not r.label:
                    answer = r.text
                else:
                    continue
                user = r.player_text or ("Watch tick: what should the teammate say right now?" if r.kind == "callout" else "")
                ctx = []
                if r.playbook:
                    ctx.append(f"Game: {r.playbook}")
                if r.observation:
                    ctx.append(f"On screen: {r.observation}")
                example = {
                    "messages": [
                        {"role": "system", "content": "You are Coach, an in-game AI teammate. Short, specific, teammate tone."},
                        {"role": "user", "content": ("\n".join(ctx) + "\n\n" if ctx else "") + user},
                        {"role": "assistant", "content": answer},
                    ],
                    "meta": {"id": r.id, "game": r.game, "kind": r.kind, "mode": r.mode, "label": r.label,
                             "frame": r.frame, "ts": r.ts},
                }
                f.write(json.dumps(example, ensure_ascii=False) + "\n")
                n += 1
        return n
