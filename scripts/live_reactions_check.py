# Live check for meme reactions, stings and avatars: real server + real overlay in Chromium.
# Usage from the repo root: python scripts/live_reactions_check.py . out_dir
"""Live test: real Coach server + real overlay page in Chromium.
Fires every reaction, checks the card image, the sting actually playing, the avatar (face) switching,
the classic pack, game-event reactions, and the blocked-autoplay chip. Saves screenshots + a video."""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
B = "http://127.0.0.1:8099"
env = dict(os.environ, COACH_DATA=str(OUT / "data"), META_API_KEY="test", META_BASE_URL="https://api.meta.ai/v1")
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "web.app:app", "--port", "8099"], cwd=ROOT, env=env,
                       stdout=open(OUT / "server.log", "w"), stderr=subprocess.STDOUT)
results = []
def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

def j(method, path, body=None, H=None):
    req = urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=dict({"Content-Type": "application/json"}, **(H or {})), method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:200]

for _ in range(40):
    try: urllib.request.urlopen(B + "/api/health", timeout=1); break
    except Exception: time.sleep(0.5)

AUDIO_HOOK = """
window.__audio = [];
const _A = window.Audio;
window.Audio = function(src){ const a = new _A(src); const rec = {src: String(src), played: false, error: null, duration: 0, t: 0};
  window.__audio.push(rec);
  const _p = a.play.bind(a);
  a.play = () => _p().then(() => { rec.played = true; setTimeout(()=>{ rec.duration = a.duration; rec.t = a.currentTime; }, 400); })
                    .catch(e => { rec.error = String(e && e.name || e); throw e; });
  return a; };
"""
EXPECT = {  # trigger -> (image, sting) from reactions.json
    "missed_jump": ("cackle.png", "womp.mp3"), "dumb_play": ("horse_judge.png", "bruh.mp3"),
    "ignored_callout": ("side_eye.png", "scratch.mp3"), "rizz_detected": ("rizz.png", "airhorn.mp3"),
    "slow_reaction": ("sleepy_dog.png", "boing.mp3"), "near_death": ("scream.png", "gasp.mp3"),
    "whiff": ("stunned_cats.png", "scratch.mp3"), "clutch": ("big_brain.png", "dingding.mp3"),
    "shocked": ("coach_selfie.png", "cackle.mp3"),
}
try:
    st, v = j("GET", "/api/consent/version")
    st, c = j("POST", "/api/consent", {"version": v["version"], "see": True, "hear": True, "age_ok": True})
    H = {"X-Coach-Consent": c["consent_id"]}
    st, live = j("POST", "/api/live/start", {}, H); lid = live["live_id"]
    st, s = j("POST", f"/api/overlay/{lid}/settings", {"spice": "unhinged", "pack": "3d", "avatar": "muse_bot", "guide": True}, H)
    ok("settings accepted (unhinged, 3d, muse_bot, guide on)", st == 200 and s["avatar"] == "muse_bot", f"{st}")

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(OUT / "video"), record_video_size={"width": 1280, "height": 720})
        pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "favicon" not in m.text else None)
        pg.add_init_script(AUDIO_HOOK)
        pg.goto(f"{B}/overlay?live={lid}"); pg.evaluate("document.body.style.background='#1b2a44'")
        pg.wait_for_timeout(1500)
        av = pg.evaluate("(document.querySelector('#av img')||{}).src || ''")
        ok("face: badge shows Muse Bot avatar", av.endswith("/reactions/avatars/muse_bot.png"), av.split('/')[-1])
        ok("face: badge label 'Muse Bot'", pg.inner_text("#avname") == "Muse Bot")

        # ---- every reaction, one at a time (global cooldown is 3 s) ----
        for trig, (img, sting) in EXPECT.items():
            st, r = j("POST", f"/api/overlay/{lid}/react", {"trigger": trig}, H)
            if not (st == 200 and r.get("fired")):
                ok(f"{trig}: fired", False, str(r)); time.sleep(3.2); continue
            pg.wait_for_function(f"document.querySelector('#reaction img').src.endsWith('/{img}') && document.getElementById('reaction').classList.contains('show')", timeout=4000)
            pg.wait_for_timeout(700)
            card = pg.evaluate("(()=>{const i=document.querySelector('#reaction img'); return {w:i.naturalWidth, line:document.querySelector('#reaction .line').textContent, tag:document.querySelector('#reaction .tag').textContent}})()")
            aud = [a for a in pg.evaluate("window.__audio") if a["src"].endswith("/" + sting)]
            last = aud[-1] if aud else {}
            ok(f"{trig}: card {img} loaded (512px) with line", card["w"] == 512 and card["line"], f"\"{card['line']}\"")
            ok(f"{trig}: sting {sting} played", last.get("played") and last.get("duration", 0) > 0.3 and last.get("t", 0) > 0,
               f"played={last.get('played')} dur={round(last.get('duration',0),2)}s t={round(last.get('t',0),2)}s err={last.get('error')}")
            ok(f"{trig}: card tagged with avatar name", "MUSE BOT" in card["tag"].upper(), card["tag"])
            if trig in ("missed_jump", "rizz_detected", "near_death", "shocked"):
                pg.screenshot(path=str(OUT / f"card_{trig}.png"), clip={"x": 880, "y": 560, "width": 400, "height": 160})
            time.sleep(3.2)

        # ---- cooldown: same trigger twice in a row is refused calmly ----
        j("POST", f"/api/overlay/{lid}/react", {"trigger": "whiff"}, H); time.sleep(3.2)
        st, r = j("POST", f"/api/overlay/{lid}/react", {"trigger": "whiff"}, H)
        ok("cooldown: repeat inside 8 s refused", st == 200 and r == {"fired": False, "reason": "trigger cooldown"}, str(r))

        # ---- face changes: switch avatar live ----
        for name, label in (("coach", "Coach"), ("dog", "Dog"), ("muse_bot", "Muse Bot")):
            j("POST", f"/api/overlay/{lid}/settings", {"avatar": name}, H)
            pg.wait_for_function(f"(document.querySelector('#av img')||{{}}).src && document.querySelector('#av img').src.endsWith('/{name}.png')", timeout=4000)
            nat = pg.evaluate("document.querySelector('#av img').naturalWidth")
            ok(f"face: switched to {label} on the badge", pg.inner_text("#avname") == label and nat == 256, f"img {nat}px")
            time.sleep(3.2)
            t = {"coach": "dumb_play", "dog": "clutch", "muse_bot": "slow_reaction"}[name]
            j("POST", f"/api/overlay/{lid}/react", {"trigger": t}, H)
            pg.wait_for_function(f"document.querySelector('#reaction .tag img') && document.querySelector('#reaction .tag img').src.endsWith('/{name}.png')", timeout=4000)
            ok(f"face: {label} avatar on the next reaction card", True)
            pg.wait_for_timeout(600); pg.screenshot(path=str(OUT / f"face_{name}.png"), clip={"x": 0, "y": 0, "width": 1280, "height": 720})

        # ---- classic pack ----
        time.sleep(3.2)
        j("POST", f"/api/overlay/{lid}/settings", {"pack": "classic"}, H)
        time.sleep(8.5)  # dumb_play cooled down
        j("POST", f"/api/overlay/{lid}/react", {"trigger": "dumb_play"}, H)
        pg.wait_for_function("document.querySelector('#reaction img').src.endsWith('/classic/horse_judge.png')", timeout=4000)
        pg.wait_for_timeout(600)
        ok("classic pack: polished original horse card shown", pg.evaluate("document.querySelector('#reaction img').naturalWidth") == 512)
        pg.screenshot(path=str(OUT / "card_classic_horse.png"), clip={"x": 880, "y": 560, "width": 400, "height": 160})
        time.sleep(3.2)
        j("POST", f"/api/overlay/{lid}/react", {"trigger": "rizz_detected"}, H)  # no classic version: falls back to 3D
        time.sleep(5)
        j("POST", f"/api/overlay/{lid}/react", {"trigger": "rizz_detected"}, H)
        pg.wait_for_function("document.querySelector('#reaction img').src.endsWith('/images/rizz.png')", timeout=10000)
        ok("classic pack: rizz falls back to the 3D card", True)
        j("POST", f"/api/overlay/{lid}/settings", {"pack": "3d"}, H)

        # ---- game event -> reaction with no model call ----
        time.sleep(3.2)
        st, r = j("POST", f"/api/game/{lid}/state", {"events": [{"type": "fell", "detail": "missed the ledge"}]}, H)
        if r.get("reactions_fired") == []:  # missed_jump may still be cooling down from earlier
            time.sleep(8.5); st, r = j("POST", f"/api/game/{lid}/state", {"events": [{"type": "fell"}]}, H)
        ok("game event 'fell' fires missed_jump", r.get("reactions_fired") == ["missed_jump"], str(r))
        pg.wait_for_function("document.querySelector('#reaction img').src.endsWith('/cackle.png') && document.getElementById('reaction').classList.contains('show')", timeout=4000)
        ok("game event: card + sting on the overlay", any(a["src"].endswith("/womp.mp3") and a["played"] for a in pg.evaluate("window.__audio")))

        # ---- spice off: nothing fires ----
        j("POST", f"/api/overlay/{lid}/settings", {"spice": "off"}, H); time.sleep(3.2)
        st, r = j("POST", f"/api/overlay/{lid}/react", {"trigger": "near_death"}, H)
        ok("spice off: no reaction", r.get("fired") is False, str(r))
        ok("no page errors on the overlay", not errs, "; ".join(errs[:3]))
        ctx.close()

        # ---- blocked autoplay: chip appears, one click plays the sting ----
        b2 = p.chromium.launch()  # default policy: autoplay blocked without a gesture
        pg2 = b2.new_page(viewport={"width": 1280, "height": 720}); pg2.add_init_script(AUDIO_HOOK)
        j("POST", f"/api/overlay/{lid}/settings", {"spice": "unhinged"}, H)
        pg2.goto(f"{B}/overlay?live={lid}"); pg2.wait_for_timeout(1500)
        time.sleep(8.5)
        j("POST", f"/api/overlay/{lid}/react", {"trigger": "clutch"}, H)
        pg2.wait_for_function("!document.getElementById('sound').hidden", timeout=10000)
        ok("blocked autoplay: 'Click once for meme sounds' chip shown", True)
        pg2.screenshot(path=str(OUT / "sound_chip.png"))
        pg2.click("#sound")
        try:
            pg2.wait_for_function("window.__audio.some(a => a.src.endsWith('/dingding.mp3') && a.played)", timeout=4000); played = True
        except Exception:
            played = False
        ok("blocked autoplay: one click plays the sting", bool(played))
        b2.close(); b.close()
    j("POST", f"/api/live/{lid}/stop", {}, H)
finally:
    srv.terminate()
passed = sum(1 for _, c, _ in results if c)
print(f"\nRESULT {passed}/{len(results)} checks passed")
(OUT / "results.json").write_text(json.dumps([{"check": n, "pass": c, "detail": d} for n, c, d in results], indent=1))
