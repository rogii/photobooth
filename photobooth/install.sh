#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"

sudo apt update
sudo apt install -y python3 python3-tk python3-venv python3-lgpio python3-gpiozero gphoto2
python3 -m venv --system-site-packages "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

mkdir -p "$USER_HOME/.config/autostart"
cat > "$USER_HOME/.config/autostart/photobooth.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Photobooth
Comment=Start the photobooth kiosk
Exec=$APP_DIR/.venv/bin/python $APP_DIR/app.py
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
chown -R "$USER_NAME":"$USER_NAME" "$USER_HOME/.config/autostart"

echo "Installation klar. Starta om Raspberry Pi eller kör: $APP_DIR/.venv/bin/python $APP_DIR/app.py"
echo "Koppla in kameran och prova: gphoto2 --capture-preview --filename /tmp/preview.jpg"
