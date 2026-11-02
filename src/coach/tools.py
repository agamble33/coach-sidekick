"""Gate 4b: the tools Coach can call. Each tool is a plain function with a JSON
schema; the agent loop dispatches by name. Tools never raise to the model: they
return a string result or an error string, so one bad call can't kill the match.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .clips import cut_clip, detect_audio_events, detect_scene_events
from .ingest import IngestError, VideoInfo, probe, sample_frames
from .annotations import AnnotationStore
from .incidents import CATEGORIES, SEVERITIES, IncidentStore, send_alert
from .memory import MatchMemory
from .playbook import Playbook
from .meta_api import MetaAPIError, MetaClient
from .moments import MomentError, pick_clips
from .voice import speak
from .reactions.engine import ReactionEngine

VISION_MODEL = os.environ.get("META_MODEL", "muse-spark-1.3-contributor")
LIVE_MAX_FRAME_BYTES = 2 * 1024 * 1024
LIVE_STALE_S = 30.0


class LiveFeed:
    """Latest screen frames pushed by the player's browser (live mode)."""

    def __init__(self, keep: int = 3):
        self._frames: deque[tuple[float, bytes]] = deque(maxlen=keep)
        self.started = time.time()

    def push(self, jpeg: bytes, ts: float | None = None) -> None:
        if not jpeg or jpeg[:2] != b"\xff\xd8":
            raise ValueError("frame must be a JPEG")
        if len(jpeg) > LIVE_MAX_FRAME_BYTES:
            raise ValueError("frame larger than 2 MB")
        self._frames.append((time.time() if ts is None else ts, jpeg))

    def latest(self) -> tuple[float, bytes] | None:
        return self._frames[-1] if self._frames else None

    def age_s(self) -> float | None:
        f = self.latest()
        return None if f is None else round(time.time() - f[0], 1)

    def __len__(self) -> int:
        return len(self._frames)


