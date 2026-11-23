#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_HOME="$HOME"
USER_ID="$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$USER_ID}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

SERVICE_DIR="$USER_HOME/.config/systemd/user"
AUTOSTART_DIR="$USER_HOME/.config/autostart"
mkdir -p "$SERVICE_DIR" "$AUTOSTART_DIR"
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@USER_HOME@|$USER_HOME|g" \
  "$APP_DIR/photobooth.service.in" > "$SERVICE_DIR/photobooth.service"

cat > "$AUTOSTART_DIR/photobooth.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Photobooth
Comment=Open the photobooth kiosk browser
Exec=$APP_DIR/launch-kiosk.sh
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

systemctl --user daemon-reload
systemctl --user enable --now photobooth.service
echo "Photobooth service installed and started. Restart with: systemctl --user restart photobooth"
