# Coach PC overlay (desktop app)

A small Electron app in `desktop/` that puts Coach's overlay page (highlight boxes, task list and
the latest callout) over any game on your primary display. The window is transparent, has no
frame, stays on top of everything, is click-through (your mouse goes to the game), and does not
appear in the taskbar. A tray icon controls it.

## Install

Requirements: Windows 10 or 11 (also runs on macOS and Linux but only Windows is tested), Node.js
20 or newer, and Coach running locally (`uvicorn web.app:app` from the repo root, see the README).

```powershell
cd desktop
npm install        # installs Electron 45.2.1, pinned in package.json
npm start
```

The first `npm install` downloads the Electron binary (about 100 MB). No bundling, no installer, no
code signing: `npm start` runs it from source.

## Run

1. Start Coach and go live (**Go live: share my game**). Copy the **Overlay** link Coach shows
   (`http://127.0.0.1:8000/overlay?live=...`).
2. `npm start` in `desktop/`. A Coach icon appears in the system tray. On the first run no link is
   stored, so the app shows the **demo layout** (`/overlay?demo=1`): a sample callout, two
   highlight boxes and a task list, so you can see where things land.
3. Right-click the tray icon, choose **Set overlay link...**, paste the link, press **Save and
   show**. The overlay switches to your live session. The link is stored in
   `%APPDATA%\coach-overlay\overlay-settings.json` and reused next time.
4. Play. Coach's boxes and callouts draw over the game.

The app appends `pc=1` to the overlay URL so the page can adapt to the desktop app later.

### Tray menu

| Item | What it does |
|---|---|
| Set overlay link... | Small window to paste the Overlay link (or **Use demo** to clear it) |
| Show demo layout | Clears the stored link and shows the demo page |
| Show / Hide overlay (Ctrl+Shift+O) | Toggles the overlay window |
| Open Coach | Opens `http://127.0.0.1:8000` in your browser |
| Reload overlay | Reloads the page (after the server restarts, for example) |
| Quit | Exits the app |

Double-clicking the tray icon also toggles the overlay.

### Ctrl+Shift+O

A global shortcut, registered when the app starts, that hides or shows the overlay from inside any
game without alt-tabbing. If another program already owns Ctrl+Shift+O the log says
`FAILED to register`; close that program or use the tray menu.

### Flags (environment variables)

| Variable | Effect |
|---|---|
| `COACH_URL` | Base URL of Coach if not `http://127.0.0.1:8000` (used for the demo page and Open Coach) |
| `COACH_OVERLAY_NO_GPU=1` | Disables hardware acceleration. Use it if the overlay shows an opaque black or white rectangle instead of a transparent one. Transparent windows on some Windows GPUs and drivers (and under Remote Desktop) fail to composite with the GPU on. The page still animates fine without it. |
| `COACH_OVERLAY_LOG=1` | Logs each URL load |
| `COACH_OVERLAY_SELFTEST=1` | Runs a scripted self-test (toggle twice, save a link, restore, quit) and prints each step. Used for verification on machines without screen capture. |

Example: `$env:COACH_OVERLAY_NO_GPU="1"; npm start`

### How the window is set up

`main.js` creates one `BrowserWindow` with `transparent: true`, `frame: false`,
`alwaysOnTop: true` at level `screen-saver`, `skipTaskbar: true`, `hasShadow: false`,
`focusable: false`, bounds copied from `screen.getPrimaryDisplay().bounds`, and
`setIgnoreMouseEvents(true, { forward: true })` so clicks pass through. Windows clamps a new
window to the work area (screen minus taskbar), so the bounds are re-applied once the window is
shown; the log line `overlay shown` prints the final bounds next to the display bounds so you can
check they match. The window follows display changes (`display-metrics-changed`).

## Limitation: exclusive full-screen games

The overlay is a normal top-most window. A game running in **exclusive full-screen** mode owns the
display and Windows does not composite other windows over it, so the overlay disappears (or the
game flickers to the desktop when it shows). Set the game's display mode to **borderless window**
(sometimes called "windowed fullscreen"); it looks the same and the overlay draws over it. There is
no workaround for true exclusive full screen short of injecting into the game, which Coach does
not do.

Related: some anti-cheat systems flag unknown overlays. Coach's window is a plain Electron window
and does not touch the game process, but if your game's anti-cheat complains, use the OBS route
below instead.

## Alternative: OBS browser source

If you record or stream with OBS, you do not need the desktop app:

1. In OBS add a **Browser** source.
2. URL: the Overlay link (`http://127.0.0.1:8000/overlay?live=...`), or `/overlay?demo=1` to test.
3. Set width and height to the same size as your game capture (for example 1920 x 1080) so the
   highlight boxes line up, and place the source directly over the game capture.
4. Leave the custom CSS as the default transparent body. The page has a transparent background.

This draws Coach into the recording and the stream, but not onto your own screen.

## Matching the boxes to the game

Highlight boxes are fractions of the frame Coach saw. They land in the right place when the overlay
covers exactly the area you shared. Share the game window (not the whole desktop) and run the game
borderless on the primary display, or in OBS size the browser source to the game capture.

## Troubleshooting

- Nothing shows: check the tray icon and press Ctrl+Shift+O. The overlay is click-through, so you
  cannot find it with the mouse.
- "Coach is not reachable": start Coach, then **Reload overlay** from the tray.
- "Live session ended": go live again in Coach and set the new link.
- Black rectangle: run with `COACH_OVERLAY_NO_GPU=1`.
- Second instance: the app is single-instance; starting it again just shows the existing overlay.
