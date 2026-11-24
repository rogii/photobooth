import os
import shutil
import struct
import tempfile
from pathlib import Path


THEME = "PhotoboothHidden"
SETTING = f"# Photobooth touchscreen cursor\nXCURSOR_THEME={THEME}\n"
IMAGE_TYPE = 0xFFFD0002
CURSOR_SIZE = 24


def install_theme(home):
    theme = home / ".icons" / THEME
    cursors = theme / "cursors"
    cursors.mkdir(parents=True, exist_ok=True)
    (theme / "index.theme").write_text("[Icon Theme]\nName=Photobooth Hidden\n")

    # Xcursor header, table of contents, one image header, and one transparent ARGB pixel.
    cursor = struct.pack(
        "<4s16I",
        b"Xcur", 16, 0x10000, 1,
        IMAGE_TYPE, CURSOR_SIZE, 28,
        36, IMAGE_TYPE, CURSOR_SIZE, 1, 1, 1, 0, 0, 0,
        0,
    )
    (cursors / "left_ptr").write_bytes(cursor)

    # Match the cursor shape names and legacy aliases that local applications use.
    names = {path.name for path in Path("/usr/share/icons").glob("*/cursors/*")}
    names.update(("default", "arrow", "pointer", "text", "hand1", "hand2", "xterm"))
    for name in sorted(names - {"left_ptr"}):
        try:
            (cursors / name).symlink_to("left_ptr")
        except FileExistsError:
            pass


def set_cursor_theme(config_directory):
    environment = config_directory / "labwc" / "environment"
    environment.parent.mkdir(parents=True, exist_ok=True)
    if environment.is_symlink():
        raise SystemExit(f"Labwc cursor setup requires a regular file at {environment}.")
    current = environment.read_text() if environment.exists() else ""
    settings = current.replace(SETTING, "")
    separator = "\n" if settings and not settings.endswith("\n") else ""
    updated = settings + separator + SETTING
    if updated != current:
        with tempfile.TemporaryDirectory(dir=environment.parent) as temp_dir:
            pending = Path(temp_dir) / environment.name
            pending.write_text(updated)
            if environment.exists():
                shutil.copymode(environment, pending)
            pending.replace(environment)
        print("Labwc cursor hidden for the desktop user. Restart the desktop session to activate it.")


if __name__ == "__main__":
    home = Path.home()
    install_theme(home)
    set_cursor_theme(Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config"))