@dataclass
class Overlay:
    """What the overlay page draws over the game: Coach's pointers, the task list, the last callout.

    Highlights are fractions of the shared frame (0..1) so the overlay page can be any size with
    the same aspect ratio as the capture. Each highlight expires on its own."""
    highlights: list[dict] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)
    callout: str = ""
    callout_at: float = 0.0
    reaction: dict | None = None      # last meme reaction card (image, sound, line, ts); the page dedupes on ts
    guide: bool = False               # Guide me: the player allowed Coach to point and draw routes
    pointers: list[dict] = field(default_factory=list)   # arrows: where to go / what to look at
    route: list[dict] = field(default_factory=list)      # numbered waypoints, in order
    updated: float = 0.0
    turn_started: float = 0.0
    hidden: bool = False
    # where the panels sit, so they stay off the game's own minimap and chat:
    # tasks and badge: tl, tr, bl, br (badge also off); callout: top or bottom
    layout: dict = field(default_factory=lambda: {"tasks": "bl", "callout": "top", "badge": "tl"})

    LAYOUT_CHOICES = {"tasks": ("tl", "tr", "bl", "br"), "callout": ("top", "bottom"),
                      "badge": ("tl", "tr", "bl", "br", "off")}

    def set_layout(self, layout: dict) -> dict:
        for k, v in (layout or {}).items():
            if k not in self.LAYOUT_CHOICES or v not in self.LAYOUT_CHOICES[k]:
                raise ValueError(f"bad layout {k}={v!r}")
            self.layout[k] = v
        self.touch()
        return dict(self.layout)

    MAX_HIGHLIGHTS = 5
    MAX_TASKS = 6
    MAX_POINTERS = 3
    MAX_ROUTE = 6
    DIRECTIONS = ("here", "left", "right", "up", "down", "behind")

    def touch(self) -> None:
        self.updated = time.time()

    def add_highlight(self, x: float, y: float, w: float, h: float, label: str, seconds: float) -> dict:
        now = time.time()
        self.highlights = [hl for hl in self.highlights if hl["until"] > now]
        hl = {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4),
              "label": label, "seconds": seconds, "created": now, "until": now + seconds}
        self.highlights.append(hl)
        self.highlights = self.highlights[-self.MAX_HIGHLIGHTS:]
        self.touch()
        return hl

    def add_pointer(self, x: float, y: float, label: str, direction: str, seconds: float) -> dict:
        if direction not in self.DIRECTIONS:
            raise ValueError(f"direction must be one of {', '.join(self.DIRECTIONS)}")
        now = time.time()
        self.pointers = [p for p in self.pointers if p["until"] > now]
        p = {"x": round(x, 4), "y": round(y, 4), "label": label, "direction": direction,
             "seconds": seconds, "created": now, "until": now + seconds}
        self.pointers.append(p)
        self.pointers = self.pointers[-self.MAX_POINTERS:]
        self.touch()
        return p

    def set_route(self, steps: list[dict], seconds: float) -> list[dict]:
        now = time.time()
        self.route = [{"n": i + 1, "x": round(float(st["x"]), 4), "y": round(float(st["y"]), 4),
                       "label": st.get("label", ""), "until": now + seconds, "created": now, "seconds": seconds}
                      for i, st in enumerate(steps[: self.MAX_ROUTE])]
        self.touch()
        return self.route

    def clear_guidance(self) -> None:
        self.pointers, self.route = [], []
        self.touch()

    def start_turn(self) -> None:
        self.turn_started = time.time()

    def finish_turn(self) -> None:
        """Re-base highlights drawn during this turn so their time starts now, when the player
        can actually see them, not when Coach drew them mid-turn (the rest of the turn, more
        tool calls and the reply, took longer than the box lived)."""
        now = time.time()
        for hl in self.highlights + self.pointers + self.route:
            if hl.get("created", 0) >= self.turn_started > 0:
                hl["until"] = now + hl.get("seconds", 8)
        self.turn_started = 0.0
        self.touch()

    def set_tasks(self, tasks: list[str]) -> None:
        self.tasks = [{"text": t, "done": False} for t in tasks[: self.MAX_TASKS]]
        self.touch()

    def task_done(self, index: int) -> dict:
        if not 1 <= index <= len(self.tasks):
            raise ValueError(f"no task {index}; there are {len(self.tasks)}")
        self.tasks[index - 1]["done"] = True
        self.touch()
        return self.tasks[index - 1]

    def say(self, text: str) -> None:
        self.callout, self.callout_at = text, time.time()
        self.touch()

    def react(self, payload: dict) -> None:
        self.reaction = payload
        self.touch()

    def snapshot(self) -> dict:
        now = time.time()
        return {"highlights": [hl for hl in self.highlights if hl["until"] > now],
                "tasks": list(self.tasks), "callout": self.callout, "callout_at": self.callout_at,
                "hidden": self.hidden, "layout": dict(self.layout), "reaction": self.reaction,
                "guide": self.guide,
                "pointers": [p for p in self.pointers if p["until"] > now] if self.guide else [],
                "route": [w for w in self.route if w["until"] > now] if self.guide else [],
                "updated": self.updated, "now": now}


@dataclass
class Session:
    """What Coach is working with right now."""
    work_dir: Path
    memory: MatchMemory
    match: str = "current match"
    video: str | None = None
    client: MetaClient | None = None
    speak_out_loud: bool = False
    spoken: list[str] = field(default_factory=list)
    live: LiveFeed | None = None
    playbook: "Playbook | None" = None
    teach: bool = False
    annotations: AnnotationStore | None = None
    last_observation: str = ""
    last_record_id: str = ""
    overlay: Overlay = field(default_factory=Overlay)
    reactions: ReactionEngine = field(default_factory=lambda: ReactionEngine(spice="mild", pack="3d"))
    incidents: IncidentStore | None = None
    live_id: str = ""
    _info: VideoInfo | None = None

    @property
    def game(self) -> str:
        return self.playbook.game if self.playbook else self.match

    def record(self, kind: str, text: str, player_text: str = "") -> str:
        """Write an annotation record if a store is attached; returns its id or ''."""
        if self.annotations is None or not text.strip():
            return ""
        frame = None
        if self.live is not None and self.live.latest() is not None:
            frame = self.live.latest()[1]
        mode = "teach" if self.teach else ("live" if self.live is not None else "match")
        try:
            r = self.annotations.add(self.game, kind, text, player_text=player_text, observation=self.last_observation,
                                     playbook=self.playbook.game if self.playbook else "", mode=mode, frame_jpeg=frame)
        except ValueError:
            return ""
        self.last_record_id = r.id
        return r.id

    def info(self) -> VideoInfo:
        if not self.video:
            raise IngestError("no video loaded for this session")
        if self._info is None:
            self._info = probe(self.video)
        return self._info


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[[Session, dict], str]

    def spec(self) -> dict:
        return {"type": "function", "name": self.name, "description": self.description,
                "parameters": self.parameters}


