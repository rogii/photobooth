#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ "$EUID" -eq 0 ]]; then
  echo "Run install.sh as the desktop user, without sudo." >&2
  exit 1
fi
USER_NAME="$(id -un)"
USER_HOME="$HOME"

sudo apt update
sudo apt install -y python3 python3-venv python3-lgpio python3-gpiozero gphoto2 chromium
# The kiosk launcher manages unclutter instead of using Debian's session-wide autostart.
sudo apt install -y --no-install-recommends unclutter-xfixes

if ! getent group gpio >/dev/null; then
  sudo groupadd --system gpio
fi
GPIO_GID="$(getent group gpio | cut -d: -f3)"
GPIO_RELOGIN_REQUIRED=false
if ! id -G | tr ' ' '\n' | grep -Fxq "$GPIO_GID"; then
  GPIO_RELOGIN_REQUIRED=true
fi
sudo usermod -aG gpio "$USER_NAME"

sudo tee /etc/udev/rules.d/99-photobooth-gpio.rules >/dev/null <<'EOF'
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"
KERNEL=="gpiomem*", GROUP="gpio", MODE="0660"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=gpio
for GPIO_DEVICE in /dev/gpiochip* /dev/gpiomem*; do
  [[ -e "$GPIO_DEVICE" ]] || continue
  sudo chgrp gpio "$GPIO_DEVICE"
  sudo chmod 0660 "$GPIO_DEVICE"
done

python3 -m venv --system-site-packages "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

"$APP_DIR/install-service.sh"

echo "Installation klar. Tjänst: systemctl --user restart photobooth"
echo "Kiosk: $APP_DIR/launch-kiosk.sh · Webbadress: http://127.0.0.1:8080"
if [[ "$GPIO_RELOGIN_REQUIRED" == true ]]; then
  echo "GPIO access is configured for $USER_NAME. Reboot the Pi so the user service receives the new gpio group membership."
fi
