#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ "$EUID" -eq 0 ]]; then
  echo "Run install.sh as the desktop user, without sudo." >&2
  exit 1
fi
USER_NAME="$USER"
USER_HOME="$HOME"

sudo apt update
sudo apt install -y python3 python3-venv python3-lgpio python3-gpiozero gphoto2 chromium
python3 -m venv --system-site-packages "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

"$APP_DIR/install-service.sh"

echo "Installation klar. Tjänst: systemctl --user restart photobooth"
echo "Kiosk: $APP_DIR/launch-kiosk.sh · Webbadress: http://127.0.0.1:8080"
