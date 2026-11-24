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

if command -v labwc >/dev/null; then
  read -r _ LABWC_VERSION _ <<< "$(labwc --version)"
  if dpkg --compare-versions "$LABWC_VERSION" ge 0.8.4; then
    sudo apt install -y --no-install-recommends swayidle wtype
    if python3 - <<'PY'
import os
import shutil
import sys
import tempfile
from pathlib import Path
from xml.dom import Node, minidom

config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
config_dirs = (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":")
config = config_home / "labwc/rc.xml"
system_configs = [Path(directory) / "labwc/rc.xml" for directory in config_dirs if directory]
system_configs = [path for path in system_configs if path.is_file()]
shortcut = "A-W-h"
marker = " Photobooth cursor shortcut "

def bindings(document):
    return [
        node for node in document.getElementsByTagNameNS("*", "keybind")
        if sorted(node.getAttribute("key").lower().split("-")) == ["a", "h", "w"]
    ]

def hides_cursor(binding):
    actions = [node for node in binding.childNodes if node.nodeType == Node.ELEMENT_NODE]
    return (
        len(actions) == 1
        and actions[0].localName == "action"
        and actions[0].getAttribute("name").lower() == "hidecursor"
    )

if config.is_symlink():
    sys.exit(f"Labwc cursor setup requires a regular configuration file at {config}.")

# Start with the system settings when creating a user override, including on
# labwc sessions that run without --merge-config.
source = config if config.exists() else next(iter(system_configs), None)
document = minidom.parse(str(source)) if source else minidom.parseString("<labwc_config/>")
root = document.documentElement
if root.localName not in {"labwc_config", "openbox_config"}:
    sys.exit(f"Unrecognized labwc configuration in {source}.")

existing = bindings(document)
if any(not hides_cursor(binding) for binding in existing):
    sys.exit(f"The {shortcut} shortcut is already in use in {source}.")
if not existing:
    for path in system_configs:
        if any(not hides_cursor(binding) for binding in bindings(minidom.parse(str(path)))):
            sys.exit(f"The {shortcut} shortcut is already in use in {path}.")

def new_element(name):
    qualified_name = f"{root.prefix}:{name}" if root.prefix else name
    return document.createElementNS(root.namespaceURI, qualified_name)

if existing:
    binding = existing[0]
else:
    keyboard = next(
        (node for node in root.childNodes if node.nodeType == Node.ELEMENT_NODE and node.localName == "keyboard"),
        None,
    )
    if keyboard is None:
        keyboard = root.appendChild(new_element("keyboard"))
    binding = keyboard.appendChild(new_element("keybind"))
    binding.setAttribute("key", shortcut)
    action = binding.appendChild(new_element("action"))
    action.setAttribute("name", "HideCursor")

has_marker = any(node.nodeType == Node.COMMENT_NODE and node.data == marker for node in binding.childNodes)
if not has_marker:
    binding.insertBefore(document.createComment(marker), binding.firstChild)

if not has_marker or source != config:
    config.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=config.parent) as temp_dir:
        pending = Path(temp_dir) / config.name
        pending.write_bytes(document.toxml(encoding="UTF-8") + b"\n")
        if config.exists():
            shutil.copymode(config, pending)
        pending.replace(config)
PY
    then
      echo "Labwc cursor hiding is configured. Restart the desktop session to activate it."
    else
      echo "Labwc cursor setup was skipped. The Wayland kiosk page can still hide its pointer." >&2
    fi
  fi
fi

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
