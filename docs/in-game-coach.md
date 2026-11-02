# In-game Coach: architecture review, gaps, and the path to a true in-game sidekick

Written 2026-11-02, two days before the Nov 4, 9 PM ET deadline. Indie track is judged on
"creativity, technical ambition, and whether it works"; the 3-minute demo video is the primary
judging artifact; the project must genuinely use the Meta Model API; new work only.

## 1. Where Coach lives today, per platform

| Platform | Coach sees | Coach draws | Coach talks | Verdict |
|---|---|---|---|---|
| Flat PC game, windowed or borderless | Screen share, frame every 4 s to Muse Spark vision | Overlay page over the game (browser window, OBS source, or the Electron PC app), click-through | Browser voice | Full feature set. Best demo surface today |
| PC VR through Quest Link / Air Link | Share the game or SteamVR mirror window | Overlay window pinned into VR with a SteamVR overlay tool (XSOverlay, OVR Toolkit, Desktop+) | PC audio into the headset via Link | Works, but the panel floats beside the game; boxes and arrows are not aligned to the 3D world |
| Standalone Quest game (Horizon Worlds, Quest-native) | Casting to the PC | Nothing. Horizon OS gives third-party apps no cross-app overlay; "system overlay present" in the Meta SDK refers to Meta's own UI, not ours | Only via a voice-call workaround | Watch and talk, cannot draw |
| Quest browser panel in Horizon Home | n/a | The overlay page as a floating 2D panel | Yes | Lobby and between-rounds only; hidden once an immersive app starts |

The honest line for judges: on flat PC and PC VR Coach is in the game today. On standalone Quest it
is beside the game. The only way to be inside a standalone Quest title is to be part of the game
build. That is the Game SDK below, and it is the thing judges will read as a real in-game coach.

## 2. Which games Coach can help right now

- Any flat PC game that runs windowed or borderless: shooters, MOBAs, platformers, strategy, racing.
  Full set: callouts, highlight boxes, Guide me arrows and routes, task list, meme reactions, clips,
  memory, teach mode with a playbook.
- Any PC VR title launched through SteamVR (or with `-vrmode openvr`): a floating Coach panel in
  the headset with everything above, voice included. Spatial pointing is not aligned.
- Any standalone Quest title that allows casting: Coach watches and talks (voice-call route). No
  drawing. Horizon Worlds included.
- Any game a studio writes a playbook for: Coach teaches new players one thing at a time.
- Kids' titles: the safety-report path and the kids-audience playbook flag already exist.

Strongest demo candidates with what exists: a flat PC game with clear landmarks (a door, a key, a
boss) so Guide me arrows read instantly on video, plus a Quest Link session to show the panel in VR.

## 3. Architecture gaps found in this review

| # | Gap | Impact | Fix | Status |
|---|---|---|---|---|
| 1 | Perception is vision-only: every "where to go" is Muse Spark reading a 768 px frame taken up to 4 s ago | Arrows can land a few hundred pixels off; latency 4 to 8 s; costs a vision call per tick | Let the game send structured state (player position, objectives, landmarks) so Coach reasons on facts and only uses vision for what the game does not expose | Gate 12 (Game SDK), plan below |
| 2 | Targets are screen fractions (x, y of the shared frame) | Meaningless in VR; breaks when the pinned panel is not the same aspect as the capture | World-anchored targets: the game resolves a landmark id to a 3D position and draws the arrow itself | Gate 12 |
| 3 | Coach has no landmark vocabulary | It guesses labels; cannot say "the fountain" unless it sees it | Playbook gains a `landmarks` list (name, hint); the SDK sends live landmark positions | Gate 12 (playbook part is small) |
| 4 | Guide tools were always available to the model | Coach could point without consent, and judges flagged autonomy as a risk area | Guide me is off by default; `point` and `route` are only offered to the model while it is on, and refuse if called | Done, Gate 11 |
| 5 | Reaction assets were not shipped by the Docker build | Every card would 404 on Render | `package-data` in pyproject; verified by building the wheel | Done, Gate 10 |
| 6 | Browser autoplay mutes stings until a click | First reaction silent | "Click once for meme sounds" chip only when a sting was blocked | Done, Gate 10 |
| 7 | Overlay settings (spice, pack, avatar, guide, layout) live in the live Session | Lost on server restart | Client stores them per browser and re-sends on every go-live; acceptable for the demo | Accepted |
| 8 | Overlay JS has markup-level tests only in pytest | A rendering regression would not fail CI | Playwright render check done manually for Gates 10 and 11 (Chromium cannot be installed in the sandbox); add a Playwright test on Windows CI after the deadline | Open |
| 9 | Standalone Quest: no voice path without a call-app workaround | Weakest platform story | Game SDK gives the game Coach's lines as text so the game can speak them with its own TTS or show them in-world | Gate 12 |
| 10 | Watch tick is 4 s; Guide me wants faster feedback when the player moves | Arrow stays put while the player turns | With SDK state, the game re-projects the arrow every frame itself; no round trip needed | Gate 12 |

