// Coach PC overlay. Opens the Coach overlay page in a transparent, frameless, click-through,
// always-on-top window the size of the primary display, with a tray menu to control it.
//
// Flags (environment variables, all optional):
//   COACH_URL=http://127.0.0.1:8000   base URL of the Coach server (default shown)
//   COACH_OVERLAY_NO_GPU=1            disable hardware acceleration. Try this if the window
//                                     shows a black or white rectangle instead of a transparent
//                                     one (happens on some Windows GPUs and drivers).
//   COACH_OVERLAY_LOG=1               extra log lines (URL loads)

const { app, BrowserWindow, Tray, Menu, screen, globalShortcut, shell, ipcMain, nativeImage } = require("electron");
const fs = require("fs");
const path = require("path");

const COACH_BASE = (process.env.COACH_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const DEMO_URL = COACH_BASE + "/overlay?demo=1";
const TOGGLE_KEY = "CommandOrControl+Shift+O";
const VERBOSE = process.env.COACH_OVERLAY_LOG === "1";

function log(...a) { console.log("[coach-overlay]", ...a); }

// Transparent windows on Windows sometimes render as an opaque black rectangle when the GPU
// compositor is involved. This must be called before the app is ready.
if (process.env.COACH_OVERLAY_NO_GPU === "1") {
  app.disableHardwareAcceleration();
  log("hardware acceleration disabled (COACH_OVERLAY_NO_GPU=1)");
}

let overlay = null;
let linkWin = null;
let tray = null;

// ---- settings: {"url": "..."} in userData/overlay-settings.json ----
function settingsPath() { return path.join(app.getPath("userData"), "overlay-settings.json"); }
function loadSettings() {
  try { return JSON.parse(fs.readFileSync(settingsPath(), "utf8")); } catch (e) { return {}; }
}
function saveSettings(s) {
  fs.mkdirSync(path.dirname(settingsPath()), { recursive: true });
  fs.writeFileSync(settingsPath(), JSON.stringify(s, null, 2));
}

// Add pc=1 so the overlay page can adapt to the desktop app later.
function withPcFlag(url) {
  try {
    const u = new URL(url);
    u.searchParams.set("pc", "1");
    return u.toString();
  } catch (e) {
    return url;
  }
}

function currentUrl() {
  const s = loadSettings();
  return withPcFlag(s.url && /^https?:\/\//i.test(s.url) ? s.url : DEMO_URL);
}

// ---- overlay window ----
function createOverlay() {
  const bounds = screen.getPrimaryDisplay().bounds;
  overlay = new BrowserWindow({
    x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    focusable: false,
    show: false,
    backgroundColor: "#00000000",
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false },
  });
  overlay.setAlwaysOnTop(true, "screen-saver");
  overlay.setIgnoreMouseEvents(true, { forward: true });
  overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlay.setMenu(null);
  overlay.once("ready-to-show", () => {
    overlay.showInactive();
    // Windows clamps a new window to the work area (screen minus taskbar), so the first show
    // can come up short by the taskbar height. Re-apply the full display bounds once shown.
    overlay.setBounds(bounds);
    log("overlay shown", JSON.stringify({
      bounds: overlay.getBounds(), display: bounds,
      alwaysOnTop: overlay.isAlwaysOnTop(), visible: overlay.isVisible(),
    }));
  });
  overlay.webContents.on("did-finish-load", () => log("loaded", overlay.webContents.getURL()));
  overlay.webContents.on("did-fail-load", (_e, code, desc, url) => log("load failed", code, desc, url));
  overlay.on("closed", () => { overlay = null; });
  loadOverlay(currentUrl());
}

function loadOverlay(url) {
  if (!overlay) return;
  if (VERBOSE) log("loading", url);
  overlay.loadURL(url);
}

function showOverlay() {
  if (!overlay) { createOverlay(); return; }
  if (!overlay.isVisible()) overlay.showInactive();
}

function toggleOverlay() {
  if (!overlay) { createOverlay(); buildTray(); return; }
  if (overlay.isVisible()) { overlay.hide(); log("overlay hidden"); }
  else { overlay.showInactive(); log("overlay shown"); }
  buildTray();
}

function useDemo() {
  const s = loadSettings();
  delete s.url;
  saveSettings(s);
  log("showing demo layout");
  if (!overlay) createOverlay(); else loadOverlay(currentUrl());
  showOverlay();
  buildTray();
}

// ---- "Set overlay link..." window ----
function openLinkWindow() {
  if (linkWin && !linkWin.isDestroyed()) { linkWin.focus(); return; }
  linkWin = new BrowserWindow({
    width: 520, height: 240, resizable: false, minimizable: false, maximizable: false,
    title: "Coach overlay link", autoHideMenuBar: true, alwaysOnTop: true,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false },
  });
  linkWin.setMenu(null);
  linkWin.loadFile(path.join(__dirname, "link.html"));
  linkWin.on("closed", () => { linkWin = null; });
}

