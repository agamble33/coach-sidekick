# Submission draft: Coach

For the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026). Paste into the submission
form; trim to the form's limits. Replace the bracketed items before submitting.

## Title

Coach: an in-game AI sidekick that watches, talks and teaches while you play

## One line

Coach plays with you, not for you: live callouts, pointers on the screen, a task list, highlight
clips, match memory and a studio playbook that teaches new players inside the game, all through
Meta's Muse Spark and Muse Voice Transcribe.

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

## How we built it

Python (FastAPI, ffmpeg) with one agent loop on the Meta Model API Responses endpoint: Muse Spark
1.3 for reasoning, tool calls and vision (image input on the same call), Muse Voice Transcribe 1.0
for speech. Eleven tools: look, look_now, find_moments, cut_clip, remember, recall, callout,
highlight, set_tasks, task_done, report_concern. Speech out is the browser's own voice (the API has
no text to speech). The web app is one HTML file; the PC overlay is a small Electron window;
everything ships in one Docker image for Render. 172 tests, two gate scripts, no GitHub Actions.

## What we verified

Every feature was exercised against the running server with real Meta calls on Nov 1 (docs/
verification-2026-11-01.md): transcription word for word, live callouts, highlight boxes that
survive the turn, tasks, clips, memory, playbook teaching, labelling and export, and a synthetic
kids-game frame with a grooming attempt in chat that Coach reported on its own while a normal frame
produced nothing.

## Challenges

The highlight box kept expiring before the player could see it, because Coach's own turn (callout,
tasks, reply) outlived the box; the clock now restarts when the turn ends. Every WAV upload failed
because the converter wrote onto its own input. Chrome's screen-share picker blocks new windows,
so Corner mode needs the share to finish first. Windows at 125 percent scaling fooled our first
desktop capture, not the overlay.

## What is next

Android app with screen capture and a floating bubble, studio-preloaded mission lists, a lawyer
pass on the pilot terms, self-serve data deletion, and the highlight reel.

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
