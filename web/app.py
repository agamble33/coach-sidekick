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
  POST /api/live/start        -> {live_id}        (screen-share session)
  POST /api/live/{id}/frame   JPEG of the player's screen (every few seconds)
  POST /api/live/{id}/stop
  POST /api/turn {live_id, text|watch:true}  Coach turn against the live screen
"""

from __future__ import annotations

import json
import re
import os
import queue
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from coach.gamestate import GameState
from coach.guard import Guard, GuardError, Limits
from coach.profile import PlayerProfile
from pydantic import BaseModel, Field

from coach.agent import TEACH_PROMPT, WATCH_PROMPT, CoachAgent
from coach.annotations import AnnotationStore
from coach.clips import detect_audio_events, detect_scene_events
from coach.config import load_settings
from coach.health import health_report
from coach.incidents import STATUSES, IncidentStore
from coach.ingest import VIDEO_SUFFIXES, IngestError, probe
from coach.memory import MatchMemory
from coach.meta_api import MetaAPIError, MetaClient
from coach.moments import pick_clips
from coach.playbook import PlaybookError, PlaybookStore
from coach.tools import LiveFeed, Session
from coach.voice import VoiceError, to_wav_24k, transcribe_file

STATIC = Path(__file__).parent / "static"
DATA = Path(os.environ.get("COACH_DATA", "coach_data")).resolve()
MAX_UPLOAD = 500 * 1024 * 1024
MAX_AUDIO = 25 * 1024 * 1024

app = FastAPI(title="Coach: Coach")
_lock = threading.Lock()
_agents: dict[str, CoachAgent] = {}
_matches: dict[str, dict] = {}
_live: dict[str, LiveFeed] = {}
MAX_LIVE = 20

# ---- pilot consent -------------------------------------------------------------------
# Coach must not see the screen, hear the mic or take a match video until the player has
# agreed to the pilot terms (web/static/terms.html). The page asks once and stores the
# consent id; every gated request carries it in X-Coach-Consent and the server checks it
# against the consents it has recorded, so the gate is enforced here, not only in the UI.
CONSENT_VERSION = "pilot-2026-11-01"
_consents: set[str] = set()
_consents_loaded = False


def _consent_file() -> Path:
    return DATA / "consents.jsonl"


def _load_consents() -> None:
    global _consents_loaded
    if _consents_loaded:
        return
    f = _consent_file()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("version") == CONSENT_VERSION and rec.get("consent_id"):
                _consents.add(rec["consent_id"])
    _consents_loaded = True


def require_consent(x_coach_consent: str | None = Header(default=None)) -> str:
    _load_consents()
    if not x_coach_consent or x_coach_consent not in _consents:
        raise HTTPException(403, "Pilot consent required: agree to the pilot terms before Coach can see or hear your game")
    return x_coach_consent


class ConsentIn(BaseModel):
    version: str
    see: bool = False
    hear: bool = False
    age_ok: bool = False


@app.get("/terms")
def terms():
    return FileResponse(STATIC / "terms.html")


@app.get("/api/consent/version")
def consent_version():
    return {"version": CONSENT_VERSION}


@app.post("/api/consent")
def give_consent(body: ConsentIn, user_agent: str | None = Header(default=None)):
    if body.version != CONSENT_VERSION:
        raise HTTPException(400, f"these terms are version {CONSENT_VERSION}; reload the page")
    if not (body.see and body.hear and body.age_ok):
        raise HTTPException(400, "all three boxes must be checked")
    _load_consents()
    cid = secrets.token_hex(12)
    rec = {"consent_id": cid, "version": body.version, "see": True, "hear": True, "age_ok": True,
           "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "user_agent": (user_agent or "")[:200]}
    with _lock:
        DATA.mkdir(parents=True, exist_ok=True)
        with _consent_file().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        _consents.add(cid)
    return {"consent_id": cid, "version": body.version}


def _client_factory() -> MetaClient:
    return MetaClient(load_settings())


app.state.client_factory = _client_factory
app.state.transcribe = transcribe_file
app.state.memory = MatchMemory(DATA / "memory.json")
app.state.profile = PlayerProfile(DATA / "profile.json")
app.state.guard = Guard(DATA / "budget.json", Limits.from_env(), disabled=os.environ.get("COACH_DISABLED", "") in ("1", "true", "yes"))


def _subject(request: Request) -> str:
    """Who to count against: the consent id when present, else the client address."""
    cid = request.headers.get("x-coach-consent") or ""
    return cid[:32] if cid else (request.client.host if request.client else "anon")


def _guard(request: Request, kind: str) -> str:
    sub = _subject(request)
    try:
        app.state.guard.check(kind, sub)
    except GuardError as exc:
        raise HTTPException(exc.status, exc.message)
    return sub
app.state.playbooks = PlaybookStore(DATA / "playbook.json")
app.state.annotations = AnnotationStore(DATA / "annotations" / "records.jsonl")
app.state.incidents = IncidentStore(DATA / "incidents" / "incidents.jsonl")


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
async def upload_match(file: UploadFile = File(...), consent: str = Depends(require_consent)):
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
    live_id: str | None = None
    text: str | None = Field(default=None, max_length=4000)
    watch: bool = False
    teach: bool = False


def _agent_for(mid: str | None, live_id: str | None = None) -> CoachAgent:
    key = f"live:{live_id}" if live_id else (mid or "none")
    with _lock:
        if key not in _agents:
            meta = _load(mid) if mid else None
            feed = None
            if live_id:
                feed = _live.get(live_id)
                if feed is None:
                    raise HTTPException(404, "live session not found")
            try:
                client = app.state.client_factory()
            except MetaAPIError as exc:
                raise HTTPException(503, str(exc))
            session = Session(work_dir=Path(meta["video"]).parent if meta else DATA / "scratch",
                              memory=app.state.memory, profile=app.state.profile,
                              match=meta["name"] if meta else ("live session" if live_id else "no match"),
                              video=meta["video"] if meta else None, client=client, live=feed,
                              annotations=app.state.annotations, incidents=app.state.incidents,
                              live_id=live_id or "")
            _agents[key] = CoachAgent(client, session)
        agent = _agents[key]
        agent.session.playbook = app.state.playbooks.load()      # always current
        return agent


@app.post("/api/live/start")
def live_start(consent: str = Depends(require_consent)):
    with _lock:
        if len(_live) >= MAX_LIVE:
            oldest = min(_live, key=lambda k: _live[k].started)
            _live.pop(oldest, None); _agents.pop(f"live:{oldest}", None)
        lid = secrets.token_hex(8)
        _live[lid] = LiveFeed()
    return {"live_id": lid}


@app.post("/api/live/{lid}/frame")
async def live_frame(lid: str, request: Request, file: UploadFile = File(...)):
    _guard(request, "frames")
    feed = _live.get(lid)
    if feed is None:
        raise HTTPException(404, "live session not found")
    data = await file.read()
    try:
        feed.push(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "frames": len(feed)}


@app.post("/api/live/{lid}/stop")
def live_stop(lid: str):
    with _lock:
        _live.pop(lid, None)
        _agents.pop(f"live:{lid}", None)
    return {"ok": True}


# ---- overlay ---------------------------------------------------------------------------
# The overlay page (/overlay?live=ID) draws Coach's highlight boxes, task list and last callout
# over the game: as an OBS browser source, in Corner mode, or pinned into VR. It polls this.
@app.get("/overlay")
def overlay_page():
    return FileResponse(STATIC / "overlay.html")


def _overlay_for(lid: str):
    if lid not in _live:
        raise HTTPException(404, "live session not found")
    agent = _agents.get(f"live:{lid}")
    return agent.session.overlay if agent else None


@app.get("/api/overlay/{lid}")
def overlay_state(lid: str):
    ov = _overlay_for(lid)
    if ov is None:
        from coach.reactions.engine import ReactionEngine
        d = ReactionEngine(validate_assets=False).state()   # defaults before Coach's agent exists for this session
        return {"highlights": [], "tasks": [], "callout": "", "callout_at": 0, "hidden": False, "reaction": None, "guide": False, "pointers": [], "route": [],
                "layout": {"tasks": "bl", "callout": "top", "badge": "tl"}, "updated": 0, "now": time.time(),
                "avatar_url": d["avatar_url"], "avatar_label": d["avatar_label"]}
    snap = ov.snapshot()
    rx = _agents[f"live:{lid}"].session.reactions
    snap["avatar_url"], snap["avatar_label"] = rx.avatar_url(), rx.state()["avatar_label"]
    return snap


class OverlaySettingsIn(BaseModel):
    hidden: bool | None = None
    layout: dict | None = None
    spice: str | None = None     # reactions: off | mild | unhinged
    pack: str | None = None      # reactions: 3d | classic
    avatar: str | None = None    # reactions: muse_bot | coach | dog
    guide: bool | None = None    # Guide me: let Coach draw arrows and routes


@app.post("/api/overlay/{lid}/settings")
def overlay_settings(lid: str, body: OverlaySettingsIn, consent: str = Depends(require_consent)):
    """Hide or show the overlay (the Coach key) and move its panels off the game's own HUD."""
    if lid not in _live:
        raise HTTPException(404, "live session not found")
    ov = _agent_for(None, lid).session.overlay
    if body.hidden is not None:
        ov.hidden = bool(body.hidden); ov.touch()
    if body.guide is not None:
        ov.guide = bool(body.guide)
        if not ov.guide:
            ov.clear_guidance()
        ov.touch()
    if body.layout is not None:
        try:
            ov.set_layout(body.layout)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    rx = _agent_for(None, lid).session.reactions
    try:
        if body.spice is not None:
            rx.set_spice(body.spice)
        if body.pack is not None:
            rx.set_pack(body.pack)
        if body.avatar is not None:
            rx.set_avatar(body.avatar)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    ov.touch()
    return {"hidden": ov.hidden, "layout": dict(ov.layout), "spice": rx.spice, "pack": rx.pack, "avatar": rx.avatar,
            "guide": ov.guide, "reactions": rx.state()}