## 4. Gate 12: the Game SDK (the real in-game coach)

What it is: a small HTTP contract any engine can speak, plus a reference C# client for Unity.
Coach's existing tools and overlay keep working unchanged; the game becomes another client of the
same live session.

Game to Coach (`POST /api/game/{live_id}/state`, every 0.5 to 2 s or on events):
```json
{"player": {"pos": [12.4, 0, -3.1], "yaw": 95, "hp": 42, "state": "exploring"},
 "objective": "Find the east gate key",
 "landmarks": [{"id": "east_gate", "label": "East gate", "pos": [40, 0, -8], "visible": false, "dir": "right"},
               {"id": "fountain", "label": "Fountain", "pos": [20, 0, -5], "visible": true, "screen": [0.52, 0.55]}],
 "events": [{"t": 1793641000.2, "type": "missed_jump"}, {"t": 1793641003.9, "type": "took_damage", "amount": 18}]}
```
Coach to game (`GET /api/game/{live_id}/directives` or the existing `/api/overlay/{live_id}`):
the same snapshot the overlay already reads: `callout`, `tasks`, `pointers`, `route`, `reaction`,
plus `landmark` ids on pointers and route steps when Coach used one. The game resolves the id to a
world position and draws its own arrow, path, or NPC gesture; it speaks `callout` with its own TTS.

Coach side changes:
- `Session.game_state` (latest payload, kept small) injected into the watch tick as text, so Coach
  reasons on facts before it spends a vision call. Events like `missed_jump` map straight to
  `react` triggers without vision.
- `point` and `route` accept an optional `landmark` id; when the game reported that landmark, the
  server fills `x, y` from `screen` or sets `direction` from `dir`, so one tool serves the overlay
  and the game.
- Playbook `landmarks` list so the names are consistent across studio, Coach and game.

Game side: `CoachClient.cs` (one script, no dependencies): posts state, polls directives, exposes
`OnCallout`, `OnPoint(landmarkId)`, `OnRoute`, `OnReaction`. A `CoachArrow` prefab points at the
resolved transform. Reference integration target: the Unity project in `Code/I-m-A-Zombie`, which
Tony owns, so no third-party IP in the demo. Unreal uses the same HTTP contract (Blueprint or C++).

Effort: Coach side plus a fake-game Python test client, half a day. Unity script and a minimal
scene, half a day, tested on Tony's machine (Unity is not available in the sandbox). Demo video
then shows Coach as an in-world arrow and voice inside a running Unity game, with the overlay and
VR panel as the "any game" fallback.

Rules check: the SDK, the Unity script and the integration are new work; the game itself is not.
The demo should show Coach's parts, not the game as a submission. Say so in the video.

## 5. Two-day plan

| When | What | Done when |
|---|---|---|
| Nov 2 | Gate 11 Guide me (this branch) | 205 tests green, arrows and routes render |
| Nov 2 evening | Gate 12 Coach side: state endpoint, directives, landmark-aware point/route, react from events, playbook landmarks, fake-game test | tests green |
| Nov 3 | `CoachClient.cs` + arrow prefab into I'm A Zombie; record the Unity segment | arrow follows a landmark in Play mode |
| Nov 3 evening | Merge gate10 and gate11 (and 12) to main, push, Render redeploy, re-run the readiness audit | live site shows reactions and Guide me |
| Nov 4 | 3-minute video: live PC game with Guide me, Quest Link panel, Unity in-world coach, meme reaction. Submit before 9 PM ET | submitted |

If Nov 3 slips, cut the Unity segment and keep the Coach-side SDK with the fake-game test: the
contract is still demoable in the video as a terminal client driving arrows on the overlay.
