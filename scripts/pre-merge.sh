#!/usr/bin/env bash
# Pre-merge gate: run before every merge to main. The exit code is the verdict.
# Full test suite with ffmpeg required and no skips allowed, then the em dash check.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"
if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; elif [ -x .venv/bin/python ]; then PY=.venv/bin/python; fi
ffmpeg -version | head -1
LOG="${TMPDIR:-/tmp}/coach-pytest.log"
set +e
REQUIRE_FFMPEG=1 "$PY" -m pytest -q -rs -p no:cacheprovider 2>&1 | tee "$LOG"
status=${PIPESTATUS[0]}
set -e
test "$status" -eq 0
if grep -qE "skipped|SKIPPED" "$LOG"; then
  echo "pre-merge: a test was skipped; that counts as a failure here" >&2
  exit 1
fi
bash scripts/check-no-dashes.sh
echo "pre-merge: OK"
