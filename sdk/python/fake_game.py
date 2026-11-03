"""A fake game that speaks the Coach Game SDK. Use it to test Coach without an engine, and in the
demo video as a terminal client driving arrows on the overlay.

    python sdk/python/fake_game.py --base http://127.0.0.1:8000 --live LIVE_ID --consent CONSENT_ID

The player walks a loop past three landmarks, reports which are on screen, and emits a few events
(fell, clutch). Watch the overlay: Coach's arrows anchor on landmark ids, reactions fire from events.
"""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.request

LANDMARKS = {  # id -> (label, world x, world z)
    "courtyard": ("Courtyard", 0.0, 10.0),
    "fountain": ("Fountain", 20.0, -5.0),
    "east_gate": ("East gate", 40.0, -8.0),
}
FOV = 70.0


def project(px, pz, yaw_deg, lx, lz):
    """Project a world point to screen fractions for a camera at (px, pz) facing yaw. Returns
    (visible, screen_xy, direction)."""
    dx, dz = lx - px, lz - pz
    dist = math.hypot(dx, dz)
    ang = math.degrees(math.atan2(dx, dz)) - yaw_deg
    ang = (ang + 180) % 360 - 180
    if abs(ang) < FOV / 2 and dist > 0.5:
        x = 0.5 + (ang / FOV)
        y = 0.55 - min(0.3, 4.0 / max(dist, 1))   # farther things sit higher on screen
        return True, [round(x, 3), round(y, 3)], ""
    return False, None, ("left" if ang < -FOV / 2 and ang > -135 else "right" if ang > FOV / 2 and ang < 135 else "behind")


def state_at(t: float) -> dict:
    """Player walks a circle of radius 20 around (20, 0), facing along the path."""
    ang = (t * 12.0) % 360
    px, pz = 20 + 20 * math.cos(math.radians(ang)), 20 * math.sin(math.radians(ang))
    yaw = (ang + 90) % 360
    lms = []
    for lid, (label, lx, lz) in LANDMARKS.items():
        vis, scr, d = project(px, pz, yaw, lx, lz)
        lms.append({"id": lid, "label": label, "pos": [round(lx, 1), 0, round(lz, 1)], "visible": vis, "screen": scr, "dir": d})
    events = []
    step = int(t) % 30
    if step == 7:
        events.append({"type": "fell", "detail": "missed the ledge by the fountain"})
    if step == 19:
        events.append({"type": "clutch", "detail": "cleared the courtyard"})
    return {"game": "Fake Game", "player": {"pos": [round(px, 1), 0, round(pz, 1)], "yaw": round(yaw), "hp": 70, "state": "exploring"},
            "objective": "Find the east gate key", "landmarks": lms, "events": events}


def post(base, live, consent, body):
    req = urllib.request.Request(f"{base}/api/game/{live}/state", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Coach-Consent": consent}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def directives(base, live):
    with urllib.request.urlopen(f"{base}/api/game/{live}/directives", timeout=5) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--live", required=True)
    ap.add_argument("--consent", required=True)
    ap.add_argument("--hz", type=float, default=1.0)
    a = ap.parse_args()
    t0 = time.time()
    last_speak = 0.0
    while True:
        t = time.time() - t0
        r = post(a.base, a.live, a.consent, state_at(t))
        d = directives(a.base, a.live)
        ov = d["overlay"]
        arrows = [f"{p.get('landmark') or p['label']}:{p['direction']}" for p in ov.get("pointers", [])]
        route = [w.get("landmark") or w.get("label") for w in ov.get("route", [])]
        if d.get("speak_at", 0) > last_speak:
            last_speak = d["speak_at"]; print(f"[{t:6.1f}s] COACH SAYS: {d['speak']}")
        print(f"[{t:6.1f}s] posted #{r['posts']} fired={r['reactions_fired']} arrows={arrows} route={route}")
        time.sleep(1.0 / a.hz)
