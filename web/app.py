"""Gate 5: the Coach web app. FastAPI backend + one static page.

Routes
  GET  /                      the app
  GET  /api/health            provider status (no key values)
  POST /api/match             upload a match video (mp4/mkv/mov/webm) -> match id + info
  POST /api/match/sample      generate a synthetic demo match with ffmpeg
  GET  /api/match/{id}        info, moments, clips
  GET  /api/match/{id}/video  stream the video
  GET  /api/match/{id}/clips/{name}
  POST /api/turn              {match_id, text} -> SSE stream of tool events then the reply
  POST /api/transcribe        audio blob (any format) -> {transcript}
  GET  /api/memory            notes Coach has saved
"""

from __future__ import annotations

import json
import os
import queue
import secrets
import shutil
import subprocess
import tempfile
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from muse_replay.agent import CoachAgent
from muse_replay.clips import detect_audio_events, detect_scene_events
from muse_replay.config import load_settings
from muse_replay.health import health_report
from muse_replay.ingest import VIDEO_SUFFIXES, IngestError, probe
from muse_replay.memory import MatchMemory
from muse_replay.meta_api import MetaAPIError, MetaClient
from muse_replay.moments import pick_clips
from muse_replay.tools import Session
from muse_replay.voice import VoiceError, to_wav_24k, transcribe_file

STATIC = Path(__file__).parent / "static"
DATA = Path(os.environ.get("COACH_DATA", "coach_data")).resolve()
MAX_UPLOAD = 500 * 1024 * 1024
MAX_AUDIO = 25 * 1024 * 1024

app = FastAPI(title="Muse Replay: Coach")
_lock = threading.Lock()
_agents: dict[str, CoachAgent] = {}
_matches: dict[str, dict] = {}


def _client_factory() -> MetaClient:
    return MetaClient(load_settings())


app.state.client_factory = _client_factory
app.state.transcribe = transcribe_file
app.state.memory = MatchMemory(DATA / "memory.json")


def _match_dir(mid: str) -> Path:
    if not mid.isalnum() or len(mid) > 32:
        raise HTTPException(400, "bad match id")
    d = DATA / "matches" / mid
    if not d.is_dir():
        raise HTTPException(404, "match not found")
    return d


def _register(mid: str, video: Path, name: str) -> dict:
    try:
        info = probe(video)
        events = detect_scene_events(info) + detect_audio_events(info)
        moments = [asdict(w) for w in pick_clips(events, info.duration_s, top=8)]
    except IngestError as exc:
        shutil.rmtree(video.parent, ignore_errors=True)
        raise HTTPException(400, str(exc))
    meta = {"id": mid, "name": name, "video": str(video), "info": asdict(info), "moments": moments}
    (video.parent / "match.json").write_text(json.dumps(meta), encoding="utf-8")
    _matches[mid] = meta
    return meta


def _load(mid: str) -> dict:
    if mid not in _matches:
        f = _match_dir(mid) / "match.json"
        _matches[mid] = json.loads(f.read_text(encoding="utf-8"))
    return _matches[mid]


def _public(meta: dict) -> dict:
    clips_dir = Path(meta["video"]).parent / "clips"
    clips = sorted(p.name for p in clips_dir.glob("*.mp4")) if clips_dir.is_dir() else []
    return {"id": meta["id"], "name": meta["name"], "info": meta["info"], "moments": meta["moments"], "clips": clips}


@app.get("/api/health")
def health():
    code, text = health_report()
    return {"ok": code == 0, "report": text, "ffmpeg": bool(shutil.which("ffmpeg"))}


