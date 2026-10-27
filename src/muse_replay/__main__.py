"""Command line entry point: python -m muse_replay health"""

from __future__ import annotations

import sys

from .health import health_report


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] != ["health"]:
        print("usage: python -m muse_replay health", file=sys.stderr)
        return 64
    code, text = health_report()
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
