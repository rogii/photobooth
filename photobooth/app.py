#!/usr/bin/env python3
"""Local photobooth web server for Raspberry Pi and browser based UI testing."""

from __future__ import annotations

import argparse
import hmac
import io
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_file, send_from_directory, session
from PIL import Image, ImageDraw, ImageOps

from selfie_button import SelfieButton
from wifi import Wifi

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
DATA = Path(os.environ.get("PHOTOBOOTH_DATA", Path.home() / "Photobooth"))
SESSIONS = DATA / "sessions"
UPLOAD_QUEUE = DATA / "upload-queue"
LAST_SESSION = DATA / "last-session.json"
DISPLAY_FILE = DATA / "latest-display.jpg"
NEXT_DISPLAY_FILE = DATA / "latest-display-next.jpg"
LOCKED_SESSION = DATA / "locked-session.json"
ADMIN_PORT = 8081
SERVER_INSTANCE_ID = uuid.uuid4().hex
ACCENT_COLORS = {
    "green": "#e2fa83",
    "blue": "#78baff",
    "teal": "#5fe1d0",
    "purple": "#c3a0ff",
    "bright pink": "#ff62cb",
    "red": "#ff7878",
    "orange": "#ffab60",
    "yellow": "#ffdf68",
}
DEFAULT_ACCENT = "green"
FOOTER_LOGO_UPLOAD_LIMIT = 2 * 1024 * 1024


