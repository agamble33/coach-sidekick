# Coach Game SDK (Gate 12): a true in-game coach

Any game can make Coach part of itself in an afternoon. The game tells Coach what it knows (player,
objective, landmarks, events) and draws what Coach decides (arrows at real world positions, routes,
callouts, meme reactions). Coach's web overlay keeps working unchanged; the game is just a second
client of the same live session.

## Contract

Two HTTP calls. Everything else is optional.

**Game to Coach: `POST /api/game/{live_id}/state`** (header `X-Coach-Consent: <consent_id>`), once a
second is plenty:

```json
{"game": "I'm A Zombie",
 "player": {"pos": [12.4, 0, -3.1], "yaw": 95, "hp": 42, "state": "exploring"},
 "objective": "Find the east gate key",
 "landmarks": [
   {"id": "east_gate", "label": "East gate", "pos": [40, 0, -8], "visible": false, "dir": "right"},
   {"id": "fountain",  "label": "Fountain",  "pos": [20, 0, -5], "visible": true,  "screen": [0.52, 0.55]}],
 "events": [{"type": "fell", "detail": "missed the ledge"}]}
```

- `landmarks[].screen` is the landmark's position as fractions of the screen (x right, y down) when it
  is visible; `dir` (left, right, up, down, behind, ahead) when it is not. Coach uses these to place
  arrows on the web overlay. The game uses the id to draw its own arrow in the world.
- `events[].type` that equals a reaction trigger (`missed_jump`, `dumb_play`, `ignored_callout`,
  `whiff`, `near_death`, `clutch`, `rizz_detected`, `slow_reaction`) or an alias (`fell`, `died`,
  `idle`, `kill_streak`, `boss_down`, ...) fires the meme reaction immediately, no model call.
- Response: `{"ok": true, "posts": n, "landmarks": n, "reactions_fired": [...], "fresh": true}`.

**Coach to game: `GET /api/game/{live_id}/directives`**, poll every 0.5 to 1 s:

```json
{"overlay": {"callout": "Go right, the gate is past the fountain.", "callout_at": 1793641000.1,
             "pointers": [{"x": 0.94, "y": 0.5, "label": "East gate", "direction": "right", "landmark": "east_gate", "created": ..., "until": ...}],
             "route": [{"n": 1, "landmark": "fountain", "label": "Fountain", ...}, {"n": 2, "landmark": "east_gate", ...}],
             "reaction": {"trigger": "missed_jump", "line": "Gravity 1, you 0.", "image": "/reactions/images/cackle.png", "sound": "/reactions/sounds/womp.mp3", "ts": ...},
             "tasks": [{"text": "Grab the key", "done": false}], "guide": true, "hidden": false, "avatar_url": "/reactions/avatars/muse_bot.png"},
 "game": {"...what Coach currently holds about the game..."},
 "speak": "Go right, the gate is past the fountain.", "speak_at": 1793641000.1}
```

Dedupe on `callout_at`, `created` and `ts`. `pointers[].landmark` and `route[].landmark` are the ids
you sent, so you resolve them to transforms and draw the arrow where the thing really is. In VR this
is the only way to get an aligned pointer.

What changes on Coach's side when a game is connected: the model gets a `GAME STATE` block (facts
only, nothing inferred) in its instructions on every turn and tick, so it reasons on positions and
events before spending a vision call. `point` and `route` accept a `landmark` id. Guide me still
gates pointing: the player turns it on in the Coach page.

## Unity (reference client)

`sdk/unity/CoachClient.cs` and `sdk/unity/CoachArrow.cs`. No packages beyond UnityEngine.

1. Copy both scripts into `Assets/Coach/`.
2. Empty GameObject `Coach`, add `CoachClient`. Fill **Base Url**, **Live Id**, **Consent Id** from
   the Coach page (Live card, **Game SDK** box, after you go live). Set **Player** and **Player
   Camera**. Add your landmarks (id, label, transform).
3. Add a small arrow mesh under the player with `CoachArrow` (set **Follow** to the player).
   Wire `CoachClient.OnPoint` to `CoachArrow.Show` and `OnRoute` to `CoachArrow.ShowRoute`.
4. Wire `OnCallout` to your TTS or an in-world speech bubble, `OnReaction` to a UI image + audio
   source (the image URL is absolute), `OnTasks` to a HUD list.
5. Call `ReportEvent("fell")` (or any trigger) from your gameplay code.
6. Press Play. `Connected` turns true after the first post; `LastError` says why if not.

Unreal uses the same two calls (HTTP module or a Blueprint HTTP plugin).

## Try it without an engine

`sdk/python/fake_game.py` walks a player past three landmarks and emits events:

```
python sdk/python/fake_game.py --base http://127.0.0.1:8000 --live LIVE_ID --consent CONSENT_ID
```

Open the overlay with Guide me on; arrows anchor on landmarks, reactions fire from events.

## Scope and rules

SDK, Unity scripts and tests are new work for the hackathon. A game integrated with it is a host,
not part of the submission; the demo shows Coach's parts. The Unity scripts were written outside
Unity (no compiler in the build sandbox) and must be compiled in a Unity project before the video.
