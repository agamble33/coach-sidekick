<p align="center"><img src="media/coach-logo.png" alt="Coach" width="260"></p>

# Coach

**An in-game AI sidekick.** Coach plays with you, not for you: live strategy while you play, a guide that teaches new players by playing alongside them, and a teammate that remembers what happened last match. It sees the game, hears you, talks back, and acts through tool calls.

- **For players:** a teammate on voice chat that watches your screen, calls out what matters, and clips the plays worth keeping.
- **For studios:** drop in a playbook and Coach onboards new players inside the game. No training portal, no tutorial level to build.

Built for the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026). Coach is an independent project by Goals and Gambles LLC; it is not a Meta product and uses no Meta brand assets. Model names below are stated only to document which models it calls.

## What is a Meta model call and what is not

| Part | What it uses |
|---|---|
| Reasoning, tool calling, teaching, replies | Muse Spark 1.3 (Contributor variant by default) through the Meta Model API `/responses` endpoint |
| Seeing the game (`look`, `look_now`) | The same Muse Spark call with an image input |
| Speech to text (mic, `transcribe`) | Muse Voice Transcribe 1.0 through `/asr/transcribe` |
| Speech out | No model. The operating system voice (Windows SAPI, macOS say, espeak) in the CLI; the browser's built-in `speechSynthesis` in the web app |
| Finding moments and cutting clips | No model. ffmpeg scene-change scores and audio loudness statistics |
| Memory, playbook, annotations | No model. Local JSON and JSONL files |

No other model, hosted or local, is called at runtime.

## Features

| Feature | How it works | Status |
|---|---|---|
| Sees the game | Pulls the frame at any second and reads it with Muse Spark vision | Live |
| Hears you | Push-to-talk through Muse Voice Transcribe, game vocabulary biased | Live |
| Talks back | Short spoken replies in a teammate's voice | Live |
| Acts through tools | Coach decides when to look, clip, remember or call out; real function calls on the Responses API | Live |
| Finds and cuts highlights | Scene changes and loud moments ranked into clips | Live |
| Remembers the lesson | Match memory that persists across matches | Live |
| Moment timeline | Detected moments on a clickable timeline | Live |
| Live mode | Share your screen; a frame goes to Coach every 4 s and it calls out on its own when something matters | Live |
| Playbook for studios | A studio saves the goal, controls, rules, tips and common mistakes; in New player mode Coach teaches one thing at a time as it comes up | Live |
| Learns from you | Every callout and reply is a record with its frame; thumbs up/down and corrections feed back into Coach's instructions and export as chat-tuning JSONL for Muse open-weight training | Live |
| Safety reports | Coach files a report, with the evidence frame, when it sees cheating or a hack, a game-breaking bug, bullying in chat, or an adult asking a child for personal details (kids audience in the playbook). A person reviews at /admin/incidents; optional webhook alert; Coach never acts on anyone itself | Live |
| Overlay and PC app | Highlight boxes, task list and callouts over the game (/overlay, desktop/ Electron app, OBS source, VR pin); movable panels, H or Ctrl+Shift+O to hide | Live |
| Game brief | The moment Coach names the game it sees, it writes itself a brief from Muse's own knowledge (how it plays, the words players use, modes and levels, rookie mistakes, danger signs), cached per game. set_game tool, src/coach/gamebrief.py | Live |
| Player profile | Coach remembers how you like each game set up (controls, sound, display, play style) plus skill notes on what you do well and where you struggle, and picks up there next time. remember_preference and my_preferences tools, /api/profile | Live |
| Guardrails | Per-session rate limits, a daily token budget from real API usage, a kill switch, and a scope rule that keeps Coach on the game (off-topic redirects are counted). See docs/guardrails.md | Live |
| In-game SDK | Two HTTP calls make Coach part of a game: the game posts player, objective, landmarks and events; Coach returns arrows anchored to landmark ids, routes, callouts and reactions. Unity reference client in sdk/unity, fake game in sdk/python. See docs/game-sdk.md | Live |
| Guide me | Off by default. Turn it on and Coach shows the way: an arrow at the spot, an edge arrow with a direction when it is off screen, numbered waypoints for multi-step routes. The point and route tools are only offered to the model while Guide me is on | Live |
| Meme reactions | Coach flashes a meme card with a sound sting on the overlay when you whiff, ignore a callout, pull off a clutch, or start flirting mid-match. Player settings: on/off, spice, 3D or classic style, and who Coach is (Muse Bot, Coach, Dog). See docs/reactions.md | Live |
| Highlight reel | Clips stitched into a reel with poster frames from Muse Image | On the way |

## What was built during the hackathon

Everything in this repository. Nothing here is pre-existing: the repo was created during the event and every commit is from the building window.

## Build plan (gates)

Each gate ships with tests and must pass before the next one starts.

| Gate | Scope | Status |
|------|-------|--------|
| 0 | Project scaffold, config loading, offline health check, CI | Done |
| 1 | Video ingest: read gameplay footage, sample frames | Done |
| 2 | Clips: detect key moments, cut highlight clips | Done |
| 3 | Voice: speech in (Muse Voice Transcribe), Coach replies (Muse Spark), spoken replies | Done |
| 4 | Agent: Coach as a teammate that acts through tool calls (look, find_moments, cut_clip, remember, recall, callout) | Done |
| 5 | Web app: match player, moment timeline, live tool-call feed, voice in/out, clips, memory | Done |
| 6 | Live mode: screen share, look_now tool, auto callouts | Done |
| 7 | Studio playbook and New player mode (teach ticks) | Done |
| 8 | Gameplay data: annotation records, ratings, learned examples, training export | Done |
| 9 | Highlight reel with Muse Image, hosted demo | Planned |
| 10 | Meme reactions: react tool, reaction cards and stings, player settings, avatars | Done |
| 11 | Guide me: point and route tools gated by player consent, arrows and routes on the overlay | Done |
| 13 | Guardrails and player profile: rate limits, daily token budget, kill switch, scope and injection rules, per-game preferences (docs/guardrails.md) | Done |
| 12 | Game SDK: structured game state in, landmark-anchored directives out, event-driven reactions, Unity reference client and fake game (docs/game-sdk.md) | Done (Unity scripts need an in-editor compile) |

