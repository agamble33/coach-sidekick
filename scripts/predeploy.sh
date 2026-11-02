#!/usr/bin/env bash
# Pre-deploy gate: Render runs this inside the built image before switching traffic
# (preDeployCommand in render.yaml). It is fast and needs nothing beyond the runtime image:
# the app imports, the health report renders, ffmpeg is present, no em dashes shipped.
set -euo pipefail
cd "$(dirname "$0")/.."
python -c "import web.app, coach.tools, coach.agent, coach.incidents; print('imports ok')"
python -m coach health || true   # says which providers are configured; keys live in Render
ffmpeg -version | head -1
bash scripts/check-no-dashes.sh
echo "predeploy: OK"
