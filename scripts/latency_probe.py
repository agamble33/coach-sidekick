"""Where does Coach's turn time go? Times the raw /responses call with different payload shapes.
    python scripts/latency_probe.py     (reads .env; writes coach_data/latency_probe.json)"""
import json, os, statistics, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
from coach.agent import instructions_for                 # noqa: E402
from coach.config import load_settings                   # noqa: E402
from coach.memory import MatchMemory                     # noqa: E402
from coach.meta_api import MetaClient                    # noqa: E402
from coach.tools import Session, tool_specs              # noqa: E402

client = MetaClient(load_settings())
tmp = Path(tempfile.mkdtemp())
s = Session(work_dir=tmp, memory=MatchMemory(tmp / "m.json"), match="live session")
INSTR = instructions_for(s); TOOLS = tool_specs()
Q = "Two enemies are reloading on my left. What do I do?"
print(f"instructions {len(INSTR)} chars, {len(TOOLS)} tools, tool schema {len(json.dumps(TOOLS))} chars", flush=True)

def call(model, instructions, tools, effort="low", previous=None, text=Q):
    p = {"model": model, "instructions": instructions, "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}],
         "reasoning": {"effort": effort}, "stream": False}
    if tools:
        p.update(tools=tools, tool_choice="auto", parallel_tool_calls=True)
    if previous:
        p["previous_response_id"] = previous
    t0 = time.time(); r = client.post_json("/responses", p); dt = time.time() - t0
    u = r.get("usage", {})
    return dt, r.get("id"), u.get("input_tokens"), (u.get("output_tokens_details") or {}).get("reasoning_tokens"), u.get("output_tokens")

rows = []
def variant(name, **kw):
    ts, info = [], None
    for _ in range(3):
        try:
            dt, rid, inp, reas, out = call(**kw); ts.append(dt); info = (inp, reas, out)
        except Exception as e:
            info = str(e)[:120]; break
    row = {"variant": name, "median_s": round(statistics.median(ts), 2) if ts else None, "runs": [round(t, 2) for t in ts], "in/reasoning/out tokens": info}
    rows.append(row); print(json.dumps(row), flush=True)

M = "muse-spark-1.3-contributor"
# variant("1 bare prompt", model=M, instructions="You are Coach, a gaming teammate. Reply in one short line.", tools=None)
# variant("2 full instructions, no tools", model=M, instructions=INSTR, tools=None)
# variant("3 full instructions + all tools (what Coach sends)", model=M, instructions=INSTR, tools=TOOLS)
# real Coach turns, timing every model round, with and without the thread (previous_response_id)
from coach.agent import CoachAgent   # noqa: E402
QS = ["hi coach", "what should I do if I keep dying at the bridge?", "remember I like invert Y on", "two enemies reloading on my left, what now?", "where do I go next?"]
for threaded in (True, False):
    agent = CoachAgent(client, s)
    rounds = []
    real = client.post_json
    def timed(path, payload, _real=real):
        t0 = time.time(); r = _real(path, payload); rounds.append((round(time.time() - t0, 2), (r.get("usage") or {}).get("input_tokens"), ((r.get("usage") or {}).get("output_tokens_details") or {}).get("reasoning_tokens")))
        return r
    client.post_json = timed
    for q in QS:
        if not threaded:
            agent.reset()
        rounds.clear(); t0 = time.time(); res = agent.turn(q)
        row = {"variant": f"agent turn ({'threaded' if threaded else 'fresh each turn'})", "q": q, "total_s": round(time.time() - t0, 2),
               "rounds (secs, input tok, reasoning tok)": list(rounds), "tools": [c["name"] for c in res.tool_calls]}
        rows.append(row); print(json.dumps(row), flush=True)
    client.post_json = real
(ROOT / "coach_data" / "latency_probe.json").write_text(json.dumps(rows, indent=1))
print("saved coach_data/latency_probe.json")
