"""Does Muse know real game tactics out of the box? Ten questions across popular games, graded by
whether the answer names the right specifics. Run on the PC with .env:
    python scripts/tactic_check.py    -> coach_data/tactic_check.log"""
import json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
from coach.coach_llm import build_request, parse_reply
from coach.config import load_settings
from coach.meta_api import MetaClient

# (game, question, any-of keywords a knowledgeable answer should contain)
QS = [
    ("Call of Duty", "In Call of Duty on Nuketown, where do people usually hold when defending the house side? Two sentences.", ["window", "garage", "yard", "bus", "house", "second floor", "upstairs", "door"]),
    ("Call of Duty", "In Call of Duty Search and Destroy, why do teams save a plant for the last few seconds? One sentence.", ["defuse", "time", "clock", "bomb"]),
    ("Fortnite", "In Fortnite, what is the point of building a ramp when you take fire in the open? One sentence.", ["cover", "high ground", "height", "protect", "block"]),
    ("Fortnite", "In Fortnite, what does the storm do and how should a new player plan around it? Two sentences.", ["circle", "zone", "damage", "shrink", "rotate", "move"]),
    ("Roblox", "In Roblox Blox Fruits, what should a brand new player do first to level up? Two sentences.", ["quest", "bandit", "level", "fruit", "sword", "npc"]),
    ("Roblox", "In Roblox Adopt Me, how do you get a pet as a new player? One sentence.", ["egg", "hatch", "buck", "starter", "nursery", "shop"]),
    ("Minecraft", "In Minecraft survival, what should you do before the first night? Two sentences.", ["shelter", "wood", "bed", "torch", "tools", "craft", "dig"]),
    ("Minecraft", "In Minecraft, how do you find diamonds? One sentence.", ["y", "deep", "level", "-5", "-59", "-58", "cave", "mine", "branch"]),
    ("Rocket League", "In Rocket League, what does rotation mean and why does it matter? Two sentences.", ["back", "goal", "position", "ball chase", "chasing", "defend", "third man"]),
    ("Valorant", "In Valorant, what is a default on attack? One sentence.", ["map control", "space", "information", "spread", "info", "utility"]),
]
client = MetaClient(load_settings())
hits = 0; rows = []
for game, q, keys in QS:
    t0 = time.time()
    try:
        text = parse_reply(client.post_json("/responses", build_request(q, "", "muse-spark-1.3-contributor", "low"))).text
    except Exception as e:
        text = f"ERROR {e}"
    found = [k for k in keys if k.lower() in text.lower()]
    ok = len(found) >= 2 or (len(keys) <= 4 and len(found) >= 1)
    hits += ok
    rows.append({"game": game, "ok": ok, "secs": round(time.time() - t0, 1), "found": found, "answer": text[:240]})
    print(("PASS " if ok else "FAIL ") + f"[{game}] {q[:60]}  found={found}\n      " + text[:240].replace("\n", " "), flush=True)
print(f"\nTACTIC CHECK {hits}/{len(QS)} games answered with real specifics")
(ROOT / "coach_data" / "tactic_check.json").write_text(json.dumps(rows, indent=1))
