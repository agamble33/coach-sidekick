"""Command line entry point.

python -m muse_replay health
python -m muse_replay ingest VIDEO --out DIR [--every 2] [--max 120] [--width 768]
python -m muse_replay clips VIDEO --out DIR [--top 5] [--pre 4] [--post 4] [--scene 0.3]
"""

from __future__ import annotations

import argparse
import json
import sys

from .health import health_report
from .clips import cut_highlights
from .ingest import DEFAULT_EVERY_S, DEFAULT_MAX_FRAMES, DEFAULT_WIDTH, IngestError, sample_frames
from .moments import MomentError


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
    return ap


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
    print("usage: python -m muse_replay {health,ingest,clips} ...", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
