# Coach, by Muse Replay

**An in-game AI sidekick.** Coach plays with you, not for you: live strategy while you play, a guide that teaches new players by playing alongside them, and a teammate that remembers what happened last match. It sees the game, hears you, talks back, and acts through tool calls.

- **For players:** a teammate on voice chat that watches your screen, calls out what matters, and clips the plays worth keeping.
- **For studios:** drop in a playbook and Coach onboards new players inside the game. No training portal, no tutorial level to build.

Built for the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026) on Meta's Muse models through the Meta Model API.

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
| Live mode | Screen share so Coach watches the match as it happens | On the way |
| Playbook for studios | Rules, controls and goals that Coach teaches new players while they play | On the way |
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
| 6 | Highlight reels with Muse Image, hosted demo | Planned |

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env           # then fill in your keys
python -m muse_replay health   # shows which model providers are configured
python -m muse_replay ingest match.mp4 --out frames/ --every 2   # sample frames
python -m muse_replay clips match.mp4 --out highlights/ --top 5   # cut highlight clips
python -m muse_replay transcribe callout.wav --keyword Coach       # speech to text
python -m muse_replay coach "they're flanking left" --speak          # Coach replies, out loud
python -m muse_replay play "clip the best moment" --video match.mp4  # Coach acts through tools
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

## License

MIT
