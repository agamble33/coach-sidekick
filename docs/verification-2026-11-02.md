# Coach verification, 2026-11-02 (Gates 10 to 12)

Branches: `gate10-reactions` -> `gate11-guide` -> `gate12-game-sdk` (each on top of the previous;
nothing merged to main yet, nothing pushed). Unit suite on this branch: **214 tests, 0 failures**
(187 core + 27 web), run on Tony's PC in the Cowork workspace.

Grades: A = exercised end to end against the running server (or in a real browser) and the result
matched the claim; B = covered by tests only; U = not verified, with the reason and the command to
verify. Earlier features keep their 2026-11-01 grades (docs/verification-2026-11-01.md) and still
pass their tests; nothing in Gates 10 to 12 changed their code paths except what is listed.

## Gate 10: meme reactions

| Feature | Grade | Evidence |
|---|---|---|
| Reaction engine (triggers, cooldowns, spice, packs, avatars) | A | 22 engine tests; live server fired `missed_jump` from a game event and reported `global cooldown` on the immediate repeat |
| `react` tool for the model | B | tool registered with the engine's schema (enum stays in sync with reactions.json), dispatcher test, annotation kind `react`; the model actually calling it needs the live regrade |
| 9 reaction cards, 3D pack | A | 600 px renders composed to 512 px cards; contact sheet reviewed |
| Classic pack (polished originals) | A | 6 cards built from the supplied screenshots, UI chrome cropped, upscaled and sharpened; fallback to 3D per trigger tested |
| 8 sound stings | A | synthesized, 0.6 to 2.1 s, mp3 + wav; played in a real browser run |
| Overlay card + sting + dismiss | A | rendered in Chromium with the demo page: card shows, image 512 px, sting plays, card dismisses; "click once for meme sounds" chip appears only when autoplay was blocked |
| Player settings (on/off, spice, style, avatar) + Test reaction | A | settings strip rendered; `/settings` round-trips; bad values 400; Test button endpoint fires and reports cooldown |
| Avatars (Muse Bot, Coach, Dog) on badge and card | A | badge shows the avatar image (256 px) in the rendered overlay |
| Assets ship on Render | A | wheel built the way the Dockerfile does; 29 reaction files inside, spot-checked |

## Gate 11: Guide me

| Feature | Grade | Evidence |
|---|---|---|
| `point` and `route` tools, gated by consent | A | 8 tests: refused when off, offered to the model only when on (watch tick and plain turn payloads checked), cap 3 arrows / 6 waypoints, 8 s floor, re-based at turn end |
| Arrows, edge arrows with direction, numbered routes on the overlay | A | rendered in Chromium: 2 arrows (one on-screen, one edge "Key, left"), 3 waypoints, animated route line, no console errors |
| Guide me toggle + Test arrow | A | toggle persists per browser and re-sends on go live; `/point` endpoint refused while off, draws while on, consent-gated |
| Coach pointing on its own from a real frame | U | needs the Meta API: `python scripts/regrade_live.py 8000` on the PC; step 5 asks "where do I go" and the grade line says whether Coach pointed at a landmark |

## Gate 12: Game SDK

| Feature | Grade | Evidence |
|---|---|---|
| `POST /api/game/{id}/state` (player, objective, landmarks, events) | A | live server: 3 landmarks accepted, event `fell` fired the `missed_jump` reaction with no model call, bad body 400/422, consent-gated |
| `GET /api/game/{id}/directives` | A | live server: overlay snapshot + game snapshot + `speak`; 404 after stop |
| GAME STATE in the model's instructions | A (tests) | instructions carry the block only while fresh (< 15 s); stale state drops out |
| `point` / `route` by landmark id | A | on-screen landmark resolves to its screen spot, off-screen to an edge arrow with the game's direction; unknown id is a clear error listing known ids; scripted model called `point(landmark=east_gate)` end to end through the agent loop |
| Fake game client | A | `sdk/python/fake_game.py` projection tested; drove the live server |
| Unity `CoachClient.cs` / `CoachArrow.cs` | U | written without a compiler (none in the sandbox); brace-balanced. Verify: copy into `Assets/Coach/` in the I'm A Zombie project, press Play, `Connected` turns true |
| Game SDK box on the Coach page (copy for Unity) | A (markup) | present and wired; copy uses the clipboard |

