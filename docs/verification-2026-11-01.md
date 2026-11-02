# Coach verification, 2026-11-01

Every feature was exercised against the running server (uvicorn on 127.0.0.1:8000, real Meta
Model API calls, about 35k input tokens for the full pass), not only through the unit suite.
Script: a local regrade runner that creates a consent, drives each endpoint and reads the
overlay state. Unit suite: 167 tests, 0 failures. Grades: A = exercised end to end and the
result matched the claim; B = covered by tests only; U = not verified, with the reason.

## Results

| Feature | Grade | Evidence |
|---|---|---|
| Consent gate | A | consent recorded 200; /api/live/start without a consent id 403; terms page 200; record on disk |
| Health | A | ok true, ffmpeg true, Meta API configured |
| Hears you (transcribe) | A | a Windows SAPI clip of "Coach, what should I do next? Push left or hold the high ground?" came back transcribed word for word (audio_ms 5680). Found and fixed: every .wav upload failed with 400 because the converter overwrote its own input |
| Live mode (session, frames) | A | live session created, a 39.8 KB frame from a shared Horizon window accepted |
| Sees the game (live) | A | watch tick called look_now and answered "quiet" on a static frame |
| Acts through tools | A | a pointed question produced look_now, highlight, callout, set_tasks in one turn |
| Overlay: highlight | A | box "Roof edge" at (0.40, 0.40) still on the overlay with 10 s left after the turn. Found and fixed: boxes expired before the turn ended; floor 8 s and the clock now restarts at turn end |
| Overlay: tasks | A | three tasks set by Coach, read back from /api/overlay |
| Overlay: callout banner | A | callout text mirrored to the overlay |
| Overlay on auto ticks | A (tools) / U (behaviour) | Found and fixed: the watch tick could not use highlight or set_tasks at all. On a static test frame Coach stayed quiet, which is the designed behaviour; a real moving game is needed to see it point on its own |
| Overlay layout and hide | A | layout tasks tr, callout bottom, badge br applied on the page (bounding boxes checked); hidden true made every panel invisible; both read back from the API |
| PC overlay app | A | Electron 45.2.1 window over the whole 1920x1080 desktop at 125 percent scaling, transparent, click-through, above the taskbar; DPI-aware screen capture shows the task list top-right, badge bottom-right, callout bottom and both highlight boxes exactly where the layout put them |
| Playbook for studios | A | saved "Regrade Arena", read back, teach tick ran look_now with the playbook loaded |
| Moment timeline | A | sample match: 2 moments (6.0 to 14.0 peak 10.0; 19.9 to 27.9 peak 23.9) |
| Sees the game (match video) | A | "What's happening at 15 seconds?" called look and described the colour bars |
| Finds and cuts highlights | A | find_moments then cut_clip; clip biggestmoment_0019.9-0027.9.mp4 served with 200 |
| Remembers the lesson | A | remember stored a note (memory count 2), recall read it back in the next turn |
| Learns from you | A | a real record labelled up; stats labeled 2; JSONL export 29 lines |
| Talks back (voice) | A | spoken callout heard during the live session earlier today; voice on, 22 browser voices |
| Live stop | A | overlay returns 404 after stop |
| Corner mode | U | needs a real click in Chrome (document picture-in-picture requires user activation and is blocked while the share picker is open). Code in, unit-level only |
| Highlight reel | not built | README marks it on the way |

## Fixes made during this pass (each with a test that fails on the old code)

1. WAV uploads to /api/transcribe (test_transcribe_accepts_wav_upload).
2. Highlight expiry restarts at turn end; 8 s floor (test_highlight_clock_restarts_when_turn_ends).
3. LIVE_TICK_TOOLS includes highlight, set_tasks, task_done (test_agent tick assertions).
4. Overlay layout and hidden flag with /api/overlay/{id}/settings (test_overlay_settings_layout_and_hidden).

## Not verified

- Corner mode on a real click.
- Coach pointing on its own during a live, moving game (only a static frame was available).
- The PC app on a GPU that needs COACH_OVERLAY_NO_GPU=1; the tray menu and link window visually.
- Latency from moment to spoken callout (not measured).