ipcMain.handle("link:get", () => ({ url: loadSettings().url || "", demo: DEMO_URL }));
ipcMain.handle("link:set", (_e, url) => {
  url = String(url || "").trim();
  if (!url) { useDemo(); return { ok: true, demo: true }; }
  if (!/^https?:\/\//i.test(url)) return { ok: false, error: "The link must start with http:// or https://" };
  const s = loadSettings();
  s.url = url;
  saveSettings(s);
  log("overlay link saved ->", settingsPath());
  if (!overlay) createOverlay(); else loadOverlay(currentUrl());
  showOverlay();
  buildTray();
  return { ok: true };
});

// ---- tray ----
function buildTray() {
  if (!tray) {
    const icon = nativeImage.createFromPath(path.join(__dirname, "tray.png"));
    tray = new Tray(icon);
    tray.on("double-click", toggleOverlay);
  }
  const shown = !!(overlay && overlay.isVisible());
  const s = loadSettings();
  tray.setToolTip("Coach overlay" + (s.url ? "" : " (demo layout)"));
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: s.url ? "Link: " + s.url : "No link set (showing demo)", enabled: false },
    { label: "Set overlay link...", click: openLinkWindow },
    { label: "Show demo layout", click: useDemo },
    { label: (shown ? "Hide overlay" : "Show overlay") + "\tCtrl+Shift+O", click: toggleOverlay },
    { type: "separator" },
    { label: "Open Coach", click: () => shell.openExternal(COACH_BASE + "/") },
    { label: "Reload overlay", click: () => overlay && overlay.webContents.reloadIgnoringCache() },
    { type: "separator" },
    { label: "Quit", click: () => app.quit() },
  ]));
}

// ---- lifecycle ----
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => showOverlay());

  app.whenReady().then(() => {
    log("electron", process.versions.electron, "platform", process.platform, "userData", app.getPath("userData"));
    log("coach base", COACH_BASE, "stored link", loadSettings().url || "(none, demo layout)");
    createOverlay();
    buildTray();
    const ok = globalShortcut.register(TOGGLE_KEY, toggleOverlay);
    log("shortcut", TOGGLE_KEY, ok ? "registered" : "FAILED to register (another app holds it)");
    // Follow display changes so the overlay keeps covering the primary screen.
    screen.on("display-metrics-changed", () => {
      if (!overlay) return;
      const b = screen.getPrimaryDisplay().bounds;
      overlay.setBounds(b);
      log("display changed, bounds now", JSON.stringify(b));
    });
    if (process.env.COACH_OVERLAY_SELFTEST === "1") selfTest();
  });

  // COACH_OVERLAY_SELFTEST=1: exercise toggle, link save and demo without a mouse or keyboard,
  // log each step, then quit. Used to verify the app on a machine with no screen capture.
  function selfTest() {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    (async () => {
      await sleep(3000);
      toggleOverlay(); log("selftest after toggle 1: visible =", overlay.isVisible());
      await sleep(500);
      toggleOverlay(); log("selftest after toggle 2: visible =", overlay.isVisible());
      await sleep(500);
      const before = loadSettings().url || "";
      const testUrl = COACH_BASE + "/overlay?live=selftest";
      const s = loadSettings(); s.url = testUrl; saveSettings(s);
      loadOverlay(currentUrl());
      await sleep(2500);
      log("selftest stored link:", loadSettings().url, "| page URL:", overlay.webContents.getURL());
      if (before) { const t = loadSettings(); t.url = before; saveSettings(t); } else { const t = loadSettings(); delete t.url; saveSettings(t); }
      loadOverlay(currentUrl());
      await sleep(2000);
      log("selftest restored, page URL:", overlay.webContents.getURL(), "| settings file:", settingsPath());
      log("selftest done");
      app.quit();
    })();
  }

  // A tray app: do not quit when the overlay is hidden or the link window closes.
  app.on("window-all-closed", () => {});
  app.on("will-quit", () => globalShortcut.unregisterAll());
}
