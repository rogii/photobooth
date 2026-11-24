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

KIOSK_RUNTIME_DIR="$XDG_RUNTIME_DIR/photobooth-kiosk"
mkdir -p -m 700 "$KIOSK_RUNTIME_DIR"
exec 9>"$KIOSK_RUNTIME_DIR/launcher.lock"
flock -n 9 || exit 0

PROFILE_DIR="$HOME/.config/photobooth-kiosk-chromium"
KIOSK_URL="http://127.0.0.1:8080"
UNCLUTTER_PID=""
if [[ "${XDG_SESSION_TYPE:-}" == wayland || -n "${WAYLAND_DISPLAY:-}" ]]; then
  KIOSK_URL="$KIOSK_URL/?hide_cursor=1"
elif [[ -n "${DISPLAY:-}" ]] && command -v unclutter >/dev/null; then
  unclutter --start-hidden --timeout 1 --hide-on-touch 9>&- &
  UNCLUTTER_PID=$!
fi

cleanup() {
  if [[ -n "$UNCLUTTER_PID" ]]; then
    kill "$UNCLUTTER_PID" 2>/dev/null || true
    wait "$UNCLUTTER_PID" 2>/dev/null || true
  fi
  rm -f "$KIOSK_RUNTIME_DIR/browser.pid"
}
trap cleanup EXIT

"$BROWSER" --kiosk --user-data-dir="$PROFILE_DIR" --no-first-run --noerrdialogs --disable-infobars --disable-session-crashed-bubble --password-store=basic "$KIOSK_URL" 9>&- &
BROWSER_PID=$!
trap 'kill -TERM "$BROWSER_PID" 2>/dev/null || true' TERM INT
printf '%s\n' "$BROWSER_PID" > "$KIOSK_RUNTIME_DIR/browser.pid"

BROWSER_STATUS=0
wait "$BROWSER_PID" || BROWSER_STATUS=$?
if [[ "$BROWSER_STATUS" != 143 ]]; then
  exit "$BROWSER_STATUS"
fi