def _num(args: dict, key: str, default: float | None = None, lo: float | None = None, hi: float | None = None) -> float:
    if key not in args or args[key] is None:
        if default is None:
            raise ValueError(f"missing argument {key!r}")
        return default
    try:
        v = float(args[key])
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number")
    if lo is not None and v < lo or hi is not None and v > hi:
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return v


# ---- tool implementations ----

def t_video_info(s: Session, args: dict) -> str:
    i = s.info()
    return json.dumps({"duration_s": i.duration_s, "fps": i.fps, "width": i.width,
                       "height": i.height, "has_audio": i.has_audio})


def t_look(s: Session, args: dict) -> str:
    """Grab the frame at time t from the loaded video and ask the vision model what is happening."""
    info = s.info()
    t = _num(args, "t", lo=0, hi=info.duration_s)
    question = str(args.get("question") or "What is happening in this gameplay frame? Be specific and brief.")
    with tempfile.TemporaryDirectory() as td:
        _, frames = sample_frames(s.video, td, every_s=1, max_frames=1, width=768, start_s=t, end_s=t + 0.5)
        data = Path(frames[0].path).read_bytes()
    if s.client is None:
        return f"(no model client) frame at {t:.1f}s captured, {len(data)} bytes"
    s.last_observation = _describe(s, data, question)
    return s.last_observation


def _describe(s: Session, jpeg: bytes, question: str) -> str:
    payload = {
        "model": VISION_MODEL,
        "instructions": "You are Coach's eyes. Describe the gameplay frame in one or two plain sentences: "
                        "what is on screen, who has the advantage, anything the player should react to. "
                        "Plain text only, no markdown, no em dashes.",
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": question},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()},
        ]}],
        "reasoning": {"effort": "low"}, "stream": False,
    }
    resp = s.client.post_json("/responses", payload)
    texts = [c.get("text", "") for item in resp.get("output", []) if item.get("type") == "message"
             for c in item.get("content", []) if c.get("type") == "output_text"]
    return " ".join(texts).strip() or "(vision model returned no text)"


def t_look_now(s: Session, args: dict) -> str:
    """Look at the player's live screen (latest shared frame)."""
    if s.live is None or s.live.latest() is None:
        raise ValueError("live mode is off; ask the player to share their screen")
    ts, jpeg = s.live.latest()
    age = s.live.age_s() or 0.0
    if age > LIVE_STALE_S:
        raise ValueError(f"last frame is {age:.0f}s old; the screen share may have stopped")
    question = str(args.get("question") or "What is happening on the player's screen right now? Be specific and brief.")
    if s.client is None:
        return f"(no model client) live frame {age:.1f}s old, {len(jpeg)} bytes"
    s.last_observation = _describe(s, jpeg, question)
    return f"[{age:.0f}s ago] " + s.last_observation


def t_find_moments(s: Session, args: dict) -> str:
    info = s.info()
    top = int(_num(args, "top", 5, 1, 20))
    events = detect_scene_events(info) + detect_audio_events(info)
    wins = pick_clips(events, info.duration_s, top=top)
    return json.dumps({"events": len(events), "moments": [
        {"start": w.start, "peak": w.peak, "end": w.end, "score": w.score, "signals": list(w.kinds)} for w in wins]})


