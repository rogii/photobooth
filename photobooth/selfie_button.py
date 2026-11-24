"""Pair a Bluetooth shutter and listen for its Linux volume key events."""

import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

try:
    import evdev
except ImportError:
    evdev = None


ADDRESS = r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}"
BLUETOOTH_BUS = 0x05


class SelfieButton:
    def __init__(self, marker, stop_event, on_connection, on_press, enabled):
        self.marker = marker
        self.stop_event = stop_event
        self.on_connection = on_connection
        self.on_press = on_press
        self.bluetoothctl = shutil.which("bluetoothctl") if enabled and evdev else None
        self.setup_lock = threading.Lock()
        self.scan_process = None
        try:
            self.address = marker.read_text().strip().upper()
        except OSError:
            self.address = ""
        if not re.fullmatch(ADDRESS, self.address):
            self.address = ""
        if self.bluetoothctl:
            threading.Thread(target=self.monitor, daemon=True, name="selfie-button").start()

    def command(self, *args, timeout=5):
        if not self.bluetoothctl:
            raise RuntimeError("Bluetooth selfie buttons require BlueZ and python3-evdev on the Pi.")
        try:
            result = subprocess.run(
                [self.bluetoothctl, "--timeout", str(timeout), *args],
                capture_output=True, text=True, timeout=timeout + 2,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Bluetooth did not respond.") from exc
        details = (result.stdout + result.stderr).strip().splitlines()
        # Some bluetoothctl commands print failures while returning status zero.
        failure = next((line for line in details if line.startswith("Failed ")), None)
        if failure or result.returncode:
            raise RuntimeError(failure or (details[-1] if details else "Bluetooth command failed."))
        return result.stdout

    def scan(self):
        with self.setup_lock:
            self.command("power", "on")
            try:
                if self.scan_process and self.scan_process.poll() is None:
                    self.scan_process.terminate()
                    try:
                        self.scan_process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.scan_process.kill()
                # BlueZ keeps discovery active while this client is connected.
                process = subprocess.Popen(
                    [self.bluetoothctl, "--timeout", "45", "scan", "on"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                raise RuntimeError("Could not start Bluetooth discovery.") from exc
            self.scan_process = process
            threading.Thread(target=self.finish_scan, args=(process,), daemon=True).start()

    def finish_scan(self, process):
        self.stop_event.wait(45)
        if process.poll() is None:
            process.terminate()
        process.wait()

    def devices(self):
        return [
            {"address": address, "name": name or address}
            for address, name in re.findall(
                rf"^Device ({ADDRESS})(?: ([^\r\n]*))?$", self.command("devices"), re.MULTILINE
            )
        ]

    def pair(self, address):
        if not isinstance(address, str) or not re.fullmatch(ADDRESS, address):
            raise ValueError("Choose a Bluetooth device from the list.")
        with self.setup_lock:
            info = self.command("info", address)
            if not re.search(r"^\s*Paired: yes\s*$", info, re.MULTILINE):
                self.command("--agent", "NoInputNoOutput", "pair", address, timeout=20)
                info = self.command("info", address)
                if not re.search(r"^\s*Paired: yes\s*$", info, re.MULTILINE):
                    raise RuntimeError("Pairing failed. Put the button in pairing mode and try again.")
            self.command("trust", address)
            if not re.search(r"^\s*Connected: yes\s*$", info, re.MULTILINE):
                self.command("connect", address, timeout=15)

            with tempfile.TemporaryDirectory(dir=self.marker.parent) as temp_dir:
                pending = Path(temp_dir) / self.marker.name
                pending.write_text(address + "\n")
                pending.replace(self.marker)
            self.address = address

    def forget(self):
        with self.setup_lock:
            address = self.address
            if not address:
                return
            try:
                self.command("remove", address)
            except RuntimeError as exc:
                if str(exc) != f"Device {address} not available":
                    raise
            self.marker.unlink(missing_ok=True)
            self.address = ""

    def monitor(self):
        keys = {evdev.ecodes.KEY_VOLUMEUP, evdev.ecodes.KEY_VOLUMEDOWN}
        devices = {}
        address = ""
        connected = False
        next_search = 0.0
        last_press = float("-inf")
        try:
            while not self.stop_event.is_set():
                now = time.monotonic()
                if address != self.address:
                    for device in devices.values():
                        device.close()
                    devices.clear()
                    address = self.address
                    next_search = 0.0

                if address and now >= next_search:
                    next_search = now + 1
                    for path in evdev.list_devices():
                        if path in devices:
                            continue
                        try:
                            device = evdev.InputDevice(path)
                        except OSError:
                            continue
                        try:
                            if (device.info.bustype == BLUETOOTH_BUS
                                    and (device.uniq or "").upper() == address
                                    and keys.intersection(device.capabilities().get(evdev.ecodes.EV_KEY, []))):
                                devices[path] = device
                        except OSError:
                            pass
                        finally:
                            if path not in devices:
                                device.close()

                for path, device in list(devices.items()):
                    try:
                        for event in device.read():
                            # Linux reports releases as 0 and auto-repeat as 2.
                            if (event.type == evdev.ecodes.EV_KEY and event.code in keys
                                    and event.value == 1 and now - last_press >= 0.3
                                    and address == self.address):
                                last_press = now
                                self.on_press()
                    except BlockingIOError:
                        pass
                    except OSError:
                        device.close()
                        del devices[path]
                if bool(devices) != connected:
                    connected = bool(devices)
                    self.on_connection(connected)
                self.stop_event.wait(0.1)
        finally:
            for device in devices.values():
                device.close()
            if connected:
                self.on_connection(False)
