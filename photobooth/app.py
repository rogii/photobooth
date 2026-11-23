#!/usr/bin/env python3
"""Local photobooth web server for Raspberry Pi and browser based UI testing."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import shutil
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

from flask import Flask, jsonify, redirect, request, send_file, send_from_directory, session
from PIL import Image, ImageDraw, ImageOps

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


def read_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


class PhotoboothService:
    def __init__(self, demo=False):
        self.config = read_config()
        self.config.setdefault("capture_lead_seconds", 1.2)
        self.config.setdefault("admin_pin", "1234")
        self.demo = demo
        self.camera_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.busy = False
        self.status = "Choose or create a session"
        self.countdown = ""
        self.session = None
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
        self.gallery_revision = 0
        self.capture_generation = 0
        self.host_info_lock = threading.Lock()
        self.internet_checked_at = 0.0
        self.internet_connected = False

        DATA.mkdir(parents=True, exist_ok=True)
        SESSIONS.mkdir(parents=True, exist_ok=True)
        UPLOAD_QUEUE.mkdir(parents=True, exist_ok=True)
        self._init_gpio()
        threading.Thread(target=self.upload_worker, daemon=True, name="upload-queue").start()

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
            }

    @staticmethod
    def session_from_item(item):
        return {key: item[key] for key in ("id", "name", "created_at", "hidden", "photo_dir") if key in item}

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
                "capture_count": capture_count,
                "flash_available": self.flash_available,
                "demo": self.demo,
                "phase": self.phase,
                "photo_number": self.photo_number,
                "photo_total": self.photo_total,
                "gallery_version": f"{session['id'] if session else 'none'}:{self.gallery_revision}",
                "gallery_columns": max(1, min(12, int(self.config.get("idle_gallery_columns", 3)))),
                "host_info": self.host_info(),
            }

    def gallery(self, rows=3):
        event = self.session
        if not event:
            return []
        folder = self.session_photo_dir(event)
        if not folder.is_dir():
            return []
        files = sorted(folder.glob("*.jpg"), key=lambda path: path.name, reverse=True)
        columns = max(1, min(12, int(self.config.get("idle_gallery_columns", 3))))
        files = files[:columns * max(1, min(12, int(rows)))]
        return [{"name": path.name, "url": f"/api/photos/{folder.name}/{path.name}"} for path in files]

    @staticmethod
    def safe_event_name(name):
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip(" .")
        return safe[:80] or "Event"

    def update_config(self, values):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish before changing settings")
        admin_pin = None
        if "admin_pin" in values:
            admin_pin = str(values["admin_pin"]).strip()
            if not admin_pin.isdigit() or not 4 <= len(admin_pin) <= 12:
                raise ValueError("Admin PIN must contain 4 to 12 digits")
        previous_gpio_pin = self.config.get("gpio_flash_pin", 17)
        allowed = {"countdown_seconds": (0, 30, int), "sequence_countdown_seconds": (0, 30, int), "capture_lead_seconds": (0, 5, float), "sequence_interval_seconds": (0, 10, float), "idle_gallery_columns": (1, 12, int), "result_timeout_seconds": (1, 300, int), "gpio_flash_pin": (0, 27, int), "flash_seconds": (0, 5, float)}
        for key, (low, high, cast) in allowed.items():
            if key in values:
                self.config[key] = max(low, min(high, cast(values[key])))
        for key in ("camera_command", "upload_url", "upload_token", "key_single", "key_sequence"):
            if key in values:
                self.config[key] = str(values[key]).strip()
        if admin_pin is not None:
            self.config["admin_pin"] = admin_pin
        if self.config.get("gpio_flash_pin", 17) != previous_gpio_pin:
            if self.flash:
                self.flash.close()
            self.flash = None
            self.flash_available = False
            self._init_gpio()
        CONFIG_PATH.write_text(json.dumps(self.config, ensure_ascii=False, indent=2) + "\n")
        return {key: self.config.get(key) for key in values if key != "upload_token"}

    def set_status(self, value):
        with self.state_lock:
            self.status = value

    def set_countdown(self, value):
        with self.state_lock:
            self.countdown = value

    def create_session(self, name):
        if not name or not name.strip():
            raise ValueError("Enter a session name")
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            now = datetime.now()
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
            self.session = self.session_from_item(item)
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
                self.session = dict(self.locked_session)
                self.last_session = dict(self.session)
                LAST_SESSION.write_text(json.dumps(self.session, ensure_ascii=False, indent=2))
                LOCKED_SESSION.write_text(json.dumps(self.locked_session, ensure_ascii=False, indent=2))
                (folder / "session.json").write_text(json.dumps(self.locked_session, ensure_ascii=False, indent=2))
            else:
                self.locked_session = None
                self.session = None
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
            self.session = dict(self.last_session)
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
                            capture_result["photo"] = self.capture_one(gallery_visible=(count == 1))
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
            with self.state_lock:
                self.gallery_revision += 1
            self.make_display_image(result)
            session = self.session
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

    def capture_one(self, gallery_visible=True):
        session = self.session
        folder = self.session_photo_dir(session)
        if not gallery_visible:
            folder = folder / "singles"
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
        tile_w, tile_h = 1200, 675
        canvas = Image.new("RGB", (tile_w * 2, tile_h * 2), "white")
        for index, image in enumerate(images):
            image = ImageOps.fit(image, (tile_w, tile_h), method=Image.Resampling.LANCZOS)
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
    def admin_port_only():
        protected = {"admin", "save_config", "admin_event", "admin_session_lock", "admin_session_stop", "admin_session_hidden", "admin_session_delete", "admin_session_download", "admin_capture", "restart_app", "get_admin_state"}
        port = int(request.environ.get("SERVER_PORT", 0))
        if request.endpoint in protected and int(request.environ.get("SERVER_PORT", 0)) != admin_port:
            return jsonify({"error": f"Open the admin interface on port {admin_port}"}), 404
        admin_page = request.endpoint == "admin" or (request.endpoint == "index" and port == admin_port)
        admin_request = request.endpoint in protected or admin_page
        if admin_request and request.endpoint != "admin_unlock" and not session.get("admin_unlocked"):
            if admin_page:
                kiosk_url = request.url_root.replace(f":{admin_port}/", ":8080/")
                return redirect(kiosk_url)
            return jsonify({"error": "Admin PIN required"}), 401

    @web.post("/api/admin/unlock")
    def admin_unlock():
        payload = request.get_json(silent=True) or {}
        expected = str(service.config.get("admin_pin", "1234"))
        provided = str(payload.get("pin", ""))
        if not hmac.compare_digest(provided, expected):
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

    @web.get("/api/admin/state")
    def get_admin_state():
        result = service.state()
        result["sessions"] = service.list_sessions(include_hidden=True)
        result["config"] = {key: service.config.get(key, "") for key in ("countdown_seconds", "sequence_countdown_seconds", "capture_lead_seconds", "sequence_interval_seconds", "idle_gallery_columns", "result_timeout_seconds", "camera_command", "upload_url", "gpio_flash_pin", "flash_seconds", "key_single", "key_sequence", "admin_pin")}
        return jsonify(result)

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

    @web.get("/api/admin/session-download/<session_id>")
    def admin_session_download(session_id):
        try:
            session, archive = service.session_archive(session_id)
            download_name = f"{service.safe_event_name(session['name'])}-{session_id}.zip"
            return send_file(archive, mimetype="application/zip", as_attachment=True, download_name=download_name, max_age=0)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

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

    @web.get("/api/photos/<event>/<filename>")
    def photo_file(event, filename):
        return send_from_directory(DATA / event, filename)

    @web.get("/api/gallery")
    def gallery():
        try:
            rows = max(1, min(12, int(request.args.get("rows", 3))))
        except ValueError:
            rows = 3
        return jsonify({
            "photos": service.gallery(rows),
            "columns": max(1, min(12, int(service.config.get("idle_gallery_columns", 3)))),
        })

    @web.post("/api/config")
    def save_config():
        try:
            service.update_config(request.get_json(silent=True) or {})
            return jsonify({"saved": True})
        except (ValueError, TypeError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.get("/api/state")
    def get_state():
        state = service.state()
        public = {key: state[key] for key in ("session", "busy", "status", "countdown", "photo_number", "photo_total", "recent_photo", "recent_photo_version", "phase", "gallery_version", "gallery_columns", "capture_count", "queued_uploads", "sessions", "locked_session", "host_info")}
        public["server_instance_id"] = SERVER_INSTANCE_ID
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
    args = parser.parse_args()
    service = PhotoboothService(demo=args.demo)
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
