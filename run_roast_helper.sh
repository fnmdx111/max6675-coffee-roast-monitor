#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/.roast_server.pid"
LOG_FILE="$ROOT_DIR/.roast_server.log"
VENV_PATH="${ROAST_HELPER_VENV:-}"

cd "$ROOT_DIR"

if [[ -n "$VENV_PATH" ]]; then
  if [[ -f "$VENV_PATH/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$VENV_PATH/bin/activate"
  else
    echo "ROAST_HELPER_VENV is set but no activate script found at: $VENV_PATH/bin/activate"
    exit 1
  fi
fi

HOST="127.0.0.1"
PORT="8000"
if [[ -f "$ROOT_DIR/config.json" ]]; then
  HOST_AND_PORT="$(python - <<'PY'
import json
from pathlib import Path
cfg = json.loads(Path('config.json').read_text(encoding='utf-8'))
host = str(cfg.get('host', '0.0.0.0'))
port = int(cfg.get('port', 8000))
print(host, port)
PY
)"
  HOST="${HOST_AND_PORT% *}"
  PORT="${HOST_AND_PORT##* }"
fi

if [[ "$HOST" == "0.0.0.0" ]]; then
  OPEN_HOST="127.0.0.1"
else
  OPEN_HOST="$HOST"
fi

URL="http://${OPEN_HOST}:${PORT}/"

server_running="false"
if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ -n "${OLD_PID:-}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    server_running="true"
  fi
fi

if [[ "$server_running" != "true" ]]; then
  python -u server.py >>"$LOG_FILE" 2>&1 &
  SERVER_PID=$!
  echo "$SERVER_PID" > "$PID_FILE"
else
  SERVER_PID="$(cat "$PID_FILE")"
fi

ready="false"
for _ in {1..40}; do
  if curl -fsS "${URL}api/config" >/dev/null 2>&1; then
    ready="true"
    break
  fi
  sleep 0.25
done

if [[ "$ready" != "true" ]]; then
  echo "Server started (pid $SERVER_PID), but readiness check failed."
  echo "Check logs: $LOG_FILE"
  echo "Try opening: $URL"
  exit 1
fi

if [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
  elif command -v chromium-browser >/dev/null 2>&1; then
    chromium-browser "$URL" >/dev/null 2>&1 &
  elif command -v chromium >/dev/null 2>&1; then
    chromium "$URL" >/dev/null 2>&1 &
  fi
fi

echo "Roast helper is running at: $URL"
echo "Server PID: $SERVER_PID"
echo "Logs: $LOG_FILE"
