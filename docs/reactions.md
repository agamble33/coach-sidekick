# Meme reactions (Gate 10)

Coach flashes a meme card and plays a sound sting on the overlay when the player has a moment:
a missed jump, a dumb play, an ignored callout, a whiff, a near-death, a clutch, flirting mid-match.

## For players

1. Go live (share your screen) and open the **Overlay** (or add it to OBS as a browser source).
2. In the Live card, the **Meme reactions** row:
   - **Meme reactions** checkbox: on or off.
   - **Spice**: `mild` is the normal set; `unhinged` adds the wilder cards.
   - **Style**: `3D` rendered cards, or `classic` for the original meme look.
   - **Coach is**: who Coach looks like on the badge and cards: Muse Bot (default), Coach, or Dog.
   - **Test reaction**: fires one so you can see and hear it.
3. Sounds play on the overlay page. Browsers mute a page until you click it once; if a sting was
   blocked you'll see a "Click once for meme sounds" chip on the overlay. OBS browser sources are never muted.

Settings stick per browser and are re-sent each time you go live.

## How it works

- `src/coach/reactions/engine.py`: `ReactionEngine` maps a trigger to a card + sting + spoken line,
  with an 8 s per-trigger cooldown and a 3 s global cooldown. `spice` gates which triggers can fire
  (`off` disables everything). `pack` picks the image set (`classic` falls back to `3d` per trigger).
  `avatar` is purely cosmetic.
- `react` is a normal Coach tool (see `tools.py`); the agent decides when a moment earns one. It is in
  `LIVE_TICK_TOOLS`, and the watch prompt tells Coach when to use it. A suppressed reaction returns
  `no reaction (reason)`, never an error.
- The overlay snapshot carries the last `reaction` (keyed by `ts`) and the avatar; `overlay.html` shows
  each reaction once and plays its sting once.
- Endpoints: `POST /api/overlay/{id}/settings` (`spice`, `pack`, `avatar`), `POST /api/overlay/{id}/react`
  (test button), `GET /api/reactions` (catalog). Assets are served at `/reactions/`.

## Assets

Every card is a 3D render generated for this project or a polished copy of a meme Tony supplied
(animals, an emoji, his own selfie); no owned characters, no real strangers' faces. Every sound is
synthesized. Avatars: `assets/avatars/`. Raw sources and regen scripts: `scripts/reactions/`.

## Add a reaction

Drop a 512x512 PNG in `assets/images/` (and optionally `assets/images/classic/`), an mp3 in
`assets/sounds/`, and an entry in `reactions.json`. `tests/test_reactions.py` fails if a file is missing.
Assets ship with the package via `[tool.setuptools.package-data]` in `pyproject.toml`; keep new
extensions listed there.
