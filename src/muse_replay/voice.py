"""Gate 3: voice in (Muse Voice Transcribe) and voice out (local OS voice).

to_wav_24k:      convert any audio/video to the WAV the API accepts (ffmpeg).
transcribe_file: upload a WAV to /asr/transcribe and parse the transcript.
speak:           say text with the local OS voice; falls back to printing.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .ingest import IngestError, _run, _tool
from .meta_api import MetaClient

ASR_MODEL = "muse-voice-transcribe-1.0"
ASR_MODES = {"PUSH_TO_TALK", "ENDPOINTING", "DIARIZATION"}
MAX_WAV_BYTES = 32 * 1024 * 1024
MAX_AUDIO_S = 10 * 60
MAX_SPEAK_CHARS = 400


class VoiceError(RuntimeError):
    pass


# ---------- audio conversion ----------

def to_wav_24k(src: str | os.PathLike, dst: str | os.PathLike,
               start_s: float | None = None, end_s: float | None = None) -> Path:
    """Mono, 16-bit PCM, 24 kHz WAV, metadata stripped. Optional time window."""
    src, dst = Path(src), Path(dst)
    if not src.is_file():
        raise VoiceError(f"file not found: {src}")
    if start_s is not None and end_s is not None and end_s <= start_s:
        raise VoiceError("end must be after start")
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_tool("ffmpeg", "FFMPEG_BIN"), "-v", "error", "-y"]
    if start_s is not None:
        cmd += ["-ss", f"{start_s:.3f}"]
    if end_s is not None:
        cmd += ["-to", f"{end_s:.3f}"]
    cmd += ["-i", str(src), "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le",
            "-map_metadata", "-1", str(dst)]
    proc = _run(cmd)
    if proc.returncode != 0 or not dst.is_file() or dst.stat().st_size <= 44:
        raise VoiceError(f"could not convert {src.name} to WAV (no audio track?)")
    return dst


@dataclass(frozen=True)
class WavInfo:
    channels: int
    sample_rate: int
    bits: int
    duration_s: float


def check_wav(path: str | os.PathLike) -> WavInfo:
    """Validate the WAV header against what the API accepts. Pure Python."""
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_WAV_BYTES:
        raise VoiceError(f"WAV is {size / 1e6:.1f} MB; limit is 32 MB")
    with open(p, "rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise VoiceError("not a RIFF/WAVE file")
        fmt = None
        data_len = None
        while True:
            chunk = f.read(8)
            if len(chunk) < 8:
                break
            cid, clen = chunk[:4], struct.unpack("<I", chunk[4:])[0]
            if cid == b"fmt ":
                fmt = f.read(clen)
            elif cid == b"data":
                data_len = clen
                break
            else:
                f.seek(clen + (clen & 1), 1)
    if fmt is None or data_len is None:
        raise VoiceError("WAV is missing fmt or data chunk")
    audio_format, channels, rate, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
    if audio_format != 1 or bits != 16:
        raise VoiceError("WAV must be 16-bit integer PCM")
    if channels != 1:
        raise VoiceError("WAV must be mono")
    if rate not in (16000, 24000):
        raise VoiceError("WAV must be 16 kHz or 24 kHz")
    duration = data_len / (rate * channels * 2)
    if duration > MAX_AUDIO_S:
        raise VoiceError("audio is longer than 10 minutes")
    return WavInfo(channels, rate, bits, round(duration, 3))


# ---------- transcription ----------

@dataclass(frozen=True)
class Turn:
    turn_id: int
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None


@dataclass(frozen=True)
class Transcript:
    text: str
    audio_ms: int
    turns: tuple[Turn, ...]
    session_id: str


def build_asr_request(mode: str = "PUSH_TO_TALK", keywords: list[str] | None = None,
                      language_bias: list[str] | None = None) -> dict:
    if mode not in ASR_MODES:
        raise VoiceError(f"mode must be one of {sorted(ASR_MODES)}")
    req: dict = {"model": ASR_MODEL, "audioEncoding": "WAV", "mode": mode}
    if keywords:
        req["keywords"] = [k.strip() for k in keywords if k.strip()][:100]
    if language_bias:
        req["languageBias"] = list(language_bias)
    return req


def parse_transcript(data: dict) -> Transcript:
    if "transcript" not in data:
        raise VoiceError("response has no transcript")
    turns = tuple(
        Turn(int(t.get("turnId", i + 1)), int(t.get("startMs", 0)), int(t.get("endMs", 0)),
             str(t.get("transcript", "")).strip(), t.get("speaker"))
        for i, t in enumerate(data.get("turns") or [])
    )
    return Transcript(str(data["transcript"]).strip(), int(data.get("audioDurationMs", 0)),
                      turns, str(data.get("sessionId", "")))


def transcribe_file(client: MetaClient, wav_path: str | os.PathLike, mode: str = "PUSH_TO_TALK",
                    keywords: list[str] | None = None, language_bias: list[str] | None = None) -> Transcript:
    check_wav(wav_path)
    req = build_asr_request(mode, keywords, language_bias)
    data = client.post_multipart("/asr/transcribe", {
        "request": ("", json.dumps(req).encode(), "application/json"),
        "audio": (Path(wav_path).name, Path(wav_path).read_bytes(), "audio/wav"),
    })
    return parse_transcript(data)


# ---------- speech out ----------

def clean_for_speech(text: str) -> str:
    """Strip markdown-ish noise and cap length so the voice never rambles."""
    t = text.replace("\u2014", ", ").replace("\u2013", ", ").replace(" - ", ", ")
    t = t.replace("*", "").replace("`", "").replace("#", "").replace("_", " ")
    t = " ".join(t.split())
    if len(t) > MAX_SPEAK_CHARS:
        cut = t[:MAX_SPEAK_CHARS]
        t = cut[: cut.rfind(" ")] if " " in cut else cut
        t = t.rstrip(",;:") + "..."
    return t


def pick_speaker() -> str:
    """Which TTS backend is available: 'sapi' (Windows), 'say' (macOS), 'espeak', or 'print'."""
    if platform.system() == "Windows" and shutil.which("powershell"):
        return "sapi"
    if platform.system() == "Darwin" and shutil.which("say"):
        return "say"
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        return "espeak"
    return "print"


def speak(text: str, backend: str | None = None, runner=subprocess.run) -> str:
    """Say `text`. Returns the backend used. `runner` is injectable for tests."""
    said = clean_for_speech(text)
    if not said:
        return "none"
    backend = backend or pick_speaker()
    if backend == "sapi":
        script = ("Add-Type -AssemblyName System.Speech; "
                  "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "$s.Rate = 1; $s.Speak([Console]::In.ReadToEnd())")
        runner(["powershell", "-NoProfile", "-Command", script], input=said, text=True, timeout=60)
    elif backend == "say":
        runner(["say", said], timeout=60)
    elif backend == "espeak":
        runner([shutil.which("espeak-ng") or "espeak", said], timeout=60)
    else:
        print(f"[Coach] {said}")
        return "print"
    return backend
