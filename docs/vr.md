# See Coach in VR

A plain-language guide for Meta Quest players. There are two very different cases, and the honest
summary is this:

| You play | Coach can watch | Coach can draw in the headset | Coach can talk in the headset |
|---|---|---|---|
| PC VR through Quest Link or Air Link | Yes (share the game window) | Yes, by pinning the Overlay window into VR with a desktop overlay tool | Yes, PC audio reaches the headset through Link |
| Standalone Quest games (Horizon Worlds, Quest-native titles) | Yes, through casting | No | Only with a workaround |

Everything below assumes Coach is running on your PC at `http://127.0.0.1:8000` (see the README).

## Part 1: PC VR through Quest Link or Air Link

This is the case where the game runs on your PC and the headset shows it through Meta Horizon Link
(cable Link or wireless Air Link). Because the game is a normal PC window, Coach can see it and a
desktop overlay tool can place Coach's window inside your VR view.

### Step 1: run the game through Link

1. Put on the headset, open Horizon Link (cable or Air Link) and reach your PC desktop or SteamVR.
2. Start the game from there.
3. If the game has a display mode setting, choose **borderless** (or **windowed**), not exclusive
   full screen. Exclusive full-screen games own the display and overlay tools cannot capture or
   draw over them reliably. Most VR titles already render in a window; this matters mostly for
   flat games you play on a virtual screen in VR.

### Step 2: go live in Coach, sharing the game window

1. On the PC (in the Link desktop view, or take the headset off for a moment), open
   `http://127.0.0.1:8000` in Chrome or Edge.
2. Click **Go live: share my game** and pick the game window (or the SteamVR mirror window). Coach
   now receives a frame every few seconds and calls out when something matters.
3. After you are live, Coach shows an **Overlay** link (`http://127.0.0.1:8000/overlay?live=...`)
   and a **Corner mode** button. Either one gives you a window to pin into VR:
   - **Overlay link**: a transparent page with Coach's highlight boxes, task list and latest callout.
     Open it in a browser tab, or run the desktop app in `desktop/` (see `docs/pc-overlay.md`),
     which opens it as a transparent full-screen window.
   - **Corner mode**: a small opaque window with Coach's latest words. Easier to pin as a small
     panel next to your hand.

Tip: for the browser version, open the Overlay link in its own window (drag the tab out) so the
overlay tool can capture just that window.

### Step 3: pin that window into VR

You need a SteamVR desktop overlay tool. Three options, all Windows 10 or 11 only:

| Tool | Price | Where |
|---|---|---|
| XSOverlay | $9.99 (Steam, Early Access) | https://store.steampowered.com/app/1173510/XSOverlay/ |
| OVR Toolkit | $10.99 (Steam) | https://store.steampowered.com/app/1068820/OVR_Toolkit/ |
| Desktop+ | Free (GPL-3.0) | https://store.steampowered.com/app/1494460 or https://github.com/elvissteinjr/DesktopPlus |

All three draw over SteamVR games. If your game launches through the Meta (Oculus) runtime instead
of SteamVR, the overlay tool will not appear in it; see the note after the steps.

#### XSOverlay