def t_cut_clip(s: Session, args: dict) -> str:
    info = s.info()
    start = _num(args, "start", lo=0, hi=info.duration_s)
    end = _num(args, "end", lo=0, hi=info.duration_s)
    if end <= start:
        raise ValueError("end must be after start")
    if end - start > 60:
        raise ValueError("clips are capped at 60 seconds")
    label = "".join(c for c in str(args.get("label", "clip")) if c.isalnum() or c in "-_")[:40] or "clip"
    out = s.work_dir / "clips" / f"{label}_{start:06.1f}-{end:06.1f}.mp4"
    cut_clip(info, start, end, out)
    return json.dumps({"clip": out.name, "seconds": round(end - start, 2)})


def t_remember(s: Session, args: dict) -> str:
    note = s.memory.remember(s.match, str(args.get("note", "")))
    return f"saved: {note.text}"


def t_recall(s: Session, args: dict) -> str:
    scope = args.get("scope", "all")
    match = s.match if scope == "this_match" else None
    notes = s.memory.recall(match, limit=int(_num(args, "limit", 10, 1, 50)))
    if not notes:
        return "no notes yet"
    return "\n".join(f"[{n.match}] {n.text}" for n in notes)


def t_callout(s: Session, args: dict) -> str:
    text = " ".join(str(args.get("text", "")).split())[:300]
    if not text:
        raise ValueError("nothing to say")
    s.spoken.append(text)
    s.overlay.say(text)
    s.record("callout", text)
    backend = speak(text) if s.speak_out_loud else "muted"
    return f"said ({backend}): {text}"


def t_react(s: Session, args: dict) -> str:
    """Flash a meme reaction card + sound sting on the overlay. Cooldowns and the spice setting
    live in the engine, so a suppressed reaction is a normal result, not an error."""
    trigger = str(args.get("trigger", "")).strip()
    context = " ".join(str(args.get("context", "")).split())[:200]
    payload = s.reactions.fire(trigger, context)
    if payload is None:
        _, why = s.reactions.can_fire(trigger)
        return f"no reaction ({why})"
    s.overlay.react(payload)
    s.record("react", f"{trigger}: {payload['line']}" + (f" ({context})" if context else ""))
    return f"reacted {trigger}: {payload['line']}"


def t_report_concern(s: Session, args: dict) -> str:
    """File a safety report for a human to review. Coach never acts on it itself."""
    category = str(args.get("category", "")).strip().lower()
    severity = str(args.get("severity", "medium")).strip().lower()
    summary = str(args.get("what_you_saw", ""))
    who = str(args.get("who", ""))
    if s.incidents is None:
        return "error: reports are not enabled on this server"
    frame = None
    if s.live is not None and s.live.latest() is not None:
        frame = s.live.latest()[1]
    mode = "teach" if s.teach else ("live" if s.live is not None else "match")
    audience = s.playbook.audience if s.playbook else ""
    inc = s.incidents.add(category, severity, summary, who=who, game=s.game, mode=mode, live_id=s.live_id,
                          audience=audience, frame_jpeg=frame)
    if send_alert(inc):
        s.incidents.mark_alerted(inc.id)
    s.record("observation", f"[safety report {inc.category}/{inc.severity}] {inc.summary}")
    return f"reported {inc.category} ({inc.severity}) as {inc.id}; a person will review it. Do not confront anyone."


def t_highlight(s: Session, args: dict) -> str:
    x = _num(args, "x", lo=0, hi=1); y = _num(args, "y", lo=0, hi=1)
    w = _num(args, "w", 0.12, 0.01, 1); h = _num(args, "h", 0.12, 0.01, 1)
    if x + w > 1.0001 or y + h > 1.0001:
        raise ValueError("the box runs off the screen; x+w and y+h must be at most 1")
    label = " ".join(str(args.get("label", "")).split())[:40]
    # floor of 8 s: Coach once asked for 5 s and the box expired before its own turn finished
    seconds = max(8.0, _num(args, "seconds", 10, 1, 30))
    hl = s.overlay.add_highlight(x, y, w, h, label, seconds)
    where = f"({hl['x']:.2f}, {hl['y']:.2f})"
    return f"highlighted {label or 'spot'} at {where} for {seconds:g}s"


GUIDE_OFF = "guide mode is off: the player has not turned on Guide me, so do not point; use callout instead"


