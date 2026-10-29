"""Live smoke test against the Meta Model API. Costs a few cents of credit.

Run on a machine that can reach api.meta.ai, from the repo root:
    python scripts/live_check.py            # health, models, one Coach reply
    python scripts/live_check.py clip.wav   # also transcribes a WAV (mono 16-bit, 24 kHz)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from muse_replay.coach_llm import coach_reply            # noqa: E402
from muse_replay.config import load_settings             # noqa: E402
from muse_replay.health import health_report             # noqa: E402
from muse_replay.meta_api import MetaClient              # noqa: E402
from muse_replay.voice import speak, transcribe_file     # noqa: E402


def load_dotenv(path: Path) -> None:
    if path.is_file():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    code, text = health_report()
    print(text)
    if code:
        return code
    client = MetaClient(load_settings())
    models = client.list_models()
    print(f"models: {len(models)} available, spark={'muse-spark-1.3' in models}, "
          f"asr={'muse-voice-transcribe-1.0' in models}")
    r = coach_reply(client, "We just lost the first round. What should we change?",
                    context="Game: 2v2 tactical shooter. Round 1 lost, both of us pushed mid.")
    print(f"coach: {r.text}")
    print(f"tokens: in={r.input_tokens} out={r.output_tokens} reasoning={r.reasoning_tokens}")
    print(f"spoke via: {speak(r.text)}")
    if len(sys.argv) > 1:
        t = transcribe_file(client, sys.argv[1], mode="ENDPOINTING", keywords=["Coach"])
        print(f"transcript ({t.audio_ms} ms): {t.text!r}  turns={len(t.turns)}")
    # Agent with tools on a synthetic match (made with ffmpeg, no real footage needed).
    import subprocess
    import tempfile
    from muse_replay.agent import CoachAgent
    from muse_replay.memory import MatchMemory
    from muse_replay.tools import Session
    with tempfile.TemporaryDirectory() as td:
        video = Path(td) / "match.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "smptebars=duration=10:size=320x240:rate=30",
                        "-f", "lavfi", "-i", "testsrc=duration=10:size=320x240:rate=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
                        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a]volume='if(between(t,14,15),1.0,0.02)':eval=frame[a]",
                        "-map", "[v]", "-map", "[a]", "-pix_fmt", "yuv420p", "-t", "20", str(video)], check=True)
        session = Session(work_dir=Path(td), memory=MatchMemory(Path(td) / "m.json"), match="live-check",
                          video=str(video), client=client)
        agent = CoachAgent(client, session)
        for ask in ["Look at the screen at 15 seconds and tell me what you see.",
                    "Find the biggest moment and clip it, then remember what happened."]:
            r = agent.turn(ask)
            for c in r.tool_calls:
                print(f"  [tool] {c['name']}({c['arguments']}) -> {c['output'][:120]}")
            print(f"agent: {r.text}  (rounds={r.rounds}, tokens in={r.input_tokens} out={r.output_tokens})")
        print(f"memory notes: {len(session.memory)}, clips: {len(list((Path(td) / 'clips').glob('*.mp4'))) if (Path(td) / 'clips').exists() else 0}")

        # Live mode + playbook: push one real frame (grabbed from the synthetic match) and run a teach tick.
        from muse_replay.agent import TEACH_PROMPT, WATCH_PROMPT
        from muse_replay.ingest import sample_frames
        from muse_replay.playbook import make_playbook
        from muse_replay.tools import LiveFeed
        _, frames = sample_frames(str(video), Path(td) / "lf", every_s=1, max_frames=1, width=960, start_s=15, end_s=15.5)
        feed = LiveFeed(); feed.push(Path(frames[0].path).read_bytes())
        pb = make_playbook({"game": "Test Card TV", "goal": "Keep the colour bars on screen and never let the picture go black.",
                            "controls": "Space pauses the feed. R resets the pattern.",
                            "mistakes": "Pressing R while the bars are already clean."})
        live = Session(work_dir=Path(td), memory=session.memory, match="live-check", client=client, live=feed, playbook=pb, teach=True)
        la = CoachAgent(client, live)
        for label, ask in [("watch tick", WATCH_PROMPT), ("teach tick", TEACH_PROMPT), ("new player asks", "I'm new. What am I looking at and what should I do?")]:
            r = la.turn(ask)
            tools_used = [c["name"] for c in r.tool_calls]
            print(f"live {label}: tools={tools_used} spoken={live.spoken[-1:]} reply={r.text!r} (rounds={r.rounds})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
