"""Live regrade for Gates 10 to 12 (reactions, Guide me, Game SDK) against a running Coach
with a real Meta API key. Costs a few cents. Run on a machine that can reach api.meta.ai:

    uvicorn web.app:app --port 8000          (in one terminal, with .env loaded)
    python scripts/regrade_live.py 8000      (in another)

Prints each step and a grade line at the end. Step 5 is the one that matters: Coach is asked
"where do I go" with Guide me on and a game-reported landmark; it should call point with
landmark=east_gate (or draw a route), and the callout should mention the gate.
"""
import json, urllib.request, sys, time, io
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "sdk" / "python")); import fake_game
from PIL import Image, ImageDraw
B="http://127.0.0.1:" + (sys.argv[1] if len(sys.argv) > 1 else "8000")
def j(method, path, body=None, headers=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req=urllib.request.Request(B+path, data=data, headers=dict({"Content-Type":ctype}, **(headers or {})), method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt=r.read().decode(errors="replace")
            return r.status, (json.loads(txt) if r.headers.get_content_type()=="application/json" else txt)
    except urllib.error.HTTPError as e: return e.code, e.read()[:300].decode(errors="replace")
st, v = j("GET","/api/consent/version")
st, c = j("POST","/api/consent", {"version": v["version"], "see": True, "hear": True, "age_ok": True})
H={"X-Coach-Consent": c["consent_id"]}
st, live = j("POST","/api/live/start", {}, H); lid=live["live_id"]
print("[1] live session", st, lid)
print("[2] settings", j("POST", f"/api/overlay/{lid}/settings", {"guide": True, "spice": "unhinged", "pack": "3d", "avatar": "muse_bot"}, H)[1]["guide"])
# a synthetic game frame: courtyard scene with a fountain and a gate label
im=Image.new("RGB",(960,540),(40,60,40)); d=ImageDraw.Draw(im)
d.rectangle((0,330,960,540),fill=(90,80,60)); d.ellipse((430,260,530,320),fill=(80,140,200)); d.text((445,240),"FOUNTAIN",fill="white")
d.rectangle((880,200,960,330),fill=(120,90,50)); d.text((880,180),"GATE ->",fill="yellow"); d.text((20,20),"HP 70   Objective: find the east gate key",fill="white")
buf=io.BytesIO(); im.save(buf,"JPEG",quality=85)
bnd="----coachframe"; body=(f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"frame.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").encode()+buf.getvalue()+f"\r\n--{bnd}--\r\n".encode()
print("[3] frame", j("POST", f"/api/live/{lid}/frame", raw=body, headers=H, ctype=f"multipart/form-data; boundary={bnd}"))
st, r = j("POST", f"/api/game/{lid}/state", fake_game.state_at(7.2), H); print("[4] game state", st, r)
# a real turn: ask where to go
t0=time.time(); st, out = j("POST","/api/turn", {"live_id": lid, "text": "Where do I go to find the key? Point the way."}, H)
tools=[l for l in str(out).splitlines() if '"tool_call"' in l or 'tool_call' in l][:8]
print(f"[5] turn {st} in {time.time()-t0:.1f}s; events with tool_call:", len(tools))
print(str(out)[-700:])
st, d = j("GET", f"/api/game/{lid}/directives"); ov=d["overlay"]
print("[6] directives: callout=", repr(ov["callout"][:120]), "| pointers=", [(p["label"],p["direction"],p.get("landmark")) for p in ov["pointers"]], "| route=", [(w["n"],w.get("landmark")) for w in ov["route"]], "| reaction=", ov["reaction"] and ov["reaction"]["trigger"])
# watch tick with game state present
t0=time.time(); st, out = j("POST","/api/turn", {"live_id": lid, "watch": True}, H)
print(f"[7] watch tick {st} in {time.time()-t0:.1f}s:", str(out)[-300:].replace("\n"," | "))
st, d = j("GET", f"/api/game/{lid}/directives"); ov=d["overlay"]
print("[8] after tick: pointers=", [(p["label"],p["direction"],p.get("landmark")) for p in ov["pointers"]], "| callout=", repr(ov["callout"][:100]))
print("[9] stop", j("POST", f"/api/live/{lid}/stop", {}, H)[0])
pointed = any(p.get("landmark") for p in ov["pointers"]) or any(w.get("landmark") for w in ov["route"])
print("\nGRADE Guide me + Game SDK (model in the loop):", "A (Coach pointed at a game landmark on its own)" if pointed else "B (no landmark pointer this run; read the callout and tool events above, then re-run once)")
