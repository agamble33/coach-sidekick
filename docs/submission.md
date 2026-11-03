# Submission draft: Coach

For the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026). Paste into the submission
form; trim to the form's limits. Replace the bracketed items before submitting.

## Title

Coach: an in-game AI sidekick that watches, talks and teaches while you play

## One line

Coach plays with you, not for you: a hands-free teammate that watches your screen, talks in your
ear, points the way, drops a meme when you whiff, remembers how you play, keeps kids safe in chat,
and gives studios a two-call SDK to bring it inside the game, all on Meta's Muse Spark and Muse
Voice Transcribe.

## What it does

- Sees the game. Share any window; a frame goes to Muse Spark every 4 seconds. Coach calls out only
  when something matters, draws a highlight box on the exact spot, and keeps a short task list on
  screen. Ask it anything by voice (Muse Voice Transcribe) or text.
- Shows up where the player is looking. A transparent overlay page sits over the game, in OBS, or
  in VR through a desktop window pin; a small always-on-top PC app floats it over any game. Panels
  move out of the way of the game's own map and chat, and a Coach key hides everything.
- Cuts the plays worth keeping. Scene cuts and loud moments ranked into clips, on request or on its
  own, with every tool call visible as it happens.
- Remembers. Match memory that carries into the next session ("last time this setup cost us").
- Teaches for studios. A studio saves goal, controls, rules, tips and common mistakes; in New player
  mode Coach teaches one thing at a time, when it comes up, with no tutorial level to build.
- Learns from you. Every callout is a record with its frame; thumbs and corrections feed back into
  Coach's instructions and export as chat-tuning JSONL for Muse open-weight training.
- Keeps players safe. With a kids audience set, Coach reports an adult asking a child for personal
  details, bullying in chat, cheats, hacks and game-breaking bugs, with the evidence frame, to a
  human review page. It never acts against anyone itself.
- Knows the game on its own. The moment Coach recognises the game on screen it writes itself a
  brief from Muse's knowledge: how it plays, the words players use, modes and levels, rookie
  mistakes and danger signs. One call per game, cached. A studio playbook overrides it.
- Hands-free. Say "Coach, where do I go?" and only the question goes to Coach (the wake word is
  caught in the browser, zero tokens). "Coach, stop talking" mutes, "Coach, talk to me" unmutes.
- Guide me. With the player's consent, Coach draws an arrow at the spot, an edge arrow with a
  direction when it is off screen, and numbered waypoints for a route.
- Meme reactions. Whiff a jump, ignore a callout, flirt mid-match or pull off a clutch and Coach
  flashes a meme card with a sound sting on the overlay: a falling scream, bruh, rizz, the vine
  boom. Three spice levels, two art styles, three Coach faces. Off is one checkbox.
- Player profile. Coach remembers how you like each game set up (controls, sound, display, play
  style) and keeps skill notes on what you do well and where you struggle, then coaches toward it.
- In-game SDK. Two HTTP calls make Coach part of a game: the game posts player, objective,
  landmarks and events; Coach returns arrows anchored to landmark ids, routes, callouts and
  reactions. Unity reference client included. This is the path to standalone Quest titles.
- Guardrails. Per-session rate limits, a daily token budget from real API usage, one Coach turn at a
  time, auto callouts only when the screen changed, a kill switch, and a scope rule that keeps Coach
  on the game and treats on-screen text as data, never instructions.

## How we built it

Python (FastAPI, ffmpeg) with one agent loop on the Meta Model API Responses endpoint: Muse Spark
1.3 for reasoning, tool calls and vision (image input on the same call), Muse Voice Transcribe 1.0
for speech. Eighteen tools: look, look_now, find_moments, cut_clip, remember, recall, callout,
highlight, set_tasks, task_done, report_concern, react, point, route, remember_preference,
my_preferences, set_game, plus the game brief writer. Speech out is the browser's own voice (the
API has no text to speech). The web app is one HTML file with a Quest-style dock; the PC overlay is
a small Electron window; everything ships in one Docker image for Render. 250 tests plus browser
audits (42 UI checks, 45 reaction checks, 12 hands-free checks), two gate scripts, no GitHub Actions.

One finding worth sharing: continuing a server thread with previous_response_id cost 8 to 12 s per
round while a fresh request took about 3 s, so Coach carries the last few exchanges itself. Four
tool-using turns went from 62.6 s to 41.1 s.

## What we verified

Every feature was exercised against the running server with real Meta calls (docs/verification-
2026-11-02.md, Nov 3 section): a Muse audit of 18 features passed 18/18, including the grooming
report, the on-screen prompt injection that Coach ignored, profile save and recall, and an arrow
anchored to a game-reported landmark. A tactic check showed Muse answers real strategy for Call of
Duty, Fortnite, Roblox, Minecraft, Rocket League and Valorant out of the box, and game briefs for
four games came back with the games' own words (Gulag, plates, FC, haki) while a made-up title was
correctly reported unknown.

## Challenges

Standalone Quest does not allow third-party overlays inside games, so on the headset Coach is in
your ear (Bluetooth earbuds paired to the PC) and on screen only through PC VR or the SDK; we say
so plainly. The first daily token cap ran out in nine minutes of a real demo because every auto
callout costs about 11k tokens; now a callout only fires when the screen actually changed. One
unescaped apostrophe silently killed every button on the dashboard, which is why there is now a
test that parses each page's script with node. The highlight box kept expiring before the player
could see it, because Coach's own turn (callout, tasks, reply) outlived the box; the clock now
restarts when the turn ends. Every WAV upload failed
because the converter wrote onto its own input. Chrome's screen-share picker blocks new windows,
so Corner mode needs the share to finish first. Windows at 125 percent scaling fooled our first
desktop capture, not the overlay.

## What is next

Streaming replies (a tool-using turn is about 8 s today), a phone companion page for standalone
Quest players, studio video playbooks through the Files API, game packs built from publishers' own
patch notes, Horizon Worlds NPC persona, an Android app with a floating bubble, a lawyer pass on the
pilot terms, self-serve data deletion, and the highlight reel.

## Links

- Repo: https://github.com/agamble33/coach-sidekick
- Hosted demo: [Render URL, set after the service is created from render.yaml]
- Demo video: [link]
- Try it in 3 minutes: README, "For judges"

## Demo video script (about 2 minutes 30 seconds)

1. (0:00) Title card, one line: "Coach plays with you, not for you."
2. (0:10) Open Coach, click Use the sample match. Timeline fills. Say: "Two signals, scene cuts and
   loud moments, ranked."
3. (0:30) Click Clip the biggest moment. Show the tool cards find_moments, cut_clip, remember.
   Clip appears under Highlights.
4. (0:50) Click What's happening at 15 seconds. Coach calls look and describes the frame. Say:
   "That is Muse Spark reading the frame."
5. (1:05) Go live, share a game window. Consent sheet, agree. Coach watches; a callout plays
   aloud; a highlight box appears on the overlay over the game; the task list updates.
6. (1:35) Hold the mic: "What should I do next?" Coach answers by voice. Say: "Muse Voice
   Transcribe in, browser voice out."
7. (1:50) Studio playbook: Fill a sample, set audience to kids, Save, New player mode on. Show a
   teach callout.
8. (2:05) Safety: show the chat frame with the stranger's question; Coach files the report and
   tells the player to get a parent; open /admin/incidents with the evidence frame. Say: "Coach
   never acts on anyone; a person reviews."
9. (2:20) Thumbs down a callout, type a correction, next reply uses it; Export training set.
10. (2:30) End card: repo, demo link, "Built on the Meta Model API."