class ReactTestIn(BaseModel):
    trigger: str = "missed_jump"


@app.post("/api/overlay/{lid}/react")
def overlay_react(lid: str, body: ReactTestIn, consent: str = Depends(require_consent)):
    """Fire one reaction by hand (the Test button in settings). Same engine and cooldowns as Coach's react tool."""
    if lid not in _live:
        raise HTTPException(404, "live session not found")
    s = _agent_for(None, lid).session
    payload = s.reactions.fire(body.trigger, "test from settings")
    if payload is None:
        _, why = s.reactions.can_fire(body.trigger)
        return {"fired": False, "reason": why}
    s.overlay.react(payload)
    return {"fired": True, "reaction": payload}


class PointTestIn(BaseModel):
    x: float = 0.72
    y: float = 0.4
    label: str = "Go here"
    direction: str = "here"


@app.post("/api/overlay/{lid}/point")
def overlay_point(lid: str, body: PointTestIn, consent: str = Depends(require_consent)):
    """Draw one arrow by hand (the Test arrow button). Same path as Coach's point tool, same Guide me gate."""
    if lid not in _live:
        raise HTTPException(404, "live session not found")
    from coach.tools import run_tool
    s = _agent_for(None, lid).session
    out = run_tool(s, "point", {"x": body.x, "y": body.y, "label": body.label, "direction": body.direction})
    return {"ok": out.startswith("pointed"), "result": out, "overlay": s.overlay.snapshot()}