## For judges: how to try Coach in 3 minutes

1. **Open the hosted demo** (link in the submission) or run it locally with the Quick start below.
2. Click **Use the sample match**. The timeline shows the moments Coach detected (blue = scene change, amber = loud moment).
3. Click **Clip the biggest moment**. Watch the right panel: Coach calls `find_moments`, `cut_clip` and `remember` itself. Each step card shows the real tool call and result. The clip appears under Highlights, the note under Match memory.
4. Click **What's happening at 15 seconds?** Coach calls `look`, sends the frame to Muse Spark, and describes it.
5. **Go live: share my game.** The first time, a consent sheet asks you to agree to the pilot terms (Coach sees the shared screen and hears the mic). Share any window (a gameplay video in another tab works). Every 20 s Coach looks and calls out only if something matters, points at the spot with a highlight box, and keeps a task list. Ask "What should I do next?" any time. Click **Overlay** for the transparent page you can put over a game or into OBS, or **Corner mode** for a small always-on-top Coach window; the `desktop/` app floats the overlay over any game (docs/pc-overlay.md, docs/vr.md). Playing a standalone Quest game? Pair Bluetooth earbuds to the PC and wear one: the game and your teammates in one ear, Coach in the other (docs/vr.md, Part 2).
6. **Studio playbook.** Click **Fill a sample**, **Save playbook**, turn on **New player mode**, then go live. Coach teaches from the playbook as things come up.
7. **Rate anything** with the thumbs. Thumbs down opens a correction box; the next reply already uses it. **Export training set** writes chat-tuning JSONL.
8. Hold the **mic** to talk instead of typing (Muse Voice Transcribe).
9. **Safety.** Set the playbook audience to kids and go live on a game with chat: if an adult asks the child for personal details, Coach files a report with the evidence frame at `/admin/incidents` and tells the child to get a parent. Coach never acts against anyone itself.

Meta models used: Muse Spark 1.3 (reasoning, tool calling, vision), Muse Voice Transcribe 1.0 (speech to text), both through the Meta Model API Responses endpoint. The hosted demo needs no login.

## Gates

No GitHub Actions. Two scripts carry the checks, and their exit codes are the verdict:

- `scripts/pre-merge.sh` before every merge to main: the full test suite with ffmpeg required and no skips allowed, then `scripts/check-no-dashes.sh`.
- `scripts/predeploy.sh` runs inside the built image before Render switches traffic (`preDeployCommand` in render.yaml): imports, health report, ffmpeg, no em dashes.

## Deploy (Render)

`render.yaml` and the `Dockerfile` are included. Connect the repo on Render, set `META_API_KEY` in the dashboard (never in the repo), and deploy. Data persists on the mounted `/data` disk.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env           # then fill in your keys
python -m coach health   # shows which model providers are configured
python -m coach ingest match.mp4 --out frames/ --every 2   # sample frames
python -m coach clips match.mp4 --out highlights/ --top 5   # cut highlight clips
python -m coach transcribe callout.wav --keyword Coach       # speech to text
python -m coach coach "they're flanking left" --speak          # Coach replies, out loud
python -m coach play "clip the best moment" --video match.mp4  # Coach acts through tools
python scripts/live_check.py                                       # live smoke test (uses credits)

# Web app
pip install -e ".[web]"
uvicorn web.app:app --reload          # then open http://127.0.0.1:8000
pytest
```

The health check never calls the network and never prints key values.

Ingest needs `ffmpeg` and `ffprobe` on your PATH (or set `FFMPEG_BIN` / `FFPROBE_BIN`). It accepts .mp4, .mkv, .mov and .webm up to 3 hours, samples one frame every N seconds (spread evenly when a cap is hit), and writes JPEGs plus `manifest.json`.

Clips finds key moments from two signals, scene cuts in the picture and loudness peaks in the audio, merges nearby signals (a cut and a shout together score higher), keeps the top N, pads each into a window that never overlaps another, and writes `clip_NN.mp4` files plus `highlights.json`.

Voice converts any audio or video to the WAV the API accepts (mono, 16-bit, 24 kHz, checked before upload), transcribes it with Muse Voice Transcribe (game vocabulary via `--keyword`), and Coach answers through Muse Spark with reasoning effort set low for fast replies. Spoken output uses the local OS voice (Windows SAPI, macOS say, espeak) since the Meta API has no text-to-speech. See `docs/meta-api.md` for the verified API details.

The agent runs on the Responses API with function tools. Coach can `look` at any second of the match (frame sent to Muse Spark as an image), `find_moments` and `cut_clip` highlights, `remember` and `recall` notes across matches, and `callout` to the player. Tool arguments are validated before use, a bad call returns an error string to the model instead of crashing, parallel calls are supported, and each player turn is capped at 8 model rounds.

## Models

- Meta Model API (Muse Spark and the other Muse models), via `META_API_KEY` and `META_BASE_URL`
- Muse Spark Open (open weights) on Baseten, via `BASETEN_API_KEY`

## Data

Coach writes its data (matches, clips, memory, playbook, annotation records and frames, training exports) under `coach_data/`, which is git-ignored. The repo holds code only.

## License

MIT
