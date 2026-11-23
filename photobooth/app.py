#!/usr/bin/env python3
"""Local photobooth web server for Raspberry Pi and browser based UI testing."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from PIL import Image, ImageDraw, ImageOps

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
DATA = Path(os.environ.get("PHOTOBOOTH_DATA", Path.home() / "Photobooth"))
SESSIONS = DATA / "sessions"
UPLOAD_QUEUE = DATA / "upload-queue"
LAST_SESSION = DATA / "last-session.json"
DISPLAY_FILE = DATA / "latest-display.jpg"
NEXT_DISPLAY_FILE = DATA / "latest-display-next.jpg"


def read_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


class PhotoboothService:
    def __init__(self, demo=False):
        self.config = read_config()
        self.demo = demo
        self.camera_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.busy = False
        self.status = "Choose or create a session"
        self.countdown = ""
        self.session = None
        self.last_session = self._read_last_session()
        self.flash = None
        self.flash_available = False
        self.recent_photo = None
        self.recent_photo_version = ""
        self.recent_photo_time = None

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
            photo_visible = bool(
                self.recent_photo
                and self.recent_photo_time
                and time.monotonic() - self.recent_photo_time < 10
            )
            return {
                "session": session,
                "last_session": dict(self.last_session) if self.last_session else None,
                "busy": self.busy,
                "status": self.status,
                "countdown": self.countdown,
                "recent_photo": photo_visible,
                "recent_photo_version": self.recent_photo_version if photo_visible else "",
                "queued_uploads": len(list(UPLOAD_QUEUE.glob("*.json"))),
                "flash_available": self.flash_available,
                "demo": self.demo,
            }

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
            }
            self.last_session = dict(self.session)
            self.status = f"Session ready · {self.session['name']}"
            (SESSIONS / self.session["id"]).mkdir(parents=True, exist_ok=True)
            LAST_SESSION.write_text(json.dumps(self.session, ensure_ascii=False, indent=2))
            return dict(self.session)

    def resume_session(self):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("Wait for the current capture to finish")
            if not self.last_session:
                raise ValueError("There is no previous session to resume")
            self.session = dict(self.last_session)
            self.status = f"Session resumed · {self.session['name']}"
            return dict(self.session)

    def start_capture(self, count, delay, interval):
        with self.state_lock:
            if self.busy:
                raise RuntimeError("A capture is already running")
            if not self.session:
                raise RuntimeError("Choose or create a session first")
            self.busy = True
            self.recent_photo = None
            self.recent_photo_version = ""
            self.recent_photo_time = None
            self.status = "Preparing capture"
        threading.Thread(
            target=self.capture_flow,
            args=(count, delay, interval),
            daemon=True,
            name="photo-capture",
        ).start()

    def capture_flow(self, count, delay, interval):
        try:
            for remaining in range(delay, 0, -1):
                self.set_countdown(str(remaining))
                time.sleep(1)
            self.set_countdown("SMILE")
            files = []
            for index in range(count):
                if self.flash:
                    self.flash.on()
                    time.sleep(float(self.config.get("flash_seconds", 0.18)))
                photo = self.capture_one()
                if self.flash:
                    self.flash.off()
                files.append(photo)
                if index + 1 < count:
                    time.sleep(interval)
            result = self.make_result(files)
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
        except Exception as exc:
            self.set_status(f"Capture failed · {exc}")
        finally:
            if self.flash:
                self.flash.off()
            self.set_countdown("")
            with self.state_lock:
                self.busy = False

    def capture_one(self):
        session = self.session
        folder = SESSIONS / session["id"]
        path = folder / f"{datetime.now().strftime('%H%M%S-%f')}.jpg"
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


def create_app(service):
    web = Flask(__name__, static_folder="static", static_url_path="/static")

    @web.get("/")
    def index():
        return send_from_directory(BASE / "static", "index.html")

    @web.get("/api/state")
    def get_state():
        return jsonify(service.state())

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

    @web.post("/api/capture")
    def capture():
        payload = request.get_json(silent=True) or {}
        try:
            count = int(payload.get("count", 1))
            delay = max(0, min(30, int(payload.get("countdown", service.config.get("countdown_seconds", 3)))))
            interval = max(0, min(10, float(payload.get("interval", service.config.get("sequence_interval_seconds", 0.8)))))
            if count not in (1, 4):
                raise ValueError("Capture count must be one or four")
            service.start_capture(count, delay, interval)
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
    parser.add_argument("--demo", action="store_true", help="Use generated images instead of camera and GPIO")
    args = parser.parse_args()
    service = PhotoboothService(demo=args.demo)
    from werkzeug.serving import make_server
    web = create_app(service)
    server = make_server(args.host, args.port, web, threaded=True)
    web.config["shutdown_server"] = server.shutdown
    try:
        server.serve_forever()
    finally:
        service.close()


if __name__ == "__main__":
    main()
