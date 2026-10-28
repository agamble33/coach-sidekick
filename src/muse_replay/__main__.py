"""Command line entry point.

python -m muse_replay health
python -m muse_replay ingest VIDEO --out DIR [--every 2] [--max 120] [--width 768]
python -m muse_replay clips VIDEO --out DIR [--top 5] [--pre 4] [--post 4] [--scene 0.3]
python -m muse_replay transcribe AUDIO [--mode ENDPOINTING] [--keyword Coach ...]
python -m muse_replay coach "what should we do?" [--context "..."] [--speak]
python -m muse_replay play "clip the best moment" --video match.mp4 [--work DIR] [--speak]
"""

from __future__ import annotations

import argparse
import json
import sys

from .health import health_report
from .agent import CoachAgent
from .clips import cut_highlights
from .coach_llm import coach_reply
from .config import load_settings
from .ingest import DEFAULT_EVERY_S, DEFAULT_MAX_FRAMES, DEFAULT_WIDTH, IngestError, sample_frames
from .meta_api import MetaAPIError, MetaClient
from .memory import MatchMemory
from .moments import MomentError
from .tools import Session
from .voice import VoiceError, speak, to_wav_24k, transcribe_file


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="muse_replay")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("health", help="show which model providers are configured")
    ing = sub.add_parser("ingest", help="sample frames from a gameplay video")
    ing.add_argument("video")
    ing.add_argument("--out", required=True)
    ing.add_argument("--every", type=float, default=DEFAULT_EVERY_S)
    ing.add_argument("--max", type=int, default=DEFAULT_MAX_FRAMES)
    ing.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    cl = sub.add_parser("clips", help="detect key moments and cut highlight clips")
    cl.add_argument("video")
    cl.add_argument("--out", required=True)
    cl.add_argument("--top", type=int, default=5)
    cl.add_argument("--pre", type=float, default=4.0)
    cl.add_argument("--post", type=float, default=4.0)
    cl.add_argument("--scene", type=float, default=0.3)
    cl.add_argument("--width", type=int, default=None)
    tr = sub.add_parser("transcribe", help="transcribe an audio or video file with Muse Voice Transcribe")
    tr.add_argument("audio")
    tr.add_argument("--mode", default="ENDPOINTING", choices=["PUSH_TO_TALK", "ENDPOINTING", "DIARIZATION"])
    tr.add_argument("--keyword", action="append", default=[])
    co = sub.add_parser("coach", help="ask Coach something (text in, text out, optional voice)")
    co.add_argument("text")
    co.add_argument("--context", default="")
    co.add_argument("--speak", action="store_true")
    pl = sub.add_parser("play", help="one Coach agent turn with tools (video, clips, memory, voice)")
    pl.add_argument("text")
    pl.add_argument("--video", default=None)
    pl.add_argument("--work", default="coach_work")
    pl.add_argument("--match", default="current match")
    pl.add_argument("--speak", action="store_true")
    return ap


def _client() -> MetaClient:
    return MetaClient(load_settings())


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = _parser()
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 64
    if args.cmd == "health":
        code, text = health_report()
        print(text)
        return code
    if args.cmd == "ingest":
        try:
            info, frames = sample_frames(args.video, args.out, args.every, args.max, args.width)
        except IngestError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"duration_s": info.duration_s, "fps": info.fps,
                          "frames": len(frames), "out": args.out}))
        return 0
    if args.cmd == "clips":
        try:
            info, windows, files = cut_highlights(args.video, args.out, args.top, args.pre,
                                                  args.post, args.scene, args.width)
        except (IngestError, MomentError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"duration_s": info.duration_s, "clips": len(files),
                          "windows": [[w.start, w.end] for w in windows], "out": args.out}))
        return 0
    if args.cmd == "transcribe":
        import tempfile
        from pathlib import Path
        try:
            with tempfile.TemporaryDirectory() as td:
                wav = to_wav_24k(args.audio, Path(td) / "in.wav")
                t = transcribe_file(_client(), wav, args.mode, args.keyword or None)
        except (VoiceError, MetaAPIError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"transcript": t.text, "audio_ms": t.audio_ms,
                          "turns": [[x.start_ms, x.end_ms, x.text, x.speaker] for x in t.turns]}))
        return 0
    if args.cmd == "coach":
        try:
            r = coach_reply(_client(), args.text, args.context)
        except (ValueError, MetaAPIError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(r.text)
        if args.speak:
            speak(r.text)
        return 0
    if args.cmd == "play":
        from pathlib import Path
        work = Path(args.work)
        try:
            client = _client()
            session = Session(work_dir=work, memory=MatchMemory(work / "memory.json"), match=args.match,
                              video=args.video, client=client, speak_out_loud=args.speak)
            r = CoachAgent(client, session).turn(args.text)
        except (ValueError, MetaAPIError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        for c in r.tool_calls:
            print(f"[tool] {c['name']}({c['arguments']}) -> {c['output'][:200]}")
        print(r.text)
        if args.speak and r.text:
            speak(r.text)
        print(json.dumps({"rounds": r.rounds, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens}), file=sys.stderr)
        return 0
    print("usage: python -m muse_replay {health,ingest,clips,transcribe,coach,play} ...", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
