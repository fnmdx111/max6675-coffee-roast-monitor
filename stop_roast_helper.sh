#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/.roast_server.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No PID file found."
  exit 0
fi

PID="$(cat "$PID_FILE")"
if [[ -n "${PID:-}" ]] && kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "Stopped roast helper server (PID $PID)."
else
  echo "Process not running (stale PID file)."
fi

rm -f "$PID_FILE"
