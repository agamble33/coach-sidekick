"""Gate 4b: the tools Coach can call. Each tool is a plain function with a JSON
schema; the agent loop dispatches by name. Tools never raise to the model: they
return a string result or an error string, so one bad call can't kill the match.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .clips import cut_clip, detect_audio_events, detect_scene_events
from .ingest import IngestError, VideoInfo, probe, sample_frames
from .memory import MatchMemory
from .meta_api import MetaAPIError, MetaClient
from .moments import MomentError, pick_clips
from .voice import speak

VISION_MODEL = "muse-spark-1.3"


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
    _info: VideoInfo | None = None

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
    """Grab the frame at time t and ask the vision model what is happening."""
    info = s.info()
    t = _num(args, "t", lo=0, hi=info.duration_s)
    question = str(args.get("question") or "What is happening in this gameplay frame? Be specific and brief.")
    with tempfile.TemporaryDirectory() as td:
        _, frames = sample_frames(s.video, td, every_s=1, max_frames=1, width=768, start_s=t, end_s=t + 0.5)
        data = Path(frames[0].path).read_bytes()
    if s.client is None:
        return f"(no model client) frame at {t:.1f}s captured, {len(data)} bytes"
    payload = {
        "model": VISION_MODEL,
        "instructions": "You are Coach's eyes. Describe the gameplay frame in one or two plain sentences: "
                        "what is on screen, who has the advantage, anything the player should react to. "
                        "Plain text only, no markdown, no em dashes.",
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": question},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(data).decode()},
        ]}],
        "reasoning": {"effort": "low"}, "stream": False,
    }
    resp = s.client.post_json("/responses", payload)
    texts = [c.get("text", "") for item in resp.get("output", []) if item.get("type") == "message"
             for c in item.get("content", []) if c.get("type") == "output_text"]
    return " ".join(texts).strip() or "(vision model returned no text)"


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
    return json.dumps({"file": str(out), "seconds": round(end - start, 2)})


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
    backend = speak(text) if s.speak_out_loud else "muted"
    return f"said ({backend}): {text}"


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("video_info", "Length, frame rate and size of the loaded match video.",
         {"type": "object", "properties": {}, "additionalProperties": False}, t_video_info),
    Tool("look", "Look at the match video at time t (seconds) and describe what is happening on screen.",
         {"type": "object", "properties": {"t": {"type": "number", "description": "seconds into the video"},
                                           "question": {"type": "string", "description": "what to look for"}},
          "required": ["t"], "additionalProperties": False}, t_look),
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
