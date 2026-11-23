#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BROWSER="$(command -v chromium || command -v chromium-browser || true)"
if [[ -z "$BROWSER" ]]; then
  echo "Chromium was not found. Install it with: sudo apt install chromium" >&2
  exit 1
fi

USER_ID="$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$USER_ID}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
systemctl --user start photobooth.service

READY=0
for _ in {1..60}; do
  if "$APP_DIR/.venv/bin/python" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/api/state", timeout=0.3)' >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.25
done
if [[ "$READY" != 1 ]]; then
  echo "Photobooth service did not start. Check: journalctl --user -u photobooth -n 50" >&2
  exit 1
fi

"$BROWSER" --kiosk --no-first-run --noerrdialogs --disable-infobars --disable-session-crashed-bubble http://127.0.0.1:8080
