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
sudo apt install -y python3 python3-venv python3-lgpio python3-gpiozero gphoto2 chromium bluez python3-evdev rfkill network-manager dnsmasq-base polkitd python3-dbus avahi-daemon
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

if ! getent group photobooth-bluetooth >/dev/null; then
  sudo groupadd --system photobooth-bluetooth
fi
BLUETOOTH_GID="$(getent group photobooth-bluetooth | cut -d: -f3)"
BLUETOOTH_RELOGIN_REQUIRED=false
if ! id -G | tr ' ' '\n' | grep -Fxq "$BLUETOOTH_GID"; then
  BLUETOOTH_RELOGIN_REQUIRED=true
fi
sudo usermod -aG photobooth-bluetooth "$USER_NAME"
sudo /usr/sbin/rfkill unblock bluetooth
sudo systemctl enable --now bluetooth.service

# Photobooth handles pairing through BlueZ. The desktop widget opens a modal
# connection dialog that a kiosk without a mouse or keyboard cannot dismiss.
python3 - /etc/xdg/wf-panel-pi/wf-panel-pi.ini \
  "${XDG_CONFIG_HOME:-$USER_HOME/.config}/wf-panel-pi/wf-panel-pi.ini" <<'PY'
import re
import sys
import tempfile
from pathlib import Path

default_path, panel_path = map(Path, sys.argv[1:])
if not default_path.is_file():
    sys.exit(0)

defaults = default_path.read_text()
config = panel_path.read_text() if panel_path.exists() else ""
updated = config
for section in ("panel", "dock"):
    section_pattern = re.compile(
        rf"^\[{section}\][ \t]*(?:\n|\Z)(.*?)(?=^\[[^\]\n]+\][ \t]*$|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    system_section = section_pattern.search(defaults)
    user_section = section_pattern.search(updated)
    user_settings = user_section[1] if user_section else ""
    settings = user_settings
    for key in ("widgets_left", "widgets_right"):
        widget_pattern = rf"^([ \t]*{key}[ \t]*=[ \t]*)([^\n]*)"
        user_widgets = re.search(widget_pattern, settings, re.MULTILINE)
        default_widgets = re.search(widget_pattern, system_section[1], re.MULTILINE) if system_section else None
        widget_list = user_widgets or default_widgets
        if not widget_list:
            continue
        widgets = widget_list[2].split()
        if "bluetooth" not in widgets:
            continue
        line = widget_list[1] + " ".join(widget for widget in widgets if widget != "bluetooth")
        if user_widgets:
            settings = settings[:user_widgets.start()] + line + settings[user_widgets.end():]
        else:
            settings = line + "\n" + settings
    if settings != user_settings:
        if user_section:
            start, end = user_section.span(1)
            separator = "" if updated[:start].endswith("\n") else "\n"
            updated = updated[:start] + separator + settings + updated[end:]
        else:
            separator = "\n" if updated.endswith("\n") else "\n\n"
            updated = (updated + separator if updated else "") + f"[{section}]\n" + settings

if updated != config:
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=panel_path.parent) as temp_dir:
        pending = Path(temp_dir) / panel_path.name
        pending.write_text(updated)
        pending.replace(panel_path)
    print("Desktop Bluetooth widget disabled. Restart the desktop session if it is already running.")
PY

sudo tee /etc/udev/rules.d/99-photobooth-bluetooth.rules >/dev/null <<'EOF'
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{id/bustype}=="0005", ENV{ID_INPUT_KEY}=="1", GROUP="photobooth-bluetooth", MODE="0660"
EOF

sudo tee /etc/udev/rules.d/99-photobooth-gpio.rules >/dev/null <<'EOF'
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"
KERNEL=="gpiomem*", GROUP="gpio", MODE="0660"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=gpio
sudo udevadm trigger --subsystem-match=input
for GPIO_DEVICE in /dev/gpiochip* /dev/gpiomem*; do
  [[ -e "$GPIO_DEVICE" ]] || continue
  sudo chgrp gpio "$GPIO_DEVICE"
  sudo chmod 0660 "$GPIO_DEVICE"
done

python3 -m venv --system-site-packages "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

"$APP_DIR/install-service.sh"

echo "Installation complete. Service: systemctl --user restart photobooth"
echo "Kiosk: $APP_DIR/launch-kiosk.sh · Web address: http://127.0.0.1:8080"
if [[ "$GPIO_RELOGIN_REQUIRED" == true ]]; then
  echo "GPIO access is configured for $USER_NAME. Reboot the Pi so the user service receives the new gpio group membership."
fi
if [[ "$BLUETOOTH_RELOGIN_REQUIRED" == true ]]; then
  echo "Bluetooth input access is configured for $USER_NAME. Reboot the Pi before pairing a selfie button."
fi
