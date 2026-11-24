#!/usr/bin/env bash
set -euo pipefail

SPLASH_DIR="$(dirname "$(realpath "$0")")"
BACKGROUND_PID=""

cleanup() {
  if [[ -n "$BACKGROUND_PID" ]]; then
    kill "$BACKGROUND_PID" 2>/dev/null || true
    wait "$BACKGROUND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

if command -v swaybg >/dev/null; then
  swaybg -c 080b0d -i "$SPLASH_DIR/splash.png" -m fit &
  BACKGROUND_PID=$!
fi

"$SPLASH_DIR/../launch-kiosk.sh"