Steps from the official documentation (https://xsoverlay.vercel.app/gettingstarted and
https://xsoverlay.vercel.app/overlaysettings) and the community wiki
(https://wiki.vrchat.com/wiki/Community:XSOverlay):

1. Start SteamVR, then start XSOverlay from Steam.
2. Look at the back of your left hand. The **wrist overlay** appears there by default.
3. Open **Layout Mode**: press the **Enable/Disable Layout Mode** button on the wrist overlay, or
   use the controller binding (double tap **X** on Touch controllers; double tap left **A** on
   Index).
4. In Layout Mode choose **Add Window** ("Adds a window to the overlay") and pick the Coach window
   (the Overlay page, Corner mode, or the desktop app) from the list of windows and monitors.
5. Point at the new overlay and squeeze the **grip** to grab it; move it where you want it. While
   holding, pull the **trigger** and move your hand forward or back to scale it.
6. In the overlay's settings turn on **Pin** ("Makes the overlay remain active even if Layout Mode
   is disabled"). Optional: **Lock** to stop accidental grabs, **Opacity** to taste, **Auto-Hide**
   to fade it when you are not looking at it.
7. Close Layout Mode. The Coach overlay stays in place while you play.

XSOverlay can also attach a panel to a controller or to the headset (the wiki lists free placement,
controller attachment and headset lock). Attaching Corner mode to your left controller works well
as a glanceable "teammate on your wrist".

#### OVR Toolkit

Steps from the OVR Toolkit wiki (https://wiki.ovrtoolkit.co.uk/#/EditMode and
https://wiki.ovrtoolkit.co.uk/#/WindowSettings) and the Steam page:

1. Launch OVR Toolkit from Steam **as administrator** (the store page says some windows cannot be
   captured otherwise). Start SteamVR.
2. Look at your left wrist. Click the **gear icon** on the wrist overlay to enter **Edit Mode**
   (click it again to leave).
3. Use the wrist overlay's add-window control to spawn a new window overlay and choose the Coach
   window from the desktop window list. (The wiki describes the Edit Mode menus **Window List**,
   **Window Settings** and **Global Settings**; the selected window has a yellow border.)
4. Grab the overlay and place it. In **Window Settings**:
   - **Tracked device** sets what the window follows (stationary in the world, a controller, or
     the headset).
   - **Pin window** keeps it visible when you hide the other windows with the double grip binding
     or the wrist arrow icon.
   - **Opacity (Slider)** and **Hide when not looking at window** are optional.
   - **Chroma key** can make a chosen colour transparent, which is useful if you pin the Overlay
     page from a browser whose background is not already transparent.
5. Leave Edit Mode and play.

#### Desktop+ (free)

Steps from the Desktop+ user guide
(https://github.com/elvissteinjr/DesktopPlus/blob/master/docs/user_guide.md):

1. Start SteamVR, then Desktop+. Open the SteamVR dashboard (system button) and go to the
   **Desktop+** dashboard tab.
2. Click **[+]** in the Overlay Bar and choose the Coach window from the list. Window capture
   uses **Graphics Capture** (Windows 10 1803 or newer); if the window is missing, enable
   **Show Advanced Settings** and check the Capture section of **Overlay Properties**.
3. Hold the trigger, drag the new overlay where you want it, release.
4. Click the overlay's icon in the Overlay Bar, choose **Properties...**, and under Position set
   **Display Mode** to **Only In-Game** so it shows while the game runs and hides when the
   dashboard is open. Set **Origin** to **Play Area** (fixed in the room) or **HMD** (fixed in
   your view).
5. Close the dashboard. Adjust **Opacity** under Appearance if needed.

#### If the overlay does not appear in your game

These tools are SteamVR overlays. A game that launches through the Meta (Oculus) runtime, or
through an OpenXR runtime other than SteamVR's, will not show them. The OVR Toolkit wiki's Oculus
page (https://wiki.ovrtoolkit.co.uk/#/Oculus) lists fixes: launch the game through SteamVR, add
`-vrmode openvr` to most Unity games, or set SteamVR as the OpenXR runtime in SteamVR settings.
The same advice applies to XSOverlay and Desktop+.

### Step 4: hear Coach in the headset

Coach speaks through the PC's browser voice, so it is ordinary PC audio. Horizon Link carries PC
audio to the headset when these are on (Meta help:
https://www.meta.com/help/quest/808853193347112/):

1. Open **Meta Horizon Link** on the PC, click **Devices**, select your headset.
2. Turn on **Hear Computer Audio in VR** and **Hear VR Audio from Computer**.
3. Make sure the PC's audio output is the **Oculus Virtual Audio Device** (taskbar speaker icon),
   or that the browser running Coach is routed to it.

If you use Virtual Desktop or Steam Link instead of Horizon Link, PC audio also streams to the
headset; use that app's audio setting.

### What works and what does not (PC VR)

- Works: Coach sees the game, draws highlight boxes and callouts in a pinned panel, and talks to
  you in the headset. The push-to-talk mic in Coach works through Link's microphone passthrough.
- Partly: highlight boxes are positioned as fractions of the shared frame. They line up with the
  game only if the pinned Overlay window has the same aspect ratio as the window you shared and is
  placed over the game's virtual screen. For true VR titles (no flat screen) treat the overlay as a
  floating panel, not an aligned HUD.
- Does not work: exclusive full-screen flat games (switch to borderless), and games that bypass
  SteamVR (see above).

## Part 2: Standalone Quest games (Horizon Worlds, Quest-native titles)

Here the game runs on the headset itself. The PC is not in the loop, so the overlay tools above
cannot draw anything in the headset. Plainly:

- **Coach can watch** by casting the headset's view to the PC.
- **Coach cannot draw inside the game.** Nothing from the PC can be rendered into a standalone
  immersive app. There is no supported way to inject an overlay into Horizon Worlds or a
  Quest-native title from outside.
- **Coach's voice needs a workaround** (below). Nothing is automatic.

### Let Coach watch: casting

Meta help (https://www.meta.com/help/quest/192719842695017/) gives these headset steps:

1. Press the **Meta** button on the right controller to open the Navigator.
2. Select **Quick controls**, then **Cast**.
3. Select **Web** (or a nearby device from the list), then **Next** and follow the on-screen steps.
4. On the PC open https://www.oculus.com/casting in Chrome or Edge, signed in with the same Meta
   account as the headset, and enter the code if asked. The headset and PC must be on the same
   Wi-Fi network (same band if your router is dual band).

Alternatively cast into the Meta Quest app on the PC if you have it installed; either way you end up
with a window on the PC that shows what you see.

Then in Coach: **Go live: share my game** and pick the casting window (the browser tab or the Quest
app window). Coach now sees your gameplay with the normal casting delay (usually one to a few
seconds) and makes callouts as usual on the PC.

Limits of casting: the cast is a single flat view, lower resolution than the headset, and some
titles block casting or show a blank frame. Casting also costs headset performance.

### Hear Coach while in a standalone game: workarounds

Coach's voice plays on the PC. To get it into your ears while you are in a standalone app:

0. **Bluetooth earbuds paired to the PC (recommended, two minutes).** Pair your earbuds to the
   **PC**, not the headset, and make them the PC's output device. Coach's voice and the meme
   sounds now play in your ears while the Quest runs the game and its own audio comes from the
   headset's speakers. Wear one earbud and leave the other ear open: the game and your
   teammates in party chat in one ear, Coach in the other. Nothing to configure in Coach. This is
   how the demo recording was made.
1. **A call app on the headset.** Start a voice call between the PC and the headset (for example
   Discord or Messenger on the Quest and on the PC) and route the PC's Coach audio into the call's
   microphone input (a virtual audio cable such as VB-Cable, or Windows "Listen to this device").
   The call app keeps running in the background of most standalone games, so you hear Coach. This
   is the only option that works inside an immersive app, and it is fiddly to set up.
2. **The Quest browser kept open to Coach in Horizon Home.** Open `http://<your PC's LAN IP>:8000`
   in the headset's browser as a floating panel (Coach must be reachable on your network, not just
   `127.0.0.1`). You can read callouts and hear Coach's voice from that panel. This works only
   while you are in Horizon Home or another 2D panel context: once you enter an immersive app, the
   browser panel is hidden and its audio stops, so it does not help during the game itself. It is
   useful between rounds or in a lobby.
3. **A PC speaker near you** if you have no earbuds; the headset's open-ear speakers let room
   audio through.

### Talk to Coach from a standalone game

Coach's push-to-talk mic lives on the PC page. From inside a standalone game you cannot press it.
Options: have a second person at the PC, use the call-app route above with the PC side feeding the
headset's microphone into Coach's mic input, or ask questions between matches from the Quest
browser panel.

### Summary for standalone play

| Want | Result |
|---|---|
| Coach watches Horizon Worlds or a Quest-native game | Yes, through casting to the PC |
| Highlight boxes or task list drawn inside the game | No. Not possible from the PC |
| Coach's voice in the headset during the game | Only through a call app on the headset with PC audio routed into the call |
| Coach's voice or text while in Horizon Home | Yes, through the Quest browser open to Coach on your LAN |
| Push-to-talk from inside the game | No, unless routed through the call app |

Sources used for the tool steps: XSOverlay official docs (https://xsoverlay.vercel.app/gettingstarted,
https://xsoverlay.vercel.app/overlaysettings) and the VRChat community wiki
(https://wiki.vrchat.com/wiki/Community:XSOverlay); OVR Toolkit wiki
(https://wiki.ovrtoolkit.co.uk/#/EditMode, https://wiki.ovrtoolkit.co.uk/#/WindowSettings,
https://wiki.ovrtoolkit.co.uk/#/Oculus) and Steam page; Desktop+ user guide
(https://github.com/elvissteinjr/DesktopPlus/blob/master/docs/user_guide.md); Meta help for Link
audio (https://www.meta.com/help/quest/808853193347112/) and casting
(https://www.meta.com/help/quest/192719842695017/). Checked 2026-11-01; menu names change between
versions, so if a button is missing look for the nearest match.
