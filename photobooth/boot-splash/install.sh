#!/usr/bin/env bash
set -euo pipefail

SPLASH_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
CMDLINE=/boot/firmware/cmdline.txt
THEME_DIR=/usr/share/plymouth/themes/photobooth
PREVIOUS_THEME=/etc/plymouth/photobooth-previous-theme
LABWC_AUTOSTART=/etc/xdg/labwc/autostart
KIOSK_HOOK="$CONFIG_DIR/labwc/photobooth-kiosk"

if [[ ! -f "$CMDLINE" ]] || ! command -v raspi-config >/dev/null || ! raspi-config nonint is_pi; then
  exit 0
fi

sudo apt install -y --no-install-recommends plymouth initramfs-tools
current_theme="$(sudo plymouth-set-default-theme)"
if [[ "$current_theme" != photobooth && ! -e "$PREVIOUS_THEME" ]]; then
  printf '%s\n' "$current_theme" | sudo tee "$PREVIOUS_THEME" >/dev/null
fi
sudo install -D -m 0644 -t "$THEME_DIR" \
  "$SPLASH_DIR/photobooth.plymouth" "$SPLASH_DIR/photobooth.script" "$SPLASH_DIR/splash.png"
sudo plymouth-set-default-theme --rebuild-initrd photobooth
if ! grep -Eq '(^|[[:space:]])splash([[:space:]]|$)' "$CMDLINE"; then
  sudo raspi-config nonint do_boot_splash 0
fi
echo "Photo Booth boot splash installed. Reboot to activate it."

if ! command -v labwc >/dev/null || [[ ! -f "$LABWC_AUTOSTART" || -L "$LABWC_AUTOSTART" ]]; then
  exit 0
fi
if [[ -e "$KIOSK_HOOK" && ! -L "$KIOSK_HOOK" ]]; then
  echo "Labwc kiosk startup was skipped because $KIOSK_HOOK is already in use." >&2
  exit 0
fi

pending="$(mktemp)"
trap 'rm -f -- "$pending"' EXIT
if ! python3 - "$LABWC_AUTOSTART" > "$pending" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
hook = '''kiosk_start="${XDG_CONFIG_HOME:-$HOME/.config}/labwc/photobooth-kiosk"
if [ -x "$kiosk_start" ]; then
  "$kiosk_start"
fi
'''
desktop_commands = (
    "/usr/bin/lwrespawn /usr/bin/pcmanfm-pi &",
    "/usr/bin/lwrespawn /usr/bin/wf-panel-pi &",
)

# Accept the stock setup and the previously documented manual setup.
original = path.read_text().replace(hook, "", 1)
lines = original.splitlines()
if "photobooth-kiosk" in original or any(lines.count(command) != 1 for command in desktop_commands):
    sys.exit(f"Labwc kiosk startup was skipped because {path} has a different layout.")

before_kiosk = "\n".join(line for line in lines if line not in desktop_commands).rstrip("\n")
print(f"{before_kiosk}\n\n{hook}\n" + "\n".join(desktop_commands))
PY
then
  exit 0
fi
sh -n "$pending"
sudo apt install -y --no-install-recommends swaybg
if ! cmp -s "$LABWC_AUTOSTART" "$pending"; then
  if [[ ! -e "$LABWC_AUTOSTART.before-photobooth" ]]; then
    sudo cp -p "$LABWC_AUTOSTART" "$LABWC_AUTOSTART.before-photobooth"
  fi
  sudo install -m 0644 "$pending" "$LABWC_AUTOSTART.photobooth-$$"
  sudo mv -T "$LABWC_AUTOSTART.photobooth-$$" "$LABWC_AUTOSTART"
fi

mkdir -p "$CONFIG_DIR/labwc"
ln -sfnT "$SPLASH_DIR/launch-labwc-kiosk.sh" "$KIOSK_HOOK"
echo "Labwc will show the splash until Chromium opens. Exit the kiosk to start the desktop."