def exit_kiosk_browser():
    if not hasattr(os, "pidfd_open"):
        raise RuntimeError("The kiosk browser launcher is only available on Linux.")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    profile = Path.home() / ".config" / "photobooth-kiosk-chromium"
    try:
        pid = int((runtime / "photobooth-kiosk" / "browser.pid").read_text())
        if pid <= 1:
            raise ValueError("Invalid browser PID")
        fd = os.pidfd_open(pid)
        try:
            process = Path(f"/proc/{pid}")
            args = (process / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
            profile_arg = os.fsencode(f"--user-data-dir={profile}")
            kiosk_args = b"--kiosk" in args and profile_arg in args
            if len(args) == 1 and (process / "exe").resolve().name in {"chromium", "chromium-browser"}:
                # Chromium can rewrite argv as a single process title.
                title = b" " + args[0] + b" "
                kiosk_args = b" --kiosk " in title and b" " + profile_arg + b" " in title
            if not kiosk_args:
                raise ValueError("Kiosk browser arguments did not match")
            signal.pidfd_send_signal(fd, signal.SIGTERM)
        finally:
            os.close(fd)
    except (OSError, ValueError) as exc:
        raise RuntimeError("No kiosk browser can be closed. Start it with launch-kiosk.sh.") from exc


def read_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


class PhotoboothService:
    def __init__(self, demo=False, manage_wifi=False):
        self.config = read_config()
        self.config.setdefault("capture_lead_seconds", 1.2)
        self.config.setdefault("admin_pin", "1234")
        self.config.setdefault("idle_photo_wall_columns", 3)
        self.demo = demo
        self.camera_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.camera_available = bool(demo)
        self.camera_error = "" if demo else "Checking camera connection…"
        self.stop_event = threading.Event()
        self.wifi = Wifi(self.stop_event, enabled=manage_wifi and not demo)
        self.busy = False
        self.status = "Choose or create a session"
        self.countdown = ""
        self.session = None
        self.selfie_connected = False
        self.selfie_seen = False
        self.last_session = self._read_last_session()
        self.locked_session = self._read_session_file(LOCKED_SESSION)
        if self.locked_session:
            self.session = dict(self.locked_session)
            self.last_session = dict(self.locked_session)
            self.status = f"Session ready · {self.session['name']}"
        self.flash = None
        self.flash_available = False
        self.recent_photo = None
        self.recent_photo_version = ""
        self.recent_photo_time = None
        self.phase = "idle"
        self.photo_number = 0
        self.photo_total = 0
        self.photo_wall_revision = 0
        self.capture_generation = 0
        self.host_info_lock = threading.Lock()
        self.internet_checked_at = 0.0
        self.internet_connected = False

        self.footer_logo_dir = DATA / "footer-logos"
        self.footer_logo_marker = self.footer_logo_dir / ".active"
        self.active_footer_logo = None
        try:
            self.active_footer_logo = self.footer_logo_path(self.footer_logo_marker.read_text().strip()).name
        except (OSError, ValueError):
            pass

        DATA.mkdir(parents=True, exist_ok=True)
        SESSIONS.mkdir(parents=True, exist_ok=True)
        UPLOAD_QUEUE.mkdir(parents=True, exist_ok=True)
        self.selfie_button = SelfieButton(
            DATA / ".selfie-button", self.stop_event, self.set_selfie_connection,
            self.capture_from_selfie_button, enabled=not self.demo,
        )
        self._init_gpio()
        if not self.demo:
            threading.Thread(target=self.camera_health_worker, daemon=True, name="camera-health").start()
        threading.Thread(target=self.upload_worker, daemon=True, name="upload-queue").start()

    def set_selfie_connection(self, connected):
        with self.state_lock:
            self.selfie_connected = connected
            if connected and self.session:
                self.selfie_seen = True

    def capture_from_selfie_button(self):
        try:
            delay = max(0, min(30, int(self.config.get("countdown_seconds", 3))))
            self.start_capture(1, delay, 0)
        except (RuntimeError, ValueError):
            # A press during another capture or before session selection is ignored.
            pass

    def camera_health_worker(self):
        """Keep checking the camera so the kiosk can recover after USB reconnects."""
        while not self.stop_event.is_set():
            command = self.config.get("camera_command", "gphoto2")
            available = False
            error = ""
            if not shutil.which(command):
                error = f"Cannot find {command}; install gPhoto2."
            elif self.camera_lock.acquire(timeout=0.2):
                try:
                    result = subprocess.run(
                        [command, "--summary"], capture_output=True, text=True, timeout=8
                    )
                    available = result.returncode == 0
                    if not available:
                        error = (result.stderr or result.stdout or "Camera did not respond.").strip()[-400:]
                except (OSError, subprocess.TimeoutExpired) as exc:
                    error = str(exc) or "Camera did not respond."
                finally:
                    self.camera_lock.release()
            else:
                self.stop_event.wait(2)
                continue
            with self.state_lock:
                self.camera_available = available
                self.camera_error = "" if available else error
            self.stop_event.wait(3)

    def _read_last_session(self):
        try:
            value = json.loads(LAST_SESSION.read_text())
            if (SESSIONS / value.get("id", "")).is_dir():
                return value
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        return None

    @staticmethod
    def _read_session_file(path):
        try:
            value = json.loads(path.read_text())
            if (SESSIONS / value.get("id", "")).is_dir():
                return value
        except (OSError, json.JSONDecodeError, TypeError, AttributeError):
            pass
        return None

    def list_sessions(self, include_hidden=False):
        latest = self._read_session_file(LAST_SESSION)
        sessions = []
        for folder in SESSIONS.iterdir():
            if not folder.is_dir():
                continue
            try:
                metadata = json.loads((folder / "session.json").read_text())
            except (OSError, json.JSONDecodeError):
                metadata = {}
            if latest and latest.get("id") == folder.name:
                metadata = {**latest, **metadata}
            try:
                stamp = (folder / "session.json").stat().st_mtime
            except OSError:
                stamp = folder.stat().st_mtime
            try:
                sort_time = datetime.fromisoformat(metadata.get("created_at", "")).timestamp()
            except (TypeError, ValueError):
                sort_time = stamp
            sessions.append({
                "id": folder.name,
                "name": metadata.get("name") or folder.name,
                "created_at": metadata.get("created_at", ""),
                "photo_dir": metadata.get("photo_dir", ""),
                "overlay": metadata.get("overlay", ""),
                "overlay_paused": bool(metadata.get("overlay_paused", False)),
                "sort_time": sort_time,
                "locked": bool(self.locked_session and self.locked_session.get("id") == folder.name),
                "hidden": bool(metadata.get("hidden", False)),
                "active": bool(self.session and self.session.get("id") == folder.name),
            })
        sessions.sort(key=lambda item: item["sort_time"], reverse=True)
        return sessions if include_hidden else [item for item in sessions if not item["hidden"]]

    def host_info(self):
        now = time.monotonic()
        with self.host_info_lock:
            if now - self.internet_checked_at >= 20:
                try:
                    with urllib.request.urlopen("https://connectivitycheck.gstatic.com/generate_204", timeout=2) as response:
                        self.internet_connected = 200 <= response.status < 300
                except (OSError, urllib.error.URLError):
                    self.internet_connected = False
                self.internet_checked_at = time.monotonic()
            try:
                disk = shutil.disk_usage(DATA)
                used = disk.used
                total = disk.total
                free = disk.free
                percent = round(used * 100 / total, 1) if total else 0
            except OSError:
                used = total = free = 0
                percent = 0
            return {
                "disk": {"path": str(DATA), "used_bytes": used, "total_bytes": total, "free_bytes": free, "used_percent": percent},
                "internet_connected": self.internet_connected,
                "hotspot": self.wifi.status["hotspot"],
            }

    @staticmethod
    def session_from_item(item):
        return {key: item[key] for key in ("id", "name", "created_at", "hidden", "photo_dir", "overlay", "overlay_paused") if key in item}

    def footer_logo_path(self, filename):
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".png"):
            raise ValueError("Footer logo not found")
        path = self.footer_logo_dir / filename
        if not path.is_file() or path.is_symlink():
            raise ValueError("Footer logo not found")
        return path

    def list_footer_logos(self):
        return [
            {"id": path.name, "name": path.stem.partition("--")[2] or path.stem}
            for path in sorted(self.footer_logo_dir.glob("*.png"))
            if path.is_file() and not path.is_symlink()
        ]

    def add_footer_logo(self, upload):
        if not upload or not upload.filename:
            raise ValueError("Choose a PNG, JPEG, or WebP logo")
        content = upload.stream.read(FOOTER_LOGO_UPLOAD_LIMIT + 1)
        if len(content) > FOOTER_LOGO_UPLOAD_LIMIT:
            raise ValueError("Choose a logo no larger than 2 MB")
        try:
            with Image.open(io.BytesIO(content), formats=("PNG", "JPEG", "WEBP")) as source:
                if max(source.size) > 4096:
                    raise ValueError("Logo dimensions must be 4096 pixels or smaller")
                logo = ImageOps.exif_transpose(source).convert("RGBA")
                # Fit both the footer and admin preview at 2x pixel density.
                logo.thumbnail((192, 96), Image.Resampling.LANCZOS)
                logo.info.clear()
        except (OSError, Image.DecompressionBombError) as exc:
            raise ValueError("Could not read the logo as a PNG, JPEG, or WebP image") from exc
        name = self.safe_event_name(Path(upload.filename).stem)[:48].strip() or "Logo"
        filename = f"{uuid.uuid4().hex}--{name}.png"
        self.footer_logo_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.footer_logo_dir) as temp_dir:
            pending = Path(temp_dir) / "logo.png"
            logo.save(pending, "PNG")
            pending.replace(self.footer_logo_dir / filename)

    def set_active_footer_logo(self, filename):
        with self.state_lock:
            self._set_active_footer_logo(filename)

    def _set_active_footer_logo(self, filename):
        if filename is None:
            self.footer_logo_marker.unlink(missing_ok=True)
        else:
            self.footer_logo_path(filename)
            with tempfile.TemporaryDirectory(dir=self.footer_logo_dir) as temp_dir:
                pending = Path(temp_dir) / "active"
                pending.write_text(filename, encoding="utf-8")
                pending.replace(self.footer_logo_marker)
        self.active_footer_logo = filename

    def remove_footer_logo(self, filename):
        with self.state_lock:
            path = self.footer_logo_path(filename)
            if filename == self.active_footer_logo:
                self._set_active_footer_logo(None)
            path.unlink()

    def session_overlay_path(self, session):
        if session.get("overlay_paused"):
            return None
        filename = session.get("overlay")
        if filename not in ("overlay.png", "overlay.webp"):
            return None
        return SESSIONS / session["id"] / filename

    def set_session_overlay(self, session_id, upload=None, remove=False):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            folder = SESSIONS / session_id
            if folder.name != session_id or folder.is_symlink() or not folder.is_dir():
                raise ValueError("Session not found")
            item = next((item for item in self.list_sessions(include_hidden=True) if item["id"] == session_id), None)
            if not item:
                raise ValueError("Session not found")
            session = self.session_from_item(item)
            if remove:
                for name in ("overlay.png", "overlay.webp"):
                    (folder / name).unlink(missing_ok=True)
                session.pop("overlay", None)
                session.pop("overlay_paused", None)
            else:
                if not upload or not upload.filename:
                    raise ValueError("Choose a PNG or WebP overlay image")
                suffix = Path(upload.filename).suffix.lower()
                if suffix not in (".png", ".webp"):
                    raise ValueError("Overlay must be a PNG or WebP image")
                filename = "overlay.png" if suffix == ".png" else "overlay.webp"
                temporary = folder / f".{filename}.tmp"
                try:
                    with Image.open(upload.stream) as source:
                        if source.width > 8000 or source.height > 8000:
                            raise ValueError("Overlay dimensions must be 8000 pixels or smaller")
                        image = ImageOps.exif_transpose(source).convert("RGBA")
                        image.save(temporary, format="PNG" if suffix == ".png" else "WEBP", lossless=True)
                except (OSError, Image.DecompressionBombError) as exc:
                    temporary.unlink(missing_ok=True)
                    raise ValueError("Could not read overlay image") from exc
                for name in ("overlay.png", "overlay.webp"):
                    (folder / name).unlink(missing_ok=True)
                temporary.replace(folder / filename)
                session["overlay"] = filename
            (folder / "session.json").write_text(json.dumps(session, ensure_ascii=False, indent=2))
            if self.session and self.session.get("id") == session_id:
                self.session = session
                self.last_session = dict(session)
                LAST_SESSION.write_text(json.dumps(session, ensure_ascii=False, indent=2))
            self.photo_wall_revision += 1
            return session

    def pause_session_overlay(self, session_id, paused):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            folder = SESSIONS / session_id
            if folder.name != session_id or folder.is_symlink() or not folder.is_dir():
                raise ValueError("Session not found")
            item = next((item for item in self.list_sessions(include_hidden=True) if item["id"] == session_id), None)
            if not item:
                raise ValueError("Session not found")
            session = self.session_from_item(item)
            if not session.get("overlay"):
                raise ValueError("This session has no overlay to pause")
            session["overlay_paused"] = bool(paused)
            (folder / "session.json").write_text(json.dumps(session, ensure_ascii=False, indent=2))
            if self.session and self.session.get("id") == session_id:
                self.session = session
                self.last_session = dict(session)
                LAST_SESSION.write_text(json.dumps(session, ensure_ascii=False, indent=2))
            self.photo_wall_revision += 1
            return session

    def make_overlaid_photo(self, photo, session):
        overlay_path = self.session_overlay_path(session)
        if not overlay_path or not overlay_path.is_file():
            return photo
        output_dir = photo.parent / "overlay"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{photo.stem}_overlay.jpg"
        with Image.open(photo) as source, Image.open(overlay_path) as overlay_source:
            base = ImageOps.exif_transpose(source).convert("RGBA")
            overlay = ImageOps.exif_transpose(overlay_source).convert("RGBA")
            if overlay.size != base.size:
                overlay = ImageOps.fit(overlay, base.size, method=Image.Resampling.LANCZOS)
            base.alpha_composite(overlay)
            base.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
        return output

    @staticmethod
    def photo_display_path(photo):
        composite = photo.parent / "overlay" / f"{photo.stem}_overlay.jpg"
        legacy_composite = photo.parent / "overlays" / photo.name
        legacy_marker = legacy_composite.with_suffix(legacy_composite.suffix + ".overlay.json")
        if not composite.is_file() and legacy_composite.is_file() and legacy_marker.is_file():
            composite.parent.mkdir(parents=True, exist_ok=True)
            legacy_composite.replace(composite)
            legacy_marker.unlink(missing_ok=True)
        return composite if composite.is_file() else photo

    def session_photo_dir(self, session):
        directory = session.get("photo_dir", "")
        candidate = DATA / directory if directory and Path(directory).name == directory and directory not in (".", "..") else None
        reserved = {DATA.resolve(), SESSIONS.resolve(), UPLOAD_QUEUE.resolve()}
        if candidate and candidate.resolve().parent == DATA.resolve() and candidate.resolve() not in reserved:
            return candidate
        legacy_name = self.safe_event_name(session["name"])
        if legacy_name in {SESSIONS.name, UPLOAD_QUEUE.name}:
            legacy_name = f"{legacy_name}--legacy-{session['id']}"
        return DATA / legacy_name

    def set_session_hidden(self, session_id, hidden):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            folder = SESSIONS / session_id
            if folder.name != session_id or folder.is_symlink() or not folder.is_dir():
                raise ValueError("Session not found")
            item = next((item for item in self.list_sessions(include_hidden=True) if item["id"] == session_id), None)
            if not item:
                raise ValueError("Session not found")
            session = self.session_from_item(item)
            session["hidden"] = bool(hidden)
            (folder / "session.json").write_text(json.dumps(session, ensure_ascii=False, indent=2))
            return session

    def delete_session(self, session_id):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            folder = SESSIONS / session_id
            if folder.name != session_id or folder.is_symlink() or not folder.is_dir():
                raise ValueError("Session not found")
            item = next((item for item in self.list_sessions(include_hidden=True) if item["id"] == session_id), None)
            if not item:
                raise ValueError("Session not found")
            photo_dir = self.session_photo_dir(item)
            if photo_dir.is_dir() and not photo_dir.is_symlink():
                shutil.rmtree(photo_dir, ignore_errors=True)
            shutil.rmtree(folder)
            for job in UPLOAD_QUEUE.glob("*.json"):
                try:
                    if json.loads(job.read_text()).get("session_id") == session_id:
                        job.unlink(missing_ok=True)
                except (OSError, json.JSONDecodeError):
                    continue
            if self.session and self.session.get("id") == session_id:
                self.session = None
                self.selfie_seen = False
                self.status = "Choose or create a session"
                self.phase = "idle"
            if self.last_session and self.last_session.get("id") == session_id:
                self.last_session = None
                LAST_SESSION.unlink(missing_ok=True)
            if self.locked_session and self.locked_session.get("id") == session_id:
                self.locked_session = None
                LOCKED_SESSION.unlink(missing_ok=True)
            return {"deleted": session_id}

    def session_archive(self, session_id):
        item = next((item for item in self.list_sessions(include_hidden=True) if item["id"] == session_id), None)
        if not item:
            raise ValueError("Session not found")
        folder = self.session_photo_dir(item)
        archive = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
            if folder.is_dir():
                for photo in sorted(folder.rglob("*")):
                    if photo.is_file() and photo.suffix.lower() in (".jpg", ".jpeg"):
                        zipped.write(photo, Path(self.safe_event_name(item["name"])) / photo.relative_to(folder))
        archive.seek(0)
        return item, archive

    def local_admin_photos(self, session_id=None):
        photos = []
        sessions = self.list_sessions(include_hidden=True)
        for item in sessions:
            if session_id and item["id"] != session_id:
                continue
            folder = self.session_photo_dir(item)
            if not folder.is_dir() or folder.is_symlink():
                continue
            for photo in folder.rglob("*"):
                if photo.is_symlink() or not photo.is_file() or photo.suffix.lower() not in (".jpg", ".jpeg"):
                    continue
                relative = photo.relative_to(folder)
                if {part.lower() for part in relative.parts} & {"deleted", "overlay", "overlays", "sequence"}:
                    continue
                try:
                    modified = photo.stat().st_mtime
                except OSError:
                    continue
                photos.append({
                    "session_id": item["id"],
                    "session_name": item["name"],
                    "relative_path": relative.as_posix(),
                    "name": photo.name,
                    "modified": modified,
                })
        photos.sort(key=lambda photo: photo["modified"], reverse=True)
        return sessions, photos

    def local_admin_photo_path(self, session_id, relative_path):
        if not session_id or Path(session_id).name != session_id:
            raise ValueError("Photo not found")
        item = next((entry for entry in self.list_sessions(include_hidden=True) if entry["id"] == session_id), None)
        if not item:
            raise ValueError("Photo not found")
        relative = Path(relative_path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts or "deleted" in {part.lower() for part in relative.parts}:
            raise ValueError("Photo not found")
        root = self.session_photo_dir(item).resolve()
        target = (root / relative).resolve()
        if root not in target.parents or not target.is_file() or target.suffix.lower() not in (".jpg", ".jpeg"):
            raise ValueError("Photo not found")
        return root, target, relative

    def move_local_admin_photos(self, photos):
        groups = {}
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            for entry in photos:
                session_id = str(entry.get("session_id", ""))
                relative_path = str(entry.get("relative_path", ""))
                root, source, relative = self.local_admin_photo_path(session_id, relative_path)
                if len(relative.parts) == 2 and relative.parts[0] == "sequence":
                    base, separator, index = relative.stem.rpartition("_")
                    group_relative = Path(f"{base}{relative.suffix}") if separator and index.isdigit() else relative
                elif len(relative.parts) == 2 and relative.parts[0] == "overlay" and relative.stem.endswith("_overlay"):
                    group_relative = Path(relative.stem.removesuffix("_overlay") + ".jpg")
                else:
                    group_relative = relative
                group_key = (session_id, group_relative.as_posix())
                group = groups.setdefault(group_key, {"root": root, "paths": set()})
                group["paths"].update((relative, group_relative))
                if len(group_relative.parts) == 1 and group_relative.suffix.lower() in (".jpg", ".jpeg"):
                    overlay_relative = Path("overlay") / f"{group_relative.stem}_overlay.jpg"
                    overlay_path = root / overlay_relative
                    if overlay_path.is_file() and not overlay_path.is_symlink():
                        group["paths"].add(overlay_relative)
                    sequence_dir = root / "sequence"
                    if sequence_dir.is_dir():
                        for candidate in sequence_dir.glob(f"{group_relative.stem}_*.jpg"):
                            index = candidate.stem.rpartition("_")[2]
                            if index.isdigit() and candidate.is_file() and not candidate.is_symlink():
                                group["paths"].add(candidate.relative_to(root))

            moved = 0
            for group in groups.values():
                root = group["root"]
                group_moved = False
                for relative in group["paths"]:
                    source = root / relative
                    if not source.is_file() or source.is_symlink():
                        continue
                    if root not in source.resolve().parents:
                        raise ValueError("Invalid photo path")
                    deleted_root = root / "deleted"
                    destination = deleted_root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if deleted_root.resolve() != root / "deleted" or root not in destination.parent.resolve().parents:
                        raise ValueError("Invalid deleted photo path")
                    if destination.exists():
                        index = 1
                        while True:
                            candidate = destination.with_name(f"{destination.stem}__{index}{destination.suffix}")
                            if not candidate.exists():
                                destination = candidate
                                break
                            index += 1
                    shutil.move(str(source), str(destination))
                    group_moved = True
                if group_moved:
                    moved += 1
            if moved:
                self.photo_wall_revision += 1
        return moved

    def _init_gpio(self):
        if self.demo:
            return
        try:
            from gpiozero import DigitalOutputDevice
            self.flash = DigitalOutputDevice(
                int(self.config.get("gpio_flash_pin", 17)),
                active_high=True,
                initial_value=False,
            )
            self.flash_available = True
        except Exception as exc:
            print(f"GPIO flash disabled: {exc}")

    def state(self):
        with self.state_lock:
            session = dict(self.session) if self.session else None
            event_folder = self.session_photo_dir(session) if session else None
            capture_count = len(list(event_folder.glob("*.jpg"))) if event_folder and event_folder.is_dir() else 0
            photo_visible = bool(
                self.recent_photo
                and self.recent_photo_time
                and self.phase == "result"
            )
            photo_wall_version = f"{session['id'] if session else 'none'}:{self.photo_wall_revision}"
            photo_wall_columns = max(1, min(12, int(self.config.get("idle_photo_wall_columns", 3))))
            selfie_configured = bool(self.selfie_button.address)
            selfie_connected = selfie_configured and self.selfie_connected
            return {
                "session": session,
                "last_session": dict(self.last_session) if self.last_session else None,
                "sessions": self.list_sessions(),
                "locked_session": dict(self.locked_session) if self.locked_session else None,
                "busy": self.busy,
                "status": self.status,
                "countdown": self.countdown,
                "recent_photo": photo_visible,
                "recent_photo_version": self.recent_photo_version if photo_visible else "",
                "queued_uploads": len(list(UPLOAD_QUEUE.glob("*.json"))),
                "gallery_upload_configured": bool(self.config.get("upload_url", "").strip()),
                "capture_count": capture_count,
                "flash_available": self.flash_available,
                "selfie_button_connected": selfie_connected,
                "selfie_button_configured": selfie_configured,
                "selfie_button_status": (
                    ("connected" if selfie_connected else "disconnected")
                    if self.selfie_seen and session else None
                ),
                "camera_available": self.camera_available,
                "camera_error": self.camera_error,
                "demo": self.demo,
                "phase": self.phase,
                "photo_number": self.photo_number,
                "photo_total": self.photo_total,
                "photo_wall_version": photo_wall_version,
                "photo_wall_columns": photo_wall_columns,
                "active_footer_logo": self.active_footer_logo,
                "host_info": self.host_info(),
            }

    def photo_wall(self, rows=3):
        event = self.session
        if not event:
            return []
        folder = self.session_photo_dir(event)
        if not folder.is_dir():
            return []
        files = sorted(
            (path for path in folder.glob("*.jpg") if not path.stem.endswith("-sequence-frame")),
            key=lambda path: path.name,
            reverse=True,
        )
        columns = max(1, min(12, int(self.config.get("idle_photo_wall_columns", 3))))
        files = files[:columns * max(1, min(12, int(rows)))]
        result = []
        for path in files:
            display = self.photo_display_path(path)
            relative = display.relative_to(folder).as_posix()
            result.append({"name": path.name, "url": f"/api/photos/{folder.name}/{relative}"})
        return result

    @staticmethod
    def safe_event_name(name):
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip(" .")
        return safe[:80] or "Event"

    def update_config(self, values):
        accent = values.get("accent_color", DEFAULT_ACCENT)
        if not isinstance(accent, str) or accent not in ACCENT_COLORS:
            raise ValueError("Choose an available accent color")
        admin_pin = None
        if "admin_pin" in values:
            admin_pin = str(values["admin_pin"]).strip()
            if len(admin_pin) != 4 or not admin_pin.isascii() or not admin_pin.isdigit():
                raise ValueError("Admin PIN must contain exactly four digits")
        allowed = {"countdown_seconds": (0, 30, int), "sequence_countdown_seconds": (0, 30, int), "capture_lead_seconds": (0, 5, float), "sequence_interval_seconds": (0, 10, float), "idle_photo_wall_columns": (1, 12, int), "result_timeout_seconds": (1, 300, int), "gpio_flash_pin": (0, 27, int), "flash_seconds": (0, 5, float)}
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish before changing settings")
            config = self.config.copy()
            for key, (low, high, cast) in allowed.items():
                if key in values:
                    config[key] = max(low, min(high, cast(values[key])))
            for key in ("camera_command", "upload_url", "upload_token", "key_single", "key_sequence"):
                if key in values:
                    config[key] = str(values[key]).strip()
            if admin_pin is not None:
                config["admin_pin"] = admin_pin
            if "accent_color" in values:
                config["accent_color"] = accent
            try:
                with tempfile.TemporaryDirectory(dir=CONFIG_PATH.parent) as temp_dir:
                    pending_config = Path(temp_dir) / CONFIG_PATH.name
                    pending_config.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
                    pending_config.replace(CONFIG_PATH)
            except OSError as exc:
                raise RuntimeError("Could not save settings to config.json") from exc
            previous_gpio_pin = self.config.get("gpio_flash_pin", 17)
            self.config = config
            if config.get("gpio_flash_pin", 17) != previous_gpio_pin:
                if self.flash:
                    self.flash.close()
                self.flash = None
                self.flash_available = False
                self._init_gpio()
            return {key: config.get(key) for key in values if key != "upload_token"}

    def set_status(self, value):
        with self.state_lock:
            self.status = value

    def set_countdown(self, value):
        with self.state_lock:
            self.countdown = value

    def activate_session(self, selected):
        if not self.session or selected["id"] != self.session["id"]:
            self.selfie_seen = self.selfie_connected
        self.session = selected

    def create_session(self, name):
        if not name or not name.strip():
            raise ValueError("Enter a session name")
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            now = datetime.now()
            self.selfie_seen = self.selfie_connected
            self.session = {
                "id": f"{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
                "name": name.strip(),
                "created_at": now.isoformat(),
                "hidden": False,
            }
            self.session["photo_dir"] = f"{self.safe_event_name(self.session['name'])}--{self.session['id']}"
            self.last_session = dict(self.session)
            self.status = f"Session ready · {self.session['name']}"
            self.session_photo_dir(self.session).mkdir(parents=True, exist_ok=True)
            (SESSIONS / self.session["id"]).mkdir(parents=True, exist_ok=True)
            LAST_SESSION.write_text(json.dumps(self.session, ensure_ascii=False, indent=2))
            (SESSIONS / self.session["id"] / "session.json").write_text(json.dumps(self.session, ensure_ascii=False, indent=2))
            return dict(self.session)

    def select_session(self, session_id, allow_hidden=False):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            folder = SESSIONS / session_id
            if folder.name != session_id or folder.is_symlink() or not folder.is_dir():
                raise ValueError("Session not found")
            item = next((item for item in self.list_sessions(include_hidden=allow_hidden) if item["id"] == session_id), None)
            if not item:
                raise ValueError("Session not found")
            if item["hidden"] and not allow_hidden:
                raise ValueError("This session is hidden from kiosk selection")
            self.activate_session(self.session_from_item(item))
            self.last_session = dict(self.session)
            self.status = f"Session resumed · {self.session['name']}"
            LAST_SESSION.write_text(json.dumps(self.session, ensure_ascii=False, indent=2))
            (folder / "session.json").write_text(json.dumps(self.session, ensure_ascii=False, indent=2))
            return dict(self.session)

    def lock_session(self, session_id=None):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            if session_id:
                folder = SESSIONS / session_id
                if folder.name != session_id or folder.is_symlink() or not folder.is_dir():
                    raise ValueError("Session not found")
                item = next((item for item in self.list_sessions(include_hidden=True) if item["id"] == session_id), None)
                if not item:
                    raise ValueError("Session not found")
                self.locked_session = self.session_from_item(item)
                self.activate_session(dict(self.locked_session))
                self.last_session = dict(self.session)
                LAST_SESSION.write_text(json.dumps(self.session, ensure_ascii=False, indent=2))
                LOCKED_SESSION.write_text(json.dumps(self.locked_session, ensure_ascii=False, indent=2))
                (folder / "session.json").write_text(json.dumps(self.locked_session, ensure_ascii=False, indent=2))
            else:
                self.locked_session = None
                self.session = None
                self.selfie_seen = False
                self.last_session = None
                self.status = "Choose or create a session"
                self.phase = "idle"
                LOCKED_SESSION.unlink(missing_ok=True)
                LAST_SESSION.unlink(missing_ok=True)
            return dict(self.locked_session) if self.locked_session else None

    def stop_session(self):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            self.session = None
            self.selfie_seen = False
            self.last_session = None
            self.locked_session = None
            self.status = "Choose or create a session"
            self.phase = "idle"
            self.recent_photo = None
            self.recent_photo_version = ""
            self.recent_photo_time = None
            LOCKED_SESSION.unlink(missing_ok=True)
            LAST_SESSION.unlink(missing_ok=True)
            return {"stopped": True}

    def resume_session(self):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            if not self.last_session:
                raise ValueError("There is no previous session to resume")
            self.activate_session(dict(self.last_session))
            self.status = f"Session resumed · {self.session['name']}"
            return dict(self.session)

    def start_capture(self, count, delay, interval, sequence_delay=None):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("A capture is already running")
            if not self.session:
                raise RuntimeError("Choose or create a session first")
            self.busy = True
            self.capture_generation += 1
            generation = self.capture_generation
            self.recent_photo = None
            self.recent_photo_version = ""
            self.recent_photo_time = None
            self.status = "Preparing capture"
            self.phase = "countdown"
            self.photo_number = 0
            self.photo_total = count
        threading.Thread(
            target=self.capture_flow,
            args=(count, delay, interval, sequence_delay if sequence_delay is not None else delay, generation),
            daemon=True,
            name="photo-capture",
        ).start()

    def capture_flow(self, count, delay, interval, sequence_delay, generation):
        result_ready = False
        try:
            files = []
            photo_delay = delay if count == 1 else sequence_delay
            for index in range(count):
                with self.state_lock:
                    self.photo_number = index + 1
                    self.photo_total = count
                    self.phase = "countdown"
                capture_result = {}
                capture_thread = None

                def start_camera_capture():
                    nonlocal capture_thread
                    if capture_thread is not None:
                        return

                    def capture_in_background():
                        try:
                            if self.flash:
                                self.flash.on()
                                time.sleep(float(self.config.get("flash_seconds", 0.18)))
                            capture_result["photo"] = self.capture_one(sequence_frame=(count == 4))
                        except Exception as exc:
                            capture_result["error"] = exc
                        finally:
                            if self.flash:
                                self.flash.off()

                    capture_thread = threading.Thread(
                        target=capture_in_background,
                        daemon=True,
                        name="camera-trigger",
                    )
                    capture_thread.start()

                capture_lead = max(0.0, min(5.0, float(self.config.get("capture_lead_seconds", 1.2))))
                if photo_delay > 0:
                    countdown_start = time.monotonic()
                    zero_at = countdown_start + photo_delay + 0.65
                    trigger_at = zero_at - capture_lead
                    for remaining in range(photo_delay, 0, -1):
                        self.set_countdown(str(remaining))
                        tick_at = countdown_start + (photo_delay - remaining + 1)
                        while time.monotonic() < tick_at:
                            now = time.monotonic()
                            if capture_thread is None and now >= trigger_at:
                                start_camera_capture()
                            time.sleep(min(0.025, max(0.001, tick_at - now)))
                    self.set_countdown("SMILE")
                    self.set_status("Smile!")
                    while time.monotonic() < zero_at:
                        now = time.monotonic()
                        if capture_thread is None and now >= trigger_at:
                            start_camera_capture()
                        time.sleep(min(0.025, max(0.001, zero_at - now)))
                else:
                    self.set_countdown("")
                    start_camera_capture()

                if capture_thread is None:
                    start_camera_capture()
                with self.state_lock:
                    self.phase = "capturing"
                    self.status = f"Capturing photo {index + 1} of {count}"
                capture_thread.join()
                if "error" in capture_result:
                    raise capture_result["error"]
                photo = capture_result["photo"]
                files.append(photo)
                if index + 1 < count:
                    time.sleep(interval)
            result = self.make_result(files)
            event_folder = self.session_photo_dir(self.session)
            event_folder.mkdir(parents=True, exist_ok=True)
            if result.parent != event_folder:
                stored = event_folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-strip.jpg"
                shutil.copy2(result, stored)
                result = stored
            if count > 1:
                sequence_folder = event_folder / "sequence"
                sequence_folder.mkdir(parents=True, exist_ok=True)
                for index, photo in enumerate(files, start=1):
                    destination = sequence_folder / f"{result.stem}_{index}{photo.suffix.lower()}"
                    photo.replace(destination)
            session = self.session
            display_result = self.make_overlaid_photo(result, session)
            self.make_display_image(display_result)
            with self.state_lock:
                self.photo_wall_revision += 1
            queued = UPLOAD_QUEUE / f"{session['id']}-{result.name}.json"
            queued.write_text(json.dumps({
                "file": str(result),
                "session_id": session["id"],
                "session_name": session["name"],
                "idempotency_key": uuid.uuid4().hex,
            }))
            with self.state_lock:
                self.recent_photo = DISPLAY_FILE
                self.recent_photo_version = result.name
                self.recent_photo_time = time.monotonic()
                self.status = f"Saved · {result.name}"
                self.phase = "result"
                self.photo_number = 0
                self.photo_total = 0
                result_ready = True
        except Exception as exc:
            with self.state_lock:
                self.camera_available = False
                self.camera_error = str(exc)
            self.set_status(f"Capture failed · {exc}")
        finally:
            if self.flash:
                self.flash.off()
            self.set_countdown("")
            with self.state_lock:
                self.busy = False
            if result_ready:
                timeout = int(self.config.get("result_timeout_seconds", 8))
                time.sleep(max(1, timeout))
            with self.state_lock:
                if generation == self.capture_generation and not self.busy:
                    self.phase = "idle"
                    self.photo_number = 0
                    self.photo_total = 0

    def capture_one(self, sequence_frame=False):
        session = self.session
        folder = self.session_photo_dir(session)
        if sequence_frame:
            folder = folder / "sequence"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.jpg"
        if self.demo:
            self.make_demo_image(path, "DEMO CAPTURE")
            return path
        command = self.config.get("camera_command", "gphoto2")
        if not shutil.which(command):
            raise RuntimeError(f"Cannot find {command}; install gPhoto2")
        with self.camera_lock:
            result = subprocess.run(
                [command, "--capture-image-and-download", "--filename", str(path)],
                capture_output=True,
                text=True,
                timeout=90,
            )
        if result.returncode != 0 or not path.exists():
            raise RuntimeError((result.stderr or result.stdout or "Camera returned no photo").strip()[-400:])
        self.normalize_photo(path)
        return path

    def normalize_photo(self, path):
        """Crop a capture to 16:9 and save it in the same JPEG file."""
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        target_ratio = 16 / 9
        if width / height > target_ratio:
            crop_width = round(height * target_ratio)
            left = (width - crop_width) // 2
            image = image.crop((left, 0, left + crop_width, height))
        else:
            crop_height = round(width / target_ratio)
            top = (height - crop_height) // 2
            image = image.crop((0, top, width, top + crop_height))
        image.save(path, format="JPEG", quality=94, optimize=True)

    def make_result(self, frames):
        if len(frames) == 1:
            return frames[0]
        images = []
        for path in frames:
            with Image.open(path) as source:
                images.append(ImageOps.exif_transpose(source).convert("RGB"))
        tile_sizes = [(max(1, image.width // 2), max(1, image.height // 2)) for image in images]
        tile_w = max(width for width, _ in tile_sizes)
        tile_h = max(height for _, height in tile_sizes)
        canvas = Image.new("RGB", (tile_w * 2, tile_h * 2), "white")
        for index, image in enumerate(images):
            image = image.resize(tile_sizes[index], Image.Resampling.LANCZOS)
            x = (index % 2) * tile_w
            y = (index // 2) * tile_h
            canvas.paste(image, (x, y))
        output = SESSIONS / self.session["id"] / f"{datetime.now().strftime('%H%M%S-%f')}-strip.jpg"
        canvas.save(output, quality=92)
        return output

    def make_display_image(self, path):
        """Create a lightweight screen copy while preserving the original capture."""
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1600, 1000), Image.Resampling.LANCZOS)
        image.save(NEXT_DISPLAY_FILE, format="JPEG", quality=86, optimize=True)
        NEXT_DISPLAY_FILE.replace(DISPLAY_FILE)

    def make_demo_image(self, path, label):
        width, height = 1600, 900
        image = Image.new("RGB", (width, height), (27, 37, 44))
        draw = ImageDraw.Draw(image)
        draw.ellipse((width * .58, -height * .22, width * 1.04, height * .62), fill=(45, 74, 76))
        draw.ellipse((width * .1, height * .35, width * .9, height * 1.4), fill=(76, 77, 69))
        draw.ellipse((width * .38, height * .13, width * .62, height * .52), fill=(203, 161, 124))
        draw.rounded_rectangle((width * .24, height * .48, width * .76, height * 1.2), radius=180, fill=(55, 91, 92))
        draw.rounded_rectangle((28, 28, 395, 90), radius=18, fill=(12, 21, 27))
        draw.text((52, 48), label, fill=(238, 229, 211))
        image.save(path, format="JPEG", quality=88)

    def upload_worker(self):
        while not self.stop_event.is_set():
            endpoint = self.config.get("upload_url", "").strip()
            if endpoint:
                for job in list(UPLOAD_QUEUE.glob("*.json")):
                    try:
                        import urllib.request
                        meta = json.loads(job.read_text())
                        image_path = Path(meta["file"])
                        boundary = uuid.uuid4().hex
                        fields = {key: str(meta[key]) for key in ("session_id", "session_name", "idempotency_key")}
                        chunks = []
                        for key, value in fields.items():
                            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
                        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{image_path.name}\"\r\nContent-Type: image/jpeg\r\n\r\n".encode())
                        chunks.append(image_path.read_bytes())
                        chunks.append(f"\r\n--{boundary}--\r\n".encode())
                        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
                        if self.config.get("upload_token"):
                            headers["Authorization"] = "Bearer " + self.config["upload_token"]
                        request = urllib.request.Request(endpoint, b"".join(chunks), headers=headers, method="POST")
                        with urllib.request.urlopen(request, timeout=30) as response:
                            if 200 <= response.status < 300:
                                job.unlink(missing_ok=True)
                    except Exception as exc:
                        print(f"Upload retry pending ({job.name}): {exc}")
                        self.stop_event.wait(2)
            self.stop_event.wait(10)

    def close(self):
        self.stop_event.set()
        if self.flash:
            self.flash.off()
            self.flash.close()
        if self.camera_lock.acquire(timeout=20):
            self.camera_lock.release()


def create_app(service, admin_port=ADMIN_PORT):
    web = Flask(__name__, static_folder="static", static_url_path="/static")
    web.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    web.secret_key = os.urandom(32)

    @web.before_request
    def admin_routes():
        regular_admin = {"admin", "save_config", "admin_event", "admin_session_lock", "admin_session_stop", "admin_session_hidden", "admin_session_delete", "admin_session_download", "admin_session_overlay", "admin_session_overlay_pause", "admin_capture", "restart_app", "get_admin_state"}
        local_admin = {"local_admin_page", "local_admin_photos", "local_admin_photo", "local_admin_delete_photos", "local_admin_shutdown", "local_admin_reboot", "local_admin_change_pin", "local_admin_exit_kiosk"}
        regular_admin.update({"admin_selfie_button", "admin_footer_logos", "admin_activate_footer_logo", "admin_remove_footer_logo", "admin_photos_page", "admin_photos", "admin_photo", "admin_delete_photos", "admin_shutdown"})
        regular_admin.update({"admin_wifi_scan", "admin_wifi_connect"})
        if request.endpoint in regular_admin and int(request.environ.get("SERVER_PORT", 0)) != admin_port:
            return jsonify({"error": f"Open the admin interface on port {admin_port}"}), 404
        if request.endpoint in local_admin and not session.get("admin_unlocked"):
            if request.endpoint == "local_admin_page":
                kiosk_url = request.url_root.replace(f":{admin_port}/", ":8080/")
                return redirect(kiosk_url)
            return jsonify({"error": "Admin PIN required"}), 401

    def valid_admin_pin(pin):
        expected = str(service.config.get("admin_pin", "1234"))
        return isinstance(pin, str) and hmac.compare_digest(pin.encode("utf-8", "surrogatepass"), expected.encode())

    @web.post("/api/admin/unlock")
    def admin_unlock():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not valid_admin_pin(str(payload.get("pin", ""))):
            return jsonify({"error": "Invalid PIN"}), 401
        session["admin_unlocked"] = True
        return jsonify({"unlocked": True})

    @web.get("/")
    def index():
        if int(request.environ.get("SERVER_PORT", 0)) == admin_port:
            return send_from_directory(BASE / "static", "admin.html")
        return send_from_directory(BASE / "static", "index.html")

    @web.get("/admin")
    def admin():
        return send_from_directory(BASE / "static", "admin.html")

    @web.get("/local-admin")
    def local_admin_page():
        return render_template("admin-photos.html", local=True)

    @web.get("/admin/captures")
    def admin_photos_page():
        return render_template("admin-photos.html", local=False)

    @web.get("/api/appearance")
    def get_appearance():
        accent = service.config.get("accent_color")
        if not isinstance(accent, str) or accent not in ACCENT_COLORS:
            accent = DEFAULT_ACCENT
        response = jsonify({"accent_color": accent, "colors": ACCENT_COLORS})
        response.headers["Cache-Control"] = "no-store"
        return response

    @web.get("/api/admin/state")
    def get_admin_state():
        result = service.state()
        boot_clock = getattr(time, "CLOCK_BOOTTIME", None)
        result["host_info"]["uptime_seconds"] = time.clock_gettime(boot_clock) if boot_clock is not None else None
        result["sessions"] = service.list_sessions(include_hidden=True)
        result["footer_logos"] = service.list_footer_logos()
        result["wifi"] = service.wifi.details()
        result["config"] = {key: service.config.get(key, "") for key in ("countdown_seconds", "sequence_countdown_seconds", "capture_lead_seconds", "sequence_interval_seconds", "idle_photo_wall_columns", "result_timeout_seconds", "camera_command", "upload_url", "gpio_flash_pin", "flash_seconds", "key_single", "key_sequence")}
        return jsonify(result)

    @web.post("/api/admin/wifi/scan")
    def admin_wifi_scan():
        try:
            return jsonify(service.wifi.scan())
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
            return jsonify({"error": "Wi-Fi scan unavailable. Enter the network name manually or try again."}), 503

    @web.post("/api/admin/wifi/connect")
    def admin_wifi_connect():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not valid_admin_pin(payload.get("pin")):
            return jsonify({"error": "Invalid admin PIN"}), 401
        try:
            service.wifi.connect(
                payload.get("ssid"), payload.get("security"), payload.get("password", ""), payload.get("hidden", False),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"connecting": True}), 202

    @web.get("/api/admin/photos", endpoint="admin_photos")
    @web.get("/api/local-admin/photos")
    def local_admin_photos():
        sessions, photos = service.local_admin_photos(request.args.get("session_id"))
        return jsonify({"sessions": sessions, "photos": photos})

    @web.get("/api/admin/photo/<session_id>/<path:relative_path>", endpoint="admin_photo")
    @web.get("/api/local-admin/photo/<session_id>/<path:relative_path>")
    def local_admin_photo(session_id, relative_path):
        try:
            _, photo, _ = service.local_admin_photo_path(session_id, relative_path)
            return send_file(service.photo_display_path(photo), mimetype="image/jpeg", max_age=0)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    @web.post("/api/admin/delete-photos", endpoint="admin_delete_photos")
    @web.post("/api/local-admin/delete-photos")
    def local_admin_delete_photos():
        payload = request.get_json(silent=True) or {}
        photos = payload.get("photos", [])
        if not isinstance(photos, list) or not all(isinstance(photo, dict) for photo in photos):
            return jsonify({"error": "Invalid photo selection"}), 400
        try:
            moved = service.move_local_admin_photos(photos)
            return jsonify({"moved": moved})
        except (ValueError, RuntimeError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/admin/shutdown")
    def admin_shutdown():
        if not request.is_json:
            return jsonify({"error": "Expected a JSON request"}), 415
        return local_admin_shutdown()

    @web.post("/api/local-admin/shutdown")
    def local_admin_shutdown():
        return request_pi_power_action("poweroff", "shutdown", "shutting_down")

    @web.post("/api/local-admin/reboot")
    def local_admin_reboot():
        if not request.is_json:
            return jsonify({"error": "Expected a JSON request"}), 415
        return request_pi_power_action("reboot", "restart", "restarting")

    def request_pi_power_action(command, action, response_key):
        try:
            result = subprocess.run(
                ["sudo", "-n", "/usr/bin/systemctl", command],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return jsonify({"error": f"Could not request {action}: {exc}"}), 500
        if result.returncode:
            message = (result.stderr or result.stdout or f"Could not request {action}").strip()
            return jsonify({"error": message}), 500
        return jsonify({response_key: True}), 202

    @web.post("/api/local-admin/pin")
    def local_admin_change_pin():
        payload = request.get_json(silent=True) or {}
        pin = payload.get("admin_pin", "")
        if pin != payload.get("confirm_pin"):
            return jsonify({"error": "The PINs did not match"}), 400
        try:
            service.update_config({"admin_pin": pin})
            return jsonify({"saved": True})
        except (ValueError, TypeError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/local-admin/exit-kiosk")
    def local_admin_exit_kiosk():
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            return jsonify({"error": "Exit to desktop is only available on the kiosk."}), 403
        if not request.is_json:
            return jsonify({"error": "Expected a JSON request"}), 415
        try:
            exit_kiosk_browser()
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"exiting": True})

    @web.post("/api/admin/event")
    def admin_event():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify({"session": service.create_session(str(payload.get("name", "")))})
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/admin/session-lock")
    def admin_session_lock():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify({"locked_session": service.lock_session(payload.get("session_id"))})
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/admin/session-stop")
    def admin_session_stop():
        try:
            return jsonify(service.stop_session())
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/admin/session-hidden")
    def admin_session_hidden():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify({"session": service.set_session_hidden(str(payload.get("session_id", "")), bool(payload.get("hidden")))})
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/admin/session-delete")
    def admin_session_delete():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(service.delete_session(str(payload.get("session_id", ""))))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/admin/footer-logos")
    def admin_footer_logos():
        if request.content_length and request.content_length > FOOTER_LOGO_UPLOAD_LIMIT + 16 * 1024:
            return jsonify({"error": "Choose a logo no larger than 2 MB"}), 413
        try:
            service.add_footer_logo(request.files.get("logo"))
            return jsonify({"saved": True}), 201
        except (ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/admin/footer-logos/active")
    def admin_activate_footer_logo():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or "id" not in payload:
            return jsonify({"error": "Choose a footer logo or deactivate it"}), 400
        try:
            service.set_active_footer_logo(payload["id"])
            return jsonify({"saved": True})
        except (ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/admin/footer-logos/remove")
    def admin_remove_footer_logo():
        payload = request.get_json(silent=True)
        try:
            service.remove_footer_logo(payload.get("id") if isinstance(payload, dict) else None)
            return jsonify({"removed": True})
        except (ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.get("/api/footer-logos/<filename>")
    def footer_logo_file(filename):
        on_admin_port = int(request.environ.get("SERVER_PORT", 0)) == admin_port
        if not on_admin_port and filename != service.active_footer_logo:
            return jsonify({"error": "Footer logo not found"}), 404
        try:
            path = service.footer_logo_path(filename)
            return send_file(path, mimetype="image/png", max_age=0)
        except (ValueError, FileNotFoundError):
            return jsonify({"error": "Footer logo not found"}), 404

    @web.post("/api/admin/session-overlay/<session_id>")
    def admin_session_overlay(session_id):
        try:
            remove = request.form.get("remove") == "1"
            overlay = service.set_session_overlay(session_id, request.files.get("overlay"), remove=remove)
            return jsonify({"session": overlay})
        except (ValueError, RuntimeError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/admin/session-overlay/<session_id>/pause")
    def admin_session_overlay_pause(session_id):
        payload = request.get_json(silent=True) or {}
        try:
            overlay = service.pause_session_overlay(session_id, payload.get("paused"))
            return jsonify({"session": overlay})
        except (ValueError, RuntimeError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.get("/api/admin/session-download/<session_id>")
    def admin_session_download(session_id):
        try:
            session, archive = service.session_archive(session_id)
            download_name = f"{service.safe_event_name(session['name'])}-{session_id}.zip"
            return send_file(archive, mimetype="application/zip", as_attachment=True, download_name=download_name, max_age=0)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    @web.route("/api/admin/selfie-button", methods=["GET", "POST"])
    def admin_selfie_button():
        try:
            if request.method == "GET":
                return jsonify({"devices": service.selfie_button.devices()})
            payload = request.get_json()
            if isinstance(payload, dict) and payload.get("forget") is True:
                service.selfie_button.forget()
                return jsonify({"forgotten": True})
            if isinstance(payload, dict) and payload.get("scan") is True:
                service.selfie_button.scan()
                return jsonify({"scanning": True}), 202
            service.selfie_button.pair(payload.get("address") if isinstance(payload, dict) else None)
            return jsonify({"paired": True})
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400
        except OSError:
            return jsonify({"error": "Could not save the selfie button selection."}), 500

    @web.post("/api/admin/capture")
    def admin_capture():
        payload = request.get_json(silent=True) or {}
        try:
            count = int(payload.get("count", 1))
            if count not in (1, 4):
                raise ValueError("Capture count must be one or four")
            delay = max(0, min(30, int(service.config.get("countdown_seconds", 3))))
            sequence_delay = max(0, min(30, int(service.config.get("sequence_countdown_seconds", 2))))
            interval = max(0, min(10, float(service.config.get("sequence_interval_seconds", 0.8))))
            service.start_capture(count, delay, interval, sequence_delay)
            return jsonify({"started": True}), 202
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.get("/api/photos/<event>/<path:filename>")
    def photo_file(event, filename):
        if event == service.footer_logo_dir.name:
            return jsonify({"error": "Photo not found"}), 404
        return send_from_directory(DATA / event, filename)

    @web.get("/api/photo-wall")
    def photo_wall():
        try:
            rows = max(1, min(12, int(request.args.get("rows", 3))))
        except ValueError:
            rows = 3
        return jsonify({
            "photos": service.photo_wall(rows),
            "columns": max(1, min(12, int(service.config.get("idle_photo_wall_columns", 3)))),
        })

    @web.post("/api/config")
    def save_config():
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict) and "admin_pin" in payload:
            if not valid_admin_pin(payload.pop("current_admin_pin", None)):
                return jsonify({"error": "Enter the current admin PIN to change it"}), 401
        try:
            service.update_config(payload)
            return jsonify({"saved": True})
        except (ValueError, TypeError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.get("/api/state")
    def get_state():
        state = service.state()
        public = {key: state[key] for key in ("session", "busy", "status", "countdown", "photo_number", "photo_total", "recent_photo", "recent_photo_version", "phase", "photo_wall_version", "photo_wall_columns", "active_footer_logo", "capture_count", "queued_uploads", "gallery_upload_configured", "sessions", "locked_session", "host_info", "camera_available", "camera_error", "selfie_button_status")}
        public["server_instance_id"] = SERVER_INSTANCE_ID
        public["admin_pin_length"] = len(str(service.config.get("admin_pin", "1234")))
        public["keys"] = {"single": service.config.get("key_single", "a"), "sequence": service.config.get("key_sequence", "b")}
        return jsonify(public)

    @web.get("/api/recent-photo")
    def recent_photo():
        state = service.state()
        path = service.recent_photo
        if not state["recent_photo"] or not path or not path.is_file():
            return "No captured photo", 404
        response = send_file(path, mimetype="image/jpeg", max_age=0, conditional=False)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

    @web.post("/api/session")
    def create_session():
        payload = request.get_json(silent=True) or {}
        try:
            session = service.create_session(str(payload.get("name", "")))
            return jsonify({"session": session}), 201
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/session/resume")
    def resume_session():
        try:
            return jsonify({"session": service.resume_session()})
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/session/select")
    def select_session():
        payload = request.get_json(silent=True) or {}
        try:
            allow_hidden = int(request.environ.get("SERVER_PORT", 0)) == admin_port
            return jsonify({"session": service.select_session(str(payload.get("id", "")), allow_hidden=allow_hidden)})
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/capture")
    def capture():
        payload = request.get_json(silent=True) or {}
        try:
            count = int(payload.get("count", 1))
            default_delay = service.config.get("sequence_countdown_seconds", 2) if count == 4 else service.config.get("countdown_seconds", 3)
            delay = max(0, min(30, int(payload.get("countdown", default_delay))))
            sequence_delay = max(0, min(30, int(service.config.get("sequence_countdown_seconds", 2))))
            interval = max(0, min(10, float(payload.get("interval", service.config.get("sequence_interval_seconds", 0.8)))))
            if count not in (1, 4):
                raise ValueError("Capture count must be one or four")
            service.start_capture(count, delay, interval, sequence_delay)
            return jsonify({"started": True}), 202
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/restart")
    def restart_app():
        service.stop_event.set()
        if service.flash:
            service.flash.off()
        shutdown = web.config.get("shutdown_server")
        if shutdown:
            threading.Timer(0.3, shutdown).start()
        return jsonify({"restarting": True})

    return web


def main():
    parser = argparse.ArgumentParser(description="Run the local photobooth web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--admin-port", type=int, default=8081)
    parser.add_argument("--demo", action="store_true", help="Use generated images instead of camera and GPIO")
    parser.add_argument("--manage-wifi", action="store_true", help="Manage Wi-Fi through NetworkManager")
    args = parser.parse_args()
    service = PhotoboothService(demo=args.demo, manage_wifi=args.manage_wifi)
    from werkzeug.serving import make_server
    web = create_app(service, args.admin_port)
    server = make_server(args.host, args.port, web, threaded=True)
    admin_server = make_server(args.host, args.admin_port, web, threaded=True)
    web.config["shutdown_server"] = server.shutdown
    try:
        threading.Thread(target=admin_server.serve_forever, daemon=True, name="admin-server").start()
        server.serve_forever()
    finally:
        service.close()


if __name__ == "__main__":
    main()
