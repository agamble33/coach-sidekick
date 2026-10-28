# Muse Replay: Coach, an AI co-op teammate

Coach joins your game as a co-op teammate. It watches through video, talks through voice, and acts through tool calls. It also remembers your last match and can cut highlight reels.

Built for the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026) on Meta's Muse models.

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
| 4 | Agent: Coach as a teammate that acts through tool calls | Planned |
| 5 | Memory and highlight reels (Muse Image) | Planned |

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
python scripts/live_check.py                                       # live smoke test (uses credits)
pytest
```

The health check never calls the network and never prints key values.

Ingest needs `ffmpeg` and `ffprobe` on your PATH (or set `FFMPEG_BIN` / `FFPROBE_BIN`). It accepts .mp4, .mkv, .mov and .webm up to 3 hours, samples one frame every N seconds (spread evenly when a cap is hit), and writes JPEGs plus `manifest.json`.

Clips finds key moments from two signals, scene cuts in the picture and loudness peaks in the audio, merges nearby signals (a cut and a shout together score higher), keeps the top N, pads each into a window that never overlaps another, and writes `clip_NN.mp4` files plus `highlights.json`.

Voice converts any audio or video to the WAV the API accepts (mono, 16-bit, 24 kHz, checked before upload), transcribes it with Muse Voice Transcribe (game vocabulary via `--keyword`), and Coach answers through Muse Spark with reasoning effort set low for fast replies. Spoken output uses the local OS voice (Windows SAPI, macOS say, espeak) since the Meta API has no text-to-speech. See `docs/meta-api.md` for the verified API details.

## Models

- Meta Model API (Muse Spark and the other Muse models), via `META_API_KEY` and `META_BASE_URL`
- Muse Spark Open (open weights) on Baseten, via `BASETEN_API_KEY`

## License

MIT
