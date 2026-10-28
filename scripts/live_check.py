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
    speak(r.text)
    if len(sys.argv) > 1:
        t = transcribe_file(client, sys.argv[1], mode="ENDPOINTING", keywords=["Coach"])
        print(f"transcript ({t.audio_ms} ms): {t.text!r}  turns={len(t.turns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
