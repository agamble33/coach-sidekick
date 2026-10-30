"""Gate 2b: detect signals with ffmpeg and cut highlight clips.

detect_scene_events: frames where the picture changes a lot (scene score).
detect_audio_events: short windows where loudness jumps above the average.
cut_clip / cut_highlights: write clips as mp4 with ffmpeg.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
from dataclasses import asdict
from pathlib import Path

from .ingest import IngestError, VideoInfo, _run, _tool, probe
from .moments import ClipWindow, Event, pick_clips

_SCENE_RE = re.compile(r"pts_time:(?P<t>[0-9.]+).*?scene_score=(?P<s>[0-9.]+)", re.S)
_RMS_RE = re.compile(r"pts_time:(?P<t>[0-9.]+)|lavfi\.astats\.Overall\.RMS_level=(?P<rms>-?[0-9.]+|-inf)")


def detect_scene_events(info: VideoInfo, threshold: float = 0.3) -> list[Event]:
    """Scene-change events. threshold is ffmpeg's 0..1 scene score."""
    if not 0 < threshold < 1:
        raise IngestError("scene threshold must be between 0 and 1")
    proc = _run([
        _tool("ffmpeg", "FFMPEG_BIN"), "-v", "info", "-nostats", "-i", info.path,
        "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-",
    ])
    if proc.returncode != 0:
        raise IngestError("scene detection failed")
    events = []
    for line in proc.stderr.splitlines():
        if "showinfo" not in line:
            continue
        t = re.search(r"pts_time:\s*([0-9.]+)", line)
        if t:
            events.append(Event(t=round(float(t.group(1)), 3), kind="scene", strength=1.0))
    return events


def detect_audio_events(info: VideoInfo, window_s: float = 1.0, z: float = 1.5) -> list[Event]:
    """Loudness-peak events: windows whose RMS is z standard deviations above the mean.
    Returns [] for videos with no audio track."""
    if not info.has_audio:
        return []
    if window_s <= 0 or z <= 0:
        raise IngestError("window_s and z must be positive")
    proc = _run([
        _tool("ffmpeg", "FFMPEG_BIN"), "-v", "info", "-nostats", "-i", info.path, "-vn",
        "-af", f"asetnsamples=n={int(48000 * window_s)},astats=metadata=1:reset=1,"
               "ametadata=print:key=lavfi.astats.Overall.RMS_level",
        "-ar", "48000", "-f", "null", "-",
    ])
    if proc.returncode != 0:
        raise IngestError("audio analysis failed")
    samples: list[tuple[float, float]] = []
    t = None
    for line in proc.stderr.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"RMS_level=(-?[0-9.]+|-inf)", line)
        if m and t is not None:
            val = m.group(1)
            samples.append((t, -120.0 if val == "-inf" else float(val)))
            t = None
    return loudness_events(samples, z)


def loudness_events(samples: list[tuple[float, float]], z: float = 1.5) -> list[Event]:
    """Pure helper: pick (t, dB) samples that stand out from the rest."""
    if len(samples) < 3:
        return []
    levels = [db for _, db in samples]
    mean = statistics.fmean(levels)
    sd = statistics.pstdev(levels)
    if sd < 0.5:                       # flat audio: nothing stands out
        return []
    out = []
    for t, db in samples:
        score = (db - mean) / sd
        if score >= z:
            out.append(Event(t=round(t, 3), kind="audio", strength=round(score, 3)))
    return out


def cut_clip(info: VideoInfo, start: float, end: float, target: str | os.PathLike,
             width: int | None = None) -> Path:
    if not 0 <= start < end <= info.duration_s + 0.05:
        raise IngestError("clip window outside the video")
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_tool("ffmpeg", "FFMPEG_BIN"), "-v", "error", "-y",
           "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", info.path,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart"]
    if width:
        cmd += ["-vf", f"scale={width}:-2"]
    cmd += (["-c:a", "aac", "-b:a", "128k"] if info.has_audio else ["-an"]) + [str(target)]
    proc = _run(cmd)
    if proc.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise IngestError(f"could not cut clip {start:.1f}-{end:.1f}s")
    return target


def cut_highlights(path: str | os.PathLike, out_dir: str | os.PathLike, top: int = 5,
                   pre_s: float = 4.0, post_s: float = 4.0, scene_threshold: float = 0.3,
                   width: int | None = None) -> tuple[VideoInfo, list[ClipWindow], list[Path]]:
    """Detect, rank, cut. Writes clip_NN.mp4 files and highlights.json into out_dir."""
    info = probe(path)
    events = detect_scene_events(info, scene_threshold) + detect_audio_events(info)
    windows = pick_clips(events, info.duration_s, top=top, pre_s=pre_s, post_s=post_s)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = [cut_clip(info, w.start, w.end, out / f"clip_{i:02d}.mp4", width)
             for i, w in enumerate(windows)]
    (out / "highlights.json").write_text(json.dumps({
        "video": asdict(info), "events": len(events),
        "clips": [dict(asdict(w), file=str(f)) for w, f in zip(windows, files)],
    }, indent=2), encoding="utf-8")
    return info, windows, files
