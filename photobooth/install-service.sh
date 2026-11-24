#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_HOME="$HOME"
USER_ID="$(id -u)"
USER_NAME="$(id -un)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$USER_ID}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

# Allow the user service to configure Wi-Fi even without an active desktop login.
sudo tee /etc/polkit-1/rules.d/49-photobooth-wifi.rules >/dev/null <<EOF
polkit.addRule(function(action, subject) {
    if (subject.user === "$USER_NAME" && [
        "org.freedesktop.NetworkManager.network-control",
        "org.freedesktop.NetworkManager.settings.modify.system",
        "org.freedesktop.NetworkManager.wifi.scan",
        "org.freedesktop.NetworkManager.wifi.share.protected"
    ].indexOf(action.id) !== -1) {
        return polkit.Result.YES;
    }
});
EOF

# Prevent the desktop from claiming the camera through D-Bus activation.
systemctl --user mask --now gvfs-gphoto2-volume-monitor.service

SERVICE_DIR="$USER_HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@USER_HOME@|$USER_HOME|g" \
  "$APP_DIR/photobooth.service.in" > "$SERVICE_DIR/photobooth.service"

AUTOSTART_DIR="${XDG_CONFIG_HOME:-$USER_HOME/.config}/autostart"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$USER_HOME/.local/share}/applications"
DESKTOP_DIR="$USER_HOME/Desktop"
if command -v xdg-user-dir >/dev/null; then
  DESKTOP_DIR="$(xdg-user-dir DESKTOP)"
fi

# Exec is quoted first for the launcher, then escaped for the desktop entry file.
KIOSK_EXEC="$APP_DIR/launch-kiosk.sh"
KIOSK_EXEC=${KIOSK_EXEC//\\/\\\\}
KIOSK_EXEC=${KIOSK_EXEC//\"/\\\"}
KIOSK_EXEC=${KIOSK_EXEC//\$/\\\$}
KIOSK_EXEC=${KIOSK_EXEC//\`/\\\`}
KIOSK_EXEC=${KIOSK_EXEC//\\/\\\\}
KIOSK_EXEC=${KIOSK_EXEC//%/%%}

mkdir -p "$AUTOSTART_DIR" "$APPLICATIONS_DIR"
KIOSK_ENTRY="$APPLICATIONS_DIR/photobooth.desktop"
cat > "$KIOSK_ENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=Photobooth Kiosk
Comment=Open the photobooth kiosk browser
Exec="$KIOSK_EXEC"
Icon=camera-photo
Terminal=false
Categories=Graphics;Photography;
EOF
install -m 0644 "$KIOSK_ENTRY" "$AUTOSTART_DIR/photobooth.desktop"
if [[ -n "$DESKTOP_DIR" && "${DESKTOP_DIR%/}" != "${USER_HOME%/}" ]]; then
  install -D -m 0755 "$KIOSK_ENTRY" "$DESKTOP_DIR/photobooth.desktop"
fi

systemctl --user daemon-reload
systemctl --user enable --now photobooth.service

printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl reboot\n' "$USER_NAME" \
  | sudo tee /etc/sudoers.d/photobooth-poweroff >/dev/null
sudo chmod 0440 /etc/sudoers.d/photobooth-poweroff
sudo visudo -c -f /etc/sudoers.d/photobooth-poweroff

echo "Photobooth service installed and started. Restart with: systemctl --user restart photobooth"