def t_point(s: Session, args: dict) -> str:
    """Draw an arrow at a screen spot (or at the screen edge toward something off screen)."""
    if not s.overlay.guide:
        return GUIDE_OFF
    x = _num(args, "x", lo=0, hi=1); y = _num(args, "y", lo=0, hi=1)
    label = " ".join(str(args.get("label", "")).split())[:40]
    direction = str(args.get("direction", "here")).strip().lower() or "here"
    seconds = max(8.0, _num(args, "seconds", 12, 1, 60))
    p = s.overlay.add_pointer(x, y, label, direction, seconds)
    where = "here" if direction == "here" else f"off screen, {direction}"
    s.record("callout", f"[point] {label or 'go'} {where}")
    return f"pointed {label or 'there'} ({where}) at ({p['x']:.2f}, {p['y']:.2f}) for {seconds:g}s"


def t_route(s: Session, args: dict) -> str:
    """Draw numbered waypoints the player should follow, in order."""
    if not s.overlay.guide:
        return GUIDE_OFF
    raw = args.get("steps")
    if not isinstance(raw, list) or not raw:
        raise ValueError("steps must be a list of {x, y, label}")
    steps = []
    for st in raw[: Overlay.MAX_ROUTE]:
        if not isinstance(st, dict):
            raise ValueError("each step must be an object with x, y, label")
        steps.append({"x": _num(st, "x", lo=0, hi=1), "y": _num(st, "y", lo=0, hi=1),
                      "label": " ".join(str(st.get("label", "")).split())[:30]})
    seconds = max(10.0, _num(args, "seconds", 20, 1, 90))
    route = s.overlay.set_route(steps, seconds)
    s.record("callout", "[route] " + " > ".join(w["label"] or f"step {w['n']}" for w in route))
    return f"route with {len(route)} steps for {seconds:g}s: " + " > ".join(w["label"] or str(w["n"]) for w in route)


def t_set_tasks(s: Session, args: dict) -> str:
    raw = args.get("tasks")
    if not isinstance(raw, list):
        raise ValueError("tasks must be a list of short strings")
    tasks = [" ".join(str(t).split())[:80] for t in raw]
    tasks = [t for t in tasks if t]
    if not tasks:
        raise ValueError("give at least one task")
    s.overlay.set_tasks(tasks)
    return "tasks: " + "; ".join(f"{i}. {t}" for i, t in enumerate(tasks[:Overlay.MAX_TASKS], 1))