@app.post("/api/match")
async def upload_match(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise HTTPException(400, f"unsupported file type; use one of {sorted(VIDEO_SUFFIXES)}")
    mid = secrets.token_hex(8)
    d = DATA / "matches" / mid
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"match{suffix}"
    size = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD:
                out.close()
                shutil.rmtree(d, ignore_errors=True)
                raise HTTPException(413, "video is larger than 500 MB")
            out.write(chunk)
    return _public(_register(mid, dest, Path(file.filename or "match").stem[:60]))


@app.post("/api/match/sample")
def sample_match():
    """A 30 s synthetic match (cuts at 10 s and 20 s, a loud burst at 24 s). No real footage needed."""
    mid = secrets.token_hex(8)
    d = DATA / "matches" / mid
    d.mkdir(parents=True, exist_ok=True)
    dest = d / "match.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "lavfi", "-i", "smptebars=duration=10:size=640x360:rate=30",
           "-f", "lavfi", "-i", "testsrc=duration=10:size=640x360:rate=30",
           "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
           "-filter_complex",
           "[2:v]trim=duration=10,setpts=PTS-STARTPTS[m];[0:v][1:v][m]concat=n=3:v=1:a=0[v];"
           "[3:a]volume='if(between(t,24,25),1.0,0.02)':eval=frame[a]",
           "-map", "[v]", "-map", "[a]", "-pix_fmt", "yuv420p", "-t", "30", str(dest)]
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(500, "ffmpeg could not build the sample")
    return _public(_register(mid, dest, "Sample match"))


@app.get("/api/match/{mid}")
def get_match(mid: str):
    return _public(_load(mid))


@app.get("/api/match/{mid}/video")
def get_video(mid: str):
    return FileResponse(_load(mid)["video"], media_type="video/mp4")


@app.get("/api/match/{mid}/clips/{name}")
def get_clip(mid: str, name: str):
    if "/" in name or "\\" in name or ".." in name or not name.endswith(".mp4"):
        raise HTTPException(400, "bad clip name")
    p = _match_dir(mid) / "clips" / name
    if not p.is_file():
        raise HTTPException(404, "clip not found")
    return FileResponse(p, media_type="video/mp4")


class TurnIn(BaseModel):
    match_id: str | None = None
    text: str = Field(min_length=1, max_length=4000)


def _agent_for(mid: str | None) -> CoachAgent:
    key = mid or "none"
    with _lock:
        if key not in _agents:
            meta = _load(mid) if mid else None
            try:
                client = app.state.client_factory()
            except MetaAPIError as exc:
                raise HTTPException(503, str(exc))
            session = Session(work_dir=Path(meta["video"]).parent if meta else DATA / "scratch",
                              memory=app.state.memory, match=meta["name"] if meta else "no match",
                              video=meta["video"] if meta else None, client=client)
            _agents[key] = CoachAgent(client, session)
        return _agents[key]


@app.post("/api/turn")
def turn(body: TurnIn):
    agent = _agent_for(body.match_id)
    q: queue.Queue = queue.Queue()
    agent.on_event = lambda kind, data: q.put((kind, data))

    def work():
        try:
            r = agent.turn(body.text)
            q.put(("done", {"text": r.text, "rounds": r.rounds, "input_tokens": r.input_tokens,
                            "output_tokens": r.output_tokens, "spoken": agent.session.spoken[-3:]}))
        except (MetaAPIError, ValueError) as exc:
            q.put(("error", {"message": str(exc)}))
        except Exception as exc:                       # never leave the stream empty
            q.put(("error", {"message": f"unexpected {type(exc).__name__}: {exc}"}))
        finally:
            q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while True:
            item = q.get()
            if item is None:
                break
            kind, data = item
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_AUDIO:
        raise HTTPException(413, "audio is larger than 25 MB")
    if not data:
        raise HTTPException(400, "empty audio")
    try:
        client = app.state.client_factory()
    except MetaAPIError as exc:
        raise HTTPException(503, str(exc))
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / ("in" + (Path(file.filename or "").suffix or ".webm"))
        src.write_bytes(data)
        try:
            wav = to_wav_24k(src, Path(td) / "in.wav")
            t = app.state.transcribe(client, wav, "PUSH_TO_TALK", ["Coach"])
        except (VoiceError, MetaAPIError) as exc:
            raise HTTPException(400, str(exc))
    return {"transcript": t.text, "audio_ms": t.audio_ms}


@app.get("/api/memory")
def memory():
    return {"notes": [asdict(n) for n in app.state.memory.recall(limit=50)]}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
