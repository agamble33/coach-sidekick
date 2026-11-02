#!/usr/bin/env bash
# House rule: no em dashes anywhere in tracked text. Exit 1 and list the files if any are found.
set -uo pipefail
cd "$(dirname "$0")/.."
if git rev-parse --git-dir >/dev/null 2>&1; then
  files=$(git ls-files)
else
  files=$(find . -type f -not -path "./.venv/*" -not -path "*/node_modules/*" -not -path "./coach_data/*")
fi
hits=$(echo "$files" | grep -v -E "\.(png|jpg|jpeg|gif|mp4|wav|ico|jks|woff2?)$" | xargs grep -l $'\xe2\x80\x94' 2>/dev/null || true)
if [ -n "$hits" ]; then
  echo "em dashes found in:"
  echo "$hits"
  exit 1
fi
echo "no em dashes"
