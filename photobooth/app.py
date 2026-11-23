#!/usr/bin/env python3
"""Photobooth proof of concept for Raspberry Pi OS desktop."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from tkinter import END, Tk, StringVar, messagebox, ttk

from PIL import Image, ImageTk, ImageOps, ImageDraw

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
DATA = Path(os.environ.get("PHOTOBOOTH_DATA", Path.home() / "Photobooth"))
SESSIONS = DATA / "sessions"
UPLOAD_QUEUE = DATA / "upload-queue"
LAST_SESSION = DATA / "last-session.json"
PREVIEW_FILE = DATA / "preview.jpg"


def read_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


class Photobooth:
    def __init__(self, root):
        self.root = root
        self.config = read_config()
        self.root.title("Fotobås")
        self.root.attributes("-fullscreen", True)
        self.root.configure(background="#111827")
        self.root.bind("<Escape>", lambda _e: self.root.attributes("-fullscreen", False))
        self.root.bind("<KeyPress>", self.on_key)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.messages = queue.Queue()
        self.camera_lock = threading.Lock()
        self.busy = False
        self.session = None
        self.preview_photo = None
        self.flash = None
        self.flash_available = False
        self.status = StringVar(value="Välj en session för att börja")
        self.countdown = StringVar(value="")
        self.event_name = StringVar()
        self.countdown_seconds = StringVar(value=str(self.config.get("countdown_seconds", 3)))
        self.sequence_interval = StringVar(value=str(self.config.get("sequence_interval_seconds", 0.8)))
        self._init_gpio()
        self._build_ui()
        DATA.mkdir(parents=True, exist_ok=True)
        SESSIONS.mkdir(parents=True, exist_ok=True)
        UPLOAD_QUEUE.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self.upload_worker, daemon=True).start()
        self.root.after(100, self.poll_messages)
        self.root.after(500, self.offer_session)

    def _init_gpio(self):
        try:
            from gpiozero import DigitalOutputDevice
            pin = int(self.config.get("gpio_flash_pin", 17))
            self.flash = DigitalOutputDevice(pin, active_high=True, initial_value=False)
            self.flash_available = True
        except Exception as exc:
            print(f"GPIO-blixt avstängd: {exc}")

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Sans", 18), padding=12)
        style.configure("TLabel", font=("Sans", 15))
        top = ttk.Frame(self.root, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="FOTOBÅS", font=("Sans", 22, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.status).pack(side="right")
        body = ttk.Frame(self.root, padding=16)
        body.pack(fill="both", expand=True)
        self.preview = ttk.Label(body, text="Kamerans livevy visas här", anchor="center")
        self.preview.pack(side="left", fill="both", expand=True, padx=(0, 16))
        panel = ttk.Frame(body, padding=12)
        panel.pack(side="right", fill="y")
        ttk.Label(panel, text="Event").pack(anchor="w")
        ttk.Label(panel, textvariable=self.event_name, wraplength=280, font=("Sans", 20, "bold")).pack(anchor="w", pady=(0, 16))
        ttk.Label(panel, text="Nedräkning (sekunder)").pack(anchor="w")
        ttk.Entry(panel, textvariable=self.countdown_seconds, font=("Sans", 18), width=8).pack(anchor="w", pady=(0, 12))
        ttk.Label(panel, text="Intervall mellan bilder (sekunder)").pack(anchor="w")
        ttk.Entry(panel, textvariable=self.sequence_interval, font=("Sans", 18), width=8).pack(anchor="w", pady=(0, 18))
        ttk.Button(panel, text="Ta en bild  (A)", command=lambda: self.start_capture(1)).pack(fill="x", pady=5)
        ttk.Button(panel, text="Ta fyra bilder  (B)", command=lambda: self.start_capture(4)).pack(fill="x", pady=5)
        ttk.Button(panel, text="Byt / ny session", command=self.offer_session).pack(fill="x", pady=(20, 5))
        ttk.Label(panel, textvariable=self.countdown, font=("Sans", 48, "bold")).pack(pady=12)
        self.queue_label = ttk.Label(panel, text="")
        self.queue_label.pack(anchor="w", pady=10)
        self.root.after(2000, self.update_queue_label)

    def offer_session(self):
        previous = None
        try:
            previous = json.loads(LAST_SESSION.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        choices = []
        if previous and (SESSIONS / previous.get("id", "")).is_dir():
            choices.append("Återuppta senaste: " + previous.get("name", "Event"))
        choices.append("Starta ny session")
        choice = self.choose_dialog("Välkommen", choices)
        if choice is None:
            return
        if previous and choice == choices[0] and len(choices) == 2:
            self.session = previous
            self.event_name.set(self.session["name"])
            self.status.set("Session återupptagen · A = en bild · B = fyra bilder")
            self.update_queue_label()
            return
        name = self.text_dialog("Ny session", "Namn på eventet:")
        if not name:
            return
        now = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session = {"id": f"{now}-{uuid.uuid4().hex[:6]}", "name": name.strip(), "created_at": datetime.now().isoformat()}
        (SESSIONS / self.session["id"]).mkdir(parents=True, exist_ok=True)
        LAST_SESSION.write_text(json.dumps(self.session, ensure_ascii=False, indent=2))
        self.event_name.set(self.session["name"])
        self.status.set("Session klar · A = en bild · B = fyra bilder")

    def choose_dialog(self, title, choices):
        result = {"value": None}
        win = self.dialog_window(title)
        ttk.Label(win, text=title, font=("Sans", 20, "bold")).pack(padx=24, pady=16)
        for choice in choices:
            ttk.Button(win, text=choice, command=lambda c=choice: (result.update(value=c), win.destroy())).pack(fill="x", padx=24, pady=6)
        ttk.Button(win, text="Avbryt", command=win.destroy).pack(fill="x", padx=24, pady=(10, 18))
        self.root.wait_window(win)
        return result["value"]

    def text_dialog(self, title, prompt):
        result = {"value": None}
        win = self.dialog_window(title)
        ttk.Label(win, text=prompt, font=("Sans", 19)).pack(padx=24, pady=16)
        entry = ttk.Entry(win, font=("Sans", 20), width=28)
        entry.pack(padx=24, pady=8)
        entry.focus_set()
        def done():
            result["value"] = entry.get()
            win.destroy()
        ttk.Button(win, text="Starta session", command=done).pack(fill="x", padx=24, pady=16)
        entry.bind("<Return>", lambda _e: done())
        self.root.wait_window(win)
        return result["value"]

    def dialog_window(self, title):
        win = __import__("tkinter").Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.grab_set()
        win.geometry("600x400+120+80")
        return win

    def on_key(self, event):
        if isinstance(event.widget, ttk.Entry):
            return
        key = event.char.lower()
        if key == str(self.config.get("key_single", "a")).lower():
            self.start_capture(1)
        elif key == str(self.config.get("key_sequence", "b")).lower():
            self.start_capture(4)

    def start_capture(self, count):
        if self.busy:
            return
        if not self.session:
            self.status.set("Välj eller skapa en session först")
            return
        try:
            delay = max(0, min(30, int(self.countdown_seconds.get())))
            interval = max(0, min(10, float(self.sequence_interval.get())))
        except ValueError:
            self.status.set("Kontrollera nedräkning och intervall")
            return
        self.busy = True
        threading.Thread(target=self.capture_flow, args=(count, delay, interval), daemon=True).start()

    def capture_flow(self, count, delay, interval):
        try:
            for n in range(delay, 0, -1):
                self.messages.put(("countdown", str(n)))
                time.sleep(1)
            self.messages.put(("countdown", "LE") )
            frames = []
            for i in range(count):
                if self.flash:
                    self.flash.on()
                    time.sleep(float(self.config.get("flash_seconds", 0.18)))
                image_path = self.capture_one()
                if self.flash:
                    self.flash.off()
                frames.append(image_path)
                if i + 1 < count:
                    time.sleep(interval)
            final_path = self.make_result(frames)
            queued = UPLOAD_QUEUE / f"{self.session['id']}-{final_path.name}.json"
            queued.write_text(json.dumps({"file": str(final_path), "session_id": self.session["id"], "session_name": self.session["name"], "idempotency_key": uuid.uuid4().hex}))
            self.messages.put(("status", f"Sparad: {final_path.name}"))
        except Exception as exc:
            if self.flash:
                self.flash.off()
            self.messages.put(("status", f"Fotografering misslyckades: {exc}"))
        finally:
            self.messages.put(("countdown", ""))
            self.messages.put(("ready", ""))

    def capture_one(self):
        command = self.config.get("camera_command", "gphoto2")
        if not shutil.which(command):
            raise RuntimeError(f"Hittar inte {command}; installera gphoto2")
        folder = SESSIONS / self.session["id"]
        path = folder / f"{datetime.now().strftime('%H%M%S-%f')}.jpg"
        with self.camera_lock:
            result = subprocess.run([command, "--capture-image-and-download", "--filename", str(path)], capture_output=True, text=True, timeout=90)
        if result.returncode != 0 or not path.exists():
            raise RuntimeError((result.stderr or result.stdout or "Kameran returnerade inget foto").strip()[-400:])
        return path

    def make_result(self, frames):
        if len(frames) == 1:
            return frames[0]
        images = [ImageOps.exif_transpose(Image.open(p)).convert("RGB") for p in frames]
        tile_w, tile_h = 1200, 900
        canvas = Image.new("RGB", (tile_w * 2, tile_h * 2), "white")
        for i, image in enumerate(images):
            image.thumbnail((tile_w - 24, tile_h - 24))
            x = (i % 2) * tile_w + (tile_w - image.width) // 2
            y = (i // 2) * tile_h + (tile_h - image.height) // 2
            canvas.paste(image, (x, y))
        out = SESSIONS / self.session["id"] / f"{datetime.now().strftime('%H%M%S-%f')}-strip.jpg"
        canvas.save(out, quality=92)
        return out

    def preview_tick(self):
        # Preview is a still-frame poll; gPhoto2 camera support/latency varies by model.
        if self.session and not self.busy and self.camera_lock.acquire(blocking=False):
            def fetch():
                try:
                    result = subprocess.run([self.config.get("camera_command", "gphoto2"), "--capture-preview", "--filename", str(PREVIEW_FILE), "--force-overwrite"], capture_output=True, timeout=15)
                    if result.returncode == 0 and PREVIEW_FILE.exists():
                        self.messages.put(("preview", str(PREVIEW_FILE)))
                except Exception:
                    pass
                finally:
                    self.camera_lock.release()
            threading.Thread(target=fetch, daemon=True).start()
        self.root.after(int(self.config.get("preview_interval_ms", 1200)), self.preview_tick)

    def poll_messages(self):
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "countdown": self.countdown.set(value)
                elif kind == "status": self.status.set(value)
                elif kind == "ready": self.busy = False
                elif kind == "preview":
                    image = Image.open(value)
                    image.thumbnail((1000, 760))
                    self.preview_photo = ImageTk.PhotoImage(image)
                    self.preview.configure(image=self.preview_photo, text="")
        except queue.Empty:
            pass
        self.root.after(100, self.poll_messages)

    def upload_worker(self):
        while True:
            endpoint = self.config.get("upload_url", "").strip()
            if endpoint:
                for job in list(UPLOAD_QUEUE.glob("*.json")):
                    try:
                        import urllib.request
                        import urllib.error
                        meta = json.loads(job.read_text())
                        image_path = Path(meta["file"])
                        boundary = uuid.uuid4().hex
                        fields = {k: str(meta[k]) for k in ("session_id", "session_name", "idempotency_key")}
                        chunks = []
                        for key, val in fields.items():
                            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n".encode())
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
                        print(f"Uppladdning väntar på återförsök ({job.name}): {exc}")
                        time.sleep(2)
            time.sleep(10)

    def update_queue_label(self):
        UPLOAD_QUEUE.mkdir(parents=True, exist_ok=True)
        self.queue_label.configure(text=f"Väntande uppladdningar: {len(list(UPLOAD_QUEUE.glob('*.json')))}\nBlixt: {'redo' if self.flash_available else 'ej ansluten'}")
        self.root.after(5000, self.update_queue_label)

    def close(self):
        if self.flash:
            self.flash.off()
            self.flash.close()
        self.root.destroy()


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    root = Tk()
    app = Photobooth(root)
    root.after(1500, app.preview_tick)
    root.mainloop()


if __name__ == "__main__":
    main()