# ---- Gate 12: Game SDK. A game that integrates Coach posts its state here and reads directives back. ----

@app.post("/api/game/{lid}/state")
def game_state_in(lid: str, body: dict, consent: str = Depends(require_consent)):
    """The game reports player, objective, landmarks and events (see docs/game-sdk.md).
    Events that match a reaction trigger fire the meme reaction directly, no model call."""
    if lid not in _live:
        raise HTTPException(404, "live session not found")
    s = _agent_for(None, lid).session
    try:
        triggers = s.game_state.update(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    fired = []
    for t in triggers:
        payload = s.reactions.fire(t, "game event")
        if payload:
            s.overlay.react(payload)
            fired.append(t)
    return {"ok": True, "posts": s.game_state.posts, "landmarks": len(s.game_state.landmarks), "reactions_fired": fired,
            "fresh": s.game_state.fresh()}


@app.get("/api/game/{lid}/directives")
def game_directives(lid: str):
    """Everything the game should draw or say: the overlay snapshot (callout, tasks, pointers and route with
    landmark ids, reaction) plus what Coach currently knows about the game. Poll every 0.5 to 1 s."""
    if lid not in _live:
        raise HTTPException(404, "live session not found")
    agent = _agents.get(f"live:{lid}")
    if agent is None:
        return {"overlay": overlay_state(lid), "game": GameState().snapshot(), "speak": ""}
    ov = agent.session.overlay.snapshot()
    ov["avatar_url"], ov["avatar_label"] = agent.session.reactions.avatar_url(), agent.session.reactions.state()["avatar_label"]
    return {"overlay": ov, "game": agent.session.game_state.snapshot(), "speak": ov["callout"], "speak_at": ov["callout_at"]}


@app.get("/api/game/{lid}/state")
def game_state_out(lid: str):
    if lid not in _live:
        raise HTTPException(404, "live session not found")
    agent = _agents.get(f"live:{lid}")
    return agent.session.game_state.snapshot() if agent else GameState().snapshot()


class PreferenceIn(BaseModel):
    game: str = "any game"
    category: str
    name: str
    value: str


@app.get("/api/profile")
def profile_get():
    """The player's saved preferences, all games."""
    return app.state.profile.snapshot()


@app.put("/api/profile")
def profile_put(body: PreferenceIn):
    try:
        return app.state.profile.set(body.game, body.category, body.name, body.value)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/profile")
def profile_delete(game: str, name: str = ""):
    return {"removed": app.state.profile.forget(game, name)}


@app.get("/api/guard")
def guard_status():
    """Operator view of the abuse caps: tokens used today, refusals, limits. No per-person data."""
    st = app.state.guard.status()
    st["offtopic_redirects"] = sum(a.offtopic for a in _agents.values())
    return st


@app.get("/api/reactions")
def reactions_catalog():
    """What the reaction feature offers (spice levels, packs, avatars, triggers) for the settings panel."""
    from coach.reactions.engine import ReactionEngine
    return ReactionEngine(validate_assets=False).state()


@app.post("/api/overlay/{lid}/demo")
def overlay_demo(lid: str, consent: str = Depends(require_consent)):
    """Fill the overlay with sample content so a studio can place and size it before going live."""
    if lid not in _live:
        raise HTTPException(404, "live session not found")
    agent = _agent_for(None, lid)
    ov = agent.session.overlay
    ov.add_highlight(0.62, 0.28, 0.14, 0.2, "Enemy here", 20)
    ov.add_highlight(0.12, 0.66, 0.1, 0.1, "Health", 20)
    ov.set_tasks(["Clear the courtyard", "Grab the key by the fountain", "Open the east gate"])
    ov.task_done(1)
    ov.say("Push left, two of them are reloading.")
    if ov.guide:
        ov.add_pointer(0.78, 0.42, "East gate", "here", 20)
        ov.add_pointer(0.04, 0.5, "Key", "left", 20)
        ov.set_route([{"x": 0.3, "y": 0.75, "label": "Courtyard"}, {"x": 0.5, "y": 0.55, "label": "Fountain"},
                      {"x": 0.78, "y": 0.42, "label": "East gate"}], 20)
    demo_rx = agent.session.reactions.fire("missed_jump", "demo")
    if demo_rx:
        ov.react(demo_rx)
    return ov.snapshot()


@app.post("/api/turn")
def turn(body: TurnIn, request: Request):
    subject = _guard(request, "turns")
    text = (body.text or "").strip()
    if body.watch:
        if not body.live_id:
            raise HTTPException(400, "watch needs a live_id")
        text = TEACH_PROMPT if body.teach else WATCH_PROMPT
    if not text:
        raise HTTPException(422, "text is required")
    agent = _agent_for(body.match_id, body.live_id)
    agent.session.teach = body.teach
    if body.teach and agent.session.playbook is None:
        raise HTTPException(400, "teach mode needs a playbook; save one first")
    q: queue.Queue = queue.Queue()
    agent.on_event = lambda kind, data: q.put((kind, data))

    def work():
        try:
            r = agent.turn(text)
            app.state.guard.record_usage(subject, r.input_tokens + r.output_tokens)
            q.put(("done", {"text": r.text, "rounds": r.rounds, "input_tokens": r.input_tokens,
                            "output_tokens": r.output_tokens, "spoken": agent.session.spoken[-3:],
                            "record_id": r.record_id, "offtopic": r.offtopic}))
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
async def transcribe(request: Request, file: UploadFile = File(...), consent: str = Depends(require_consent)):
    _guard(request, "transcribes")
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
        # named "upload", not "in": a .wav upload used to collide with the in.wav the converter
        # writes, so ffmpeg clobbered its own input and every WAV upload failed with 400
        src = Path(td) / ("upload" + (Path(file.filename or "").suffix or ".webm"))
        src.write_bytes(data)
        try:
            wav = to_wav_24k(src, Path(td) / "in.wav")
            t = app.state.transcribe(client, wav, "PUSH_TO_TALK", ["Coach"])
        except (VoiceError, MetaAPIError) as exc:
            raise HTTPException(400, str(exc))
    return {"transcript": t.text, "audio_ms": t.audio_ms}


class PlaybookIn(BaseModel):
    game: str = Field(min_length=1, max_length=80)
    audience: str = ""
    goal: str = ""
    controls: str = ""
    rules: str = ""
    tips: str = ""
    mistakes: str = ""


@app.get("/api/playbook")
def get_playbook():
    pb = app.state.playbooks.load()
    return {"playbook": asdict(pb) if pb else None}


@app.put("/api/playbook")
def put_playbook(body: PlaybookIn):
    try:
        pb = app.state.playbooks.save(body.model_dump())
    except PlaybookError as exc:
        raise HTTPException(400, str(exc))
    return {"playbook": asdict(pb), "chars": pb.total_chars()}


@app.delete("/api/playbook")
def delete_playbook():
    app.state.playbooks.clear()
    return {"ok": True}


class LabelIn(BaseModel):
    label: str = Field(pattern="^(up|down)$")
    correction: str = Field(default="", max_length=300)


@app.post("/api/annotations/{rid}/label")
def label_record(rid: str, body: LabelIn):
    try:
        r = app.state.annotations.label(rid, body.label, body.correction)
    except KeyError:
        raise HTTPException(404, "record not found")
    return {"id": r.id, "label": r.label, "correction": r.correction, "stats": app.state.annotations.stats()}


@app.get("/api/annotations/stats")
def annotation_stats(game: str | None = None):
    return app.state.annotations.stats(game)


@app.get("/api/annotations/recent")
def annotation_recent(limit: int = 30, game: str | None = None):
    return {"records": [asdict(r) for r in app.state.annotations.recent(min(max(limit, 1), 200), game)]}


@app.get("/api/annotations/frame/{name}")
def annotation_frame(name: str):
    if "/" in name or "\\" in name or ".." in name or not name.endswith(".jpg"):
        raise HTTPException(400, "bad frame name")
    p = app.state.annotations.frames_dir / name
    if not p.is_file():
        raise HTTPException(404, "frame not found")
    return FileResponse(p, media_type="image/jpeg")


@app.post("/api/annotations/export")
def annotation_export(game: str | None = None, include_unlabeled: bool = False):
    out = DATA / "annotations" / "training.jsonl"
    n = app.state.annotations.export_training(out, game, include_unlabeled)
    return {"examples": n, "file": out.name}


@app.get("/api/annotations/export")
def annotation_export_download():
    out = DATA / "annotations" / "training.jsonl"
    if not out.is_file():
        raise HTTPException(404, "export first with POST /api/annotations/export")
    return FileResponse(out, media_type="application/jsonl", filename="coach-training.jsonl")


# ---- safety reports (studio or admin) ------------------------------------------------------
# Protected by COACH_ADMIN_TOKEN when it is set (header X-Coach-Admin); open on a pilot box with
# no token, since the page is only reachable on the local network.
def require_admin(x_coach_admin: str | None = Header(default=None)) -> None:
    token = os.environ.get("COACH_ADMIN_TOKEN", "")
    if token and not (x_coach_admin and secrets.compare_digest(x_coach_admin, token)):
        raise HTTPException(401, "admin token required")


@app.get("/admin/incidents")
def incidents_page():
    return FileResponse(STATIC / "incidents.html")


@app.get("/api/incidents")
def incidents_list(limit: int = 50, status: str | None = None, category: str | None = None,
                   _: None = Depends(require_admin)):
    store = app.state.incidents
    return {"incidents": [asdict(i) for i in store.recent(limit=max(1, min(limit, 200)), status=status, category=category)],
            "stats": store.stats()}


class IncidentStatusIn(BaseModel):
    status: str = Field(pattern="^(" + "|".join(STATUSES) + ")$")
    note: str = Field(default="", max_length=300)


@app.post("/api/incidents/{iid}/status")
def incidents_status(iid: str, body: IncidentStatusIn, _: None = Depends(require_admin)):
    try:
        inc = app.state.incidents.set_status(iid, body.status, body.note)
    except KeyError:
        raise HTTPException(404, "no such report")
    return asdict(inc)


@app.get("/api/incidents/frame/{name}")
def incidents_frame(name: str, _: None = Depends(require_admin)):
    if not re.fullmatch(r"[0-9a-f]{12}\.jpg", name):
        raise HTTPException(400, "bad frame name")
    f = app.state.incidents.frames_dir / name
    if not f.is_file():
        raise HTTPException(404, "no frame")
    return FileResponse(f, media_type="image/jpeg")


@app.get("/api/memory")
def memory():
    return {"notes": [asdict(n) for n in app.state.memory.recall(limit=50)]}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
# reaction cards + sound stings (engine payloads point at /reactions/images/... and /reactions/sounds/...)
from coach.reactions.engine import ASSETS as REACTION_ASSETS
app.mount("/reactions", StaticFiles(directory=REACTION_ASSETS), name="reactions")