## Gaps that remain

1. Model-in-the-loop behaviour for Gates 10 to 12 is unverified from here (network). One command
   on the PC closes it: `python scripts/regrade_live.py 8000`.
2. Unity scripts need a compile in the editor.
3. Overlay JS still has no automated browser test in the suite (manual Chromium renders only).
4. The "Muse Bot" avatar label uses a Meta brand word; one string to rename if staff object.

## Verdict

Gates 10 and 11 are ready to merge. Gate 12 is ready on the Coach side; keep the Unity part out of
the demo unless it compiles and runs on Nov 3.

## Live reactions check, 2026-11-03

`scripts/live_reactions_check.py`: real Coach server (gate13-guardrails), real overlay page in
Chromium, reactions fired through the API and from a game event. **45/45 checks passed**:

- All 9 triggers: correct card (512 px), a line from the trigger's set, the right sting started
  playing (duration and playback position read from the audio element), card tagged with the avatar.
- Cooldown: a repeat inside 8 s is refused with `trigger cooldown`.
- Face changes live: avatar switched Muse Bot -> Coach -> Dog -> Muse Bot; badge image and name
  update within a poll, and the next reaction card carries the new avatar.
- Classic pack shows the polished original horse; rizz falls back to the 3D card.
- Game event `fell` fires `missed_jump` with card and sting, no model call.
- Spice off: nothing fires. No page errors.
- Browser that blocks autoplay: the "Click once for meme sounds" chip appears, and one click plays
  the sting that was blocked.

Not covered: the model choosing to call `react` on its own (needs the Meta API; run
`scripts/regrade_live.py` on the PC).

## Nov 3: real-model audit and speed

- `scripts/muse_audit.py` (run on the PC with the real key): 18/18 Muse-backed features passed, including vision on a frame, highlights, memory, scope rule, live strategy, meme reactions (fail and rizz), on-screen instruction injection ignored, adult-contact report, player profile save and recall, Guide me arrow and route anchored to a game landmark, teach and watch ticks, and Muse Voice Transcribe (1.6 s).
- Finding: turns took 13 to 38 s. `scripts/latency_probe.py` showed the model itself answers a short prompt in about 3 s; requests that continue a server thread with `previous_response_id` took 8 to 12 s each. Switched the agent to local threading (we resend the last six exchanges and this turn's tool calls ourselves). `scripts/speed_check.py`: 4 tool-using turns went from 62.6 s (server threading) to 41.1 s (local), with model rounds at 3 to 4 s instead of 8 to 12 s. `COACH_THREADING=server` restores the old mode.
- UI audit (`ui_audit.py`, Playwright against the stand-in API): 42/42. Found and fixed: the page script was broken by one unescaped quote (every button dead, also on main); Go live was unreachable once a match was loaded; waypoint labels stacked on top of arrow labels.
- Unit tests: 236 pass.
- `scripts/tactic_check.py` (real model): 10 tactic questions across Call of Duty, Fortnite, Roblox (Blox Fruits, Adopt Me), Minecraft, Rocket League and Valorant. 9/10 matched the keyword grader and the tenth (Rocket League rotation) was correct on reading. Muse knows popular games out of the box; the playbook and SDK cover new and unreleased games.
- Added skill notes (profile category `skills`) so Coach records what a player does well or struggles with and coaches toward it next session, and a system line to ask one short question instead of guessing. Tests added.
- Hands-free "Coach, ..." (browser speech recognition for the wake word, zero tokens), voice commands stop talking / talk to me, player-readable tool lines with a Details toggle, set_game so Coach names the game it sees ("Playing: X" badge), one Coach turn at a time per session (409; the page waits and retries a player's question, drops a tick), phone layout fixed. Browser checks: hands-free 12/12, UI audit 42/42.
