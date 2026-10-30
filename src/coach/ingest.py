"""Gate 1: video ingest.

probe() reads basic facts about a gameplay video with ffprobe.
plan_timestamps() decides which moments to sample (pure, no I/O).
sample_frames() extracts those moments as JPEG frames with ffmpeg.

ffmpeg and ffprobe must be on PATH, or set FFMPEG_BIN / FFPROBE_BIN.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm"}
MAX_DURATION_S = 3 * 60 * 60  # 3 hours
DEFAULT_EVERY_S = 2.0
DEFAULT_MAX_FRAMES = 120
DEFAULT_WIDTH = 768


class IngestError(RuntimeError):
    """Raised for any problem reading or sampling a video."""


@dataclass(frozen=True)
class VideoInfo:
    path: str
    duration_s: float
    fps: float
    width: int
    height: int
    has_audio: bool


@dataclass(frozen=True)
class Frame:
    index: int
    t: float
    path: str


def _tool(name: str, env_var: str) -> str:
    found = os.environ.get(env_var) or shutil.which(name)
    if not found:
        raise IngestError(f"{name} not found; install ffmpeg or set {env_var}")
    return found


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise IngestError(f"{Path(cmd[0]).name} timed out") from exc


def _parse_rate(rate: str | None) -> float:
    if not rate or rate in {"0/0", "0"}:
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    return float(rate)


def _check_path(path: str | os.PathLike) -> Path:
    p = Path(path)
    if not p.is_file():
        raise IngestError(f"file not found: {p}")
    if p.suffix.lower() not in VIDEO_SUFFIXES:
        raise IngestError(
            f"unsupported file type {p.suffix or '(none)'}; use one of {sorted(VIDEO_SUFFIXES)}"
        )
    return p


def probe(path: str | os.PathLike) -> VideoInfo:
    p = _check_path(path)
    proc = _run([
        _tool("ffprobe", "FFPROBE_BIN"),
        "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(p),
    ])
    if proc.returncode != 0:
        raise IngestError(f"not a readable video: {p.name}")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise IngestError("ffprobe returned invalid JSON") from exc

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise IngestError(f"no video stream in {p.name}")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise IngestError(f"could not read duration of {p.name}")
    if duration > MAX_DURATION_S:
        raise IngestError(f"video is longer than {MAX_DURATION_S // 3600} hours")

    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    return VideoInfo(
        path=str(p),
        duration_s=round(duration, 3),
        fps=round(fps, 3),
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        has_audio=has_audio,
    )


def plan_timestamps(
    duration_s: float,
    every_s: float = DEFAULT_EVERY_S,
    max_frames: int = DEFAULT_MAX_FRAMES,
    start_s: float = 0.0,
    end_s: float | None = None,
) -> list[float]:
    """Timestamps to sample, one every `every_s` seconds inside [start_s, end_s).

    If that gives more than `max_frames`, the frames are spread evenly across
    the window instead, so long videos are still covered end to end.
    """
    if duration_s <= 0:
        raise IngestError("duration must be positive")
    if every_s <= 0:
        raise IngestError("every_s must be positive")
    if max_frames < 1:
        raise IngestError("max_frames must be at least 1")
    end = duration_s if end_s is None else min(end_s, duration_s)
    start = max(0.0, start_s)
    if start >= end:
        raise IngestError("start must be before end")

    span = end - start
    count = int(span // every_s) + (0 if span % every_s == 0 else 1)
    count = max(1, count)
    if count <= max_frames:
        times = [start + i * every_s for i in range(count)]
    else:
        step = span / max_frames
        times = [start + i * step for i in range(max_frames)]
    return [round(t, 3) for t in times]


def sample_frames(
    path: str | os.PathLike,
    out_dir: str | os.PathLike,
    every_s: float = DEFAULT_EVERY_S,
    max_frames: int = DEFAULT_MAX_FRAMES,
    width: int = DEFAULT_WIDTH,
    start_s: float = 0.0,
    end_s: float | None = None,
) -> tuple[VideoInfo, list[Frame]]:
    """Extract frames as JPEGs into out_dir and write manifest.json there."""
    if width < 16:
        raise IngestError("width must be at least 16")
    info = probe(path)
    times = plan_timestamps(info.duration_s, every_s, max_frames, start_s, end_s)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ffmpeg = _tool("ffmpeg", "FFMPEG_BIN")

    frames: list[Frame] = []
    for i, t in enumerate(times):
        target = out / f"frame_{i:05d}.jpg"
        proc = _run([
            ffmpeg, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", info.path,
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(target),
        ])
        if proc.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
            raise IngestError(f"could not extract frame at {t:.3f}s")
        frames.append(Frame(index=i, t=t, path=str(target)))

    manifest = {"video": asdict(info), "every_s": every_s, "frames": [asdict(f) for f in frames]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return info, frames
