"""Time real Coach turns with local threading (default) vs server threading. Reads .env.
    python scripts/speed_check.py     -> coach_data/speed_check.log"""
import json, os, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
from coach.agent import CoachAgent
from coach.config import load_settings
from coach.memory import MatchMemory
from coach.meta_api import MetaClient
from coach.tools import Session
client = MetaClient(load_settings())
QS = ["hi coach", "remember I like invert Y on", "two enemies reloading on my left, what now?", "what did I ask you to remember?"]
for mode in ("local", "server"):
    tmp = Path(tempfile.mkdtemp()); s = Session(work_dir=tmp, memory=MatchMemory(tmp / "m.json"), match="live session")
    agent = CoachAgent(client, s, threading=mode); rounds = []; real = client.post_json
    def timed(path, payload, _real=real):
        t0 = time.time(); r = _real(path, payload); rounds.append(round(time.time() - t0, 2)); return r
    client.post_json = timed
    tot = 0
    for q in QS:
        rounds.clear(); t0 = time.time(); res = agent.turn(q); dt = round(time.time() - t0, 2); tot += dt
        print(json.dumps({"mode": mode, "q": q, "total_s": dt, "rounds_s": list(rounds), "tools": [c["name"] for c in res.tool_calls], "reply": res.text[:80]}), flush=True)
    print(f"{mode}: {tot:.1f}s for {len(QS)} turns", flush=True)
    client.post_json = real
