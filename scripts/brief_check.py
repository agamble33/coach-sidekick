"""Real-model check: write a game brief for four games and one made-up game. Reads .env."""
import os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
from coach.config import load_settings
from coach.gamebrief import GameBriefStore
from coach.meta_api import MetaClient
client = MetaClient(load_settings()); store = GameBriefStore(ROOT / "coach_data" / "game_briefs")
for g in ("Fortnite", "Beat Saber", "Call of Duty Warzone", "Roblox Blox Fruits", "Zorbulon Quest 9000"):
    t0 = time.time(); b = store.ensure(g, client); dt = time.time() - t0
    secs = ["HOW IT PLAYS", "WORDS", "MODES AND LEVELS", "FIRST HOUR", "ROOKIE MISTAKES", "DANGER SIGNS"]
    have = [x for x in secs if x in b]
    print(("PASS " if (len(have) == 6 or (g.startswith("Zorbulon") and not b)) else "FAIL ") + f"{g}: {dt:.1f}s, {len(b)} chars, sections={len(have)}/6" + ("" if b else " (unknown game, no brief)"), flush=True)
    print("     " + b[:260].replace("\n", " | "), flush=True)
