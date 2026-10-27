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
| 1 | Video ingest: read gameplay footage, sample frames | Planned |
| 2 | Clips: detect key moments, cut highlight clips | Planned |
| 3 | Voice: speech in and spoken replies | Planned |
| 4 | Agent: Coach as a teammate that acts through tool calls | Planned |
| 5 | Memory and highlight reels (Muse Image) | Planned |

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env           # then fill in your keys
python -m muse_replay health   # shows which model providers are configured
pytest
```

The health check never calls the network and never prints key values.

## Models

- Meta Model API (Muse Spark and the other Muse models), via `META_API_KEY` and `META_BASE_URL`
- Muse Spark Open (open weights) on Baseten, via `BASETEN_API_KEY`

## License

MIT