def t_task_done(s: Session, args: dict) -> str:
    idx = int(_num(args, "index", lo=1, hi=Overlay.MAX_TASKS))
    t = s.overlay.task_done(idx)
    return f"done: {t['text']}"


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("video_info", "Length, frame rate and size of the loaded match video.",
         {"type": "object", "properties": {}, "additionalProperties": False}, t_video_info),
    Tool("look", "Look at the match video at time t (seconds) and describe what is happening on screen.",
         {"type": "object", "properties": {"t": {"type": "number", "description": "seconds into the video"},
                                           "question": {"type": "string", "description": "what to look for"}},
          "required": ["t"], "additionalProperties": False}, t_look),
    Tool("look_now", "Look at the player's live screen right now (live mode). Use this for anything happening in the current game.",
         {"type": "object", "properties": {"question": {"type": "string", "description": "what to look for"}},
          "additionalProperties": False}, t_look_now),
    Tool("find_moments", "Find the biggest moments in the match (scene cuts and loud audio), ranked.",
         {"type": "object", "properties": {"top": {"type": "integer", "minimum": 1, "maximum": 20}},
          "additionalProperties": False}, t_find_moments),
    Tool("cut_clip", "Save a highlight clip from start to end seconds (max 60 s) as an mp4.",
         {"type": "object", "properties": {"start": {"type": "number"}, "end": {"type": "number"},
                                           "label": {"type": "string"}},
          "required": ["start", "end"], "additionalProperties": False}, t_cut_clip),
    Tool("remember", "Save a short note about this match so you remember it next time.",
         {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"],
          "additionalProperties": False}, t_remember),
    Tool("recall", "Read your notes from earlier matches (scope 'all') or just this one ('this_match').",
         {"type": "object", "properties": {"scope": {"type": "string", "enum": ["all", "this_match"]},
                                           "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
          "additionalProperties": False}, t_recall),
    Tool("callout", "Say something to the player out loud right now, like a teammate on voice chat.",
         {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
          "additionalProperties": False}, t_callout),
    Tool("report_concern", "File a safety report for a human reviewer when you see cheating or a hack, a game-breaking "
         "bug, bullying or harassment in chat, or an adult trying to get personal contact with a child. Say exactly what "
         "you saw. Coach never acts on it; a person does.",
         {"type": "object", "properties": {"category": {"type": "string", "enum": list(CATEGORIES)},
                                           "severity": {"type": "string", "enum": list(SEVERITIES)},
                                           "what_you_saw": {"type": "string", "description": "the exact words or behaviour on screen"},
                                           "who": {"type": "string", "description": "on-screen name or description, if any"}},
          "required": ["category", "what_you_saw"], "additionalProperties": False}, t_report_concern),
    Tool("highlight", "Draw a box on the player's screen overlay to point at something (an enemy, an exit, a pickup). "
         "x, y, w, h are fractions of the screen from the top-left (0 to 1). Pair it with a callout.",
         {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                           "w": {"type": "number"}, "h": {"type": "number"},
                                           "label": {"type": "string", "description": "two or three words"},
                                           "seconds": {"type": "number", "description": "how long to show, 8 to 30 (default 10)"}},
          "required": ["x", "y"], "additionalProperties": False}, t_highlight),
    Tool("react", ReactionEngine(validate_assets=False).tool_schema()["function"]["description"],
         ReactionEngine(validate_assets=False).tool_schema()["function"]["parameters"], t_react),
    Tool("point", "Guide me only. Draw an arrow on the player's screen at where to go or what to look at. x, y are fractions of "
         "the screen from the top-left (0 to 1). If the target is off screen, give the direction and an x, y near that edge.",
         {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                           "label": {"type": "string", "description": "two or three words, e.g. 'Exit' or 'Health'"},
                                           "direction": {"type": "string", "enum": list(Overlay.DIRECTIONS),
                                                         "description": "here if the spot is on screen, else which way to turn"},
                                           "seconds": {"type": "number", "description": "how long to show, 8 to 60 (default 12)"}},
          "required": ["x", "y"], "additionalProperties": False}, t_point),
    Tool("route", "Guide me only. Draw numbered waypoints the player should follow in order (2 to 6), each with x, y "
         "fractions of the screen and a short label. Use for 'how do I get to X' with several steps.",
         {"type": "object", "properties": {"steps": {"type": "array", "minItems": 1, "maxItems": 6, "items": {
             "type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "label": {"type": "string"}},
             "required": ["x", "y"], "additionalProperties": False}},
                                           "seconds": {"type": "number", "description": "10 to 90 (default 20)"}},
          "required": ["steps"], "additionalProperties": False}, t_route),
    Tool("set_tasks", "Replace the player's on-screen task list with the next things to do, in order (1 to 6 short lines).",
         {"type": "object", "properties": {"tasks": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6}},
          "required": ["tasks"], "additionalProperties": False}, t_set_tasks),
    Tool("task_done", "Tick off task number index on the player's task list (1 is the first).",
         {"type": "object", "properties": {"index": {"type": "integer", "minimum": 1, "maximum": 6}},
          "required": ["index"], "additionalProperties": False}, t_task_done),
]}


def tool_specs(names: list[str] | None = None) -> list[dict]:
    return [TOOLS[n].spec() for n in (names or list(TOOLS))]


def run_tool(session: Session, name: str, args: Any) -> str:
    """Dispatch one call. Always returns a string; errors are reported, never raised."""
    tool = TOOLS.get(name)
    if tool is None:
        return f"error: unknown tool {name!r}"
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            return "error: arguments were not valid JSON"
    if not isinstance(args, dict):
        return "error: arguments must be an object"
    try:
        return tool.run(session, args)
    except (ValueError, IngestError, MomentError, MetaAPIError) as exc:
        return f"error: {exc}"
