"""Time every text model on this key with the same short Coach prompt, low effort, 3 tries each.
    python scripts/model_speed.py      (reads .env; writes coach_data/model_speed.json)"""
import json, os, statistics, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
from coach.coach_llm import build_request, parse_reply   # noqa: E402
from coach.config import load_settings                    # noqa: E402
from coach.meta_api import MetaClient                     # noqa: E402

client = MetaClient(load_settings())
models = client.list_models()
print("models on this key:", models, flush=True)
rows = []
for m in models:
    if any(x in m for x in ("transcribe", "tts", "voice", "image", "embed")):
        continue
    times, err, text = [], "", ""
    for _ in range(3):
        t0 = time.time()
        try:
            r = parse_reply(client.post_json("/responses", build_request("Two enemies are reloading on my left. One line: what do I do?", "", m, "low")))
            times.append(time.time() - t0); text = r.text
        except Exception as e:
            err = str(e)[:160]; break
    row = {"model": m, "median_s": round(statistics.median(times), 2) if times else None, "runs": [round(t, 2) for t in times], "error": err, "sample": text[:100]}
    rows.append(row); print(json.dumps(row), flush=True)
(ROOT / "coach_data" / "model_speed.json").write_text(json.dumps(rows, indent=1))
print("saved coach_data/model_speed.json")
