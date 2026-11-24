"""NetworkManager-backed Wi-Fi setup for the Raspberry Pi."""

import logging
import os
import re
import socket
import subprocess
import threading
import time
import uuid

HOTSPOT_SSID = "Photobooth Setup"
HOTSPOT_PSK = "photobooth-setup"
HOTSPOT_IP = "10.42.0.1"
HOTSPOT_UUID = "4a8d52c3-a1f9-4714-a8dd-2d335e5e0cb0"
SETTINGS = "org.freedesktop.NetworkManager.Settings"
LOG = logging.getLogger(__name__)
COMMAND_ERRORS = (RuntimeError, OSError, subprocess.SubprocessError)
STATUS_ERRORS = (*COMMAND_ERRORS, ValueError)


def nmcli(*args, wait=8):
    result = subprocess.run(
        ["nmcli", "--terse", "--wait", str(wait), *args],
        capture_output=True, text=True, errors="replace", timeout=wait + 3,
        env={**os.environ, "LC_ALL": "C.UTF-8"},
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "NetworkManager command failed")
    return result.stdout.removesuffix("\n")


def fields(line):
    return [re.sub(r"\\(.)", r"\1", item) for item in re.findall(r"(?:^|:)((?:\\.|[^:\\])*)", line)]


def add_profile(profile):
    # Pass the PSK over the system bus so it never appears in a process argument.
    import dbus

    bus = dbus.SystemBus()
    settings = bus.get_object("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager/Settings")
    settings.AddConnection(profile, dbus_interface=SETTINGS, timeout=10)


class Wifi:
    def __init__(self, stop_event, enabled=False):
        self.enabled = enabled
        self.lock = threading.Lock()
        self.status = {"available": False, "hotspot": None}
        self.message = ""
        self.connecting = False
        self.last_scan = []
        if enabled:
            threading.Thread(target=self.monitor, args=(stop_event,), name="wifi", daemon=True).start()

    def details(self):
        return {
            **self.status,
            "connecting": self.connecting,
            "message": self.message,
            "hostname": f"{socket.gethostname().split('.')[0]}.local",
        }

    def read_device(self):
        devices = [
            fields(line) for line in nmcli("-f", "DEVICE,TYPE", "device", "status").splitlines()
        ]
        interface = min((name for name, kind in devices if kind == "wifi"), default=None)
        if not interface:
            self.status = {"available": False, "hotspot": None}
            return None, "", 0

        device = nmcli(
            "--escape", "no", "-g", "GENERAL.STATE,GENERAL.CON-UUID,IP4.ADDRESS", "device", "show", interface,
        ).split("\n")
        state = int(device[0].split()[0])
        connection = device[1]
        address = device[2] if len(device) > 2 else ""
        hotspot = None
        ssid = None
        if state == 100:
            if connection == HOTSPOT_UUID:
                hotspot = {"ssid": HOTSPOT_SSID, "ip": HOTSPOT_IP}
            else:
                ssid = nmcli("--escape", "no", "-g", "802-11-wireless.ssid", "connection", "show", "uuid", connection)
        self.status = {
            "available": True, "hotspot": hotspot, "ssid": ssid,
            "ip": address.split("/")[0] if address else None,
        }
        return interface, connection if state == 100 else "", state

    def monitor(self, stop_event):
        disconnected_since = None
        while not stop_event.is_set():
            if self.lock.acquire(blocking=False):
                try:
                    interface, active, state = self.read_device()
                    # Give NetworkManager time to reconnect to a saved network.
                    if interface and not active and state >= 30:
                        now = time.monotonic()
                        if disconnected_since is None:
                            disconnected_since = now
                        elif state in (30, 120) and now - disconnected_since >= 20:
                            disconnected_since = now
                            try:
                                self.last_scan = self.scan_networks(interface, "no") or self.last_scan
                            except STATUS_ERRORS:
                                LOG.info("No Wi-Fi scan results available before starting the hotspot")
                            self.start_hotspot(interface)
                            self.read_device()
                    else:
                        disconnected_since = None
                except STATUS_ERRORS as error:
                    self.status = {"available": False, "hotspot": None}
                    LOG.warning("Wi-Fi status or fallback failed: %s", error)
                finally:
                    self.lock.release()
            stop_event.wait(4)

    def start_hotspot(self, interface):
        profiles = nmcli("-g", "UUID", "connection", "show").splitlines()
        if HOTSPOT_UUID not in profiles:
            nmcli(
                "connection", "add", "type", "wifi", "ifname", interface,
                "con-name", HOTSPOT_SSID, "connection.uuid", HOTSPOT_UUID,
                "autoconnect", "no", "ssid", HOTSPOT_SSID, "wifi.mode", "ap",
                "wifi.band", "bg", "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.proto", "rsn",
                "wifi-sec.psk", HOTSPOT_PSK, "ipv4.method", "shared",
                "ipv4.addresses", f"{HOTSPOT_IP}/24", "ipv6.method", "disabled",
            )
        nmcli("connection", "up", "uuid", HOTSPOT_UUID, "ifname", interface, wait=20)

    def scan(self):
        if not self.enabled:
            raise RuntimeError("Wi-Fi management is disabled.")
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("Wi-Fi is busy. Try scanning again shortly.")
        try:
            interface, _, _ = self.read_device()
            if not interface:
                raise RuntimeError("Wi-Fi is unavailable.")
            cache_only = False
            try:
                results = self.scan_networks(interface, "yes")
            except COMMAND_ERRORS:
                cache_only = True
                results = self.scan_networks(interface, "no")
            if not results and (cache_only or self.status["hotspot"]) and self.last_scan:
                results = self.last_scan
                cache_only = True
            else:
                self.last_scan = results
            return {"networks": results, "cached": cache_only}
        finally:
            self.lock.release()

    def scan_networks(self, interface, rescan):
        output = nmcli(
            "-f", "SSID,SECURITY,SIGNAL", "device", "wifi", "list",
            "ifname", interface, "--rescan", rescan, wait=12,
        )
        networks = {}
        for line in output.splitlines():
            ssid, security, signal = fields(line)
            if ssid and ssid != HOTSPOT_SSID:
                key = (ssid, "" if security == "--" else security)
                networks[key] = max(int(signal), networks.get(key, 0))
        return [
            {"ssid": ssid, "security": security, "signal": strength}
            for (ssid, security), strength in sorted(networks.items(), key=lambda item: -item[1])
        ]

    def connect(self, ssid, security, password, hidden):
        if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or "\x00" in ssid:
            raise ValueError("Enter a Wi-Fi network name of 1–32 bytes.")
        if ssid == HOTSPOT_SSID:
            raise ValueError("Choose the Wi-Fi network you want the Pi to join.")
        if security not in ("open", "wpa-psk", "sae") or not isinstance(hidden, bool):
            raise ValueError("Choose open, WPA/WPA2 Personal, or WPA3 Personal.")
        if not isinstance(password, str) or "\x00" in password:
            raise ValueError("Enter a valid Wi-Fi password.")
        if security == "wpa-psk" and not (
            8 <= len(password.encode()) <= 63 or re.fullmatch(r"[a-fA-F0-9]{64}", password)
        ):
            raise ValueError("Enter a WPA/WPA2 password of 8–63 bytes, or a 64-digit hex key.")
        if security == "sae" and not 1 <= len(password.encode()) <= 1024:
            raise ValueError("Enter a WPA3 password of 1–1024 bytes.")

        if not self.lock.acquire(blocking=False):
            raise RuntimeError("Wi-Fi is busy. Try again shortly.")
        if not self.status["available"]:
            self.lock.release()
            raise RuntimeError("Wi-Fi is unavailable.")
        self.message = ""
        self.connecting = True
        threading.Thread(
            target=self.switch, args=(ssid, security, password, hidden), name="wifi-switch", daemon=True,
        ).start()

    def switch(self, ssid, security, password, hidden):
        interface = None
        previous = ""
        added = False
        profile_id = str(uuid.uuid4())
        name = f"Photobooth Wi-Fi: {ssid}"
        try:
            import dbus

            interface, previous, _ = self.read_device()
            if not interface:
                raise RuntimeError("Wi-Fi is unavailable")
            profile = {
                "connection": {
                    "id": name, "uuid": profile_id, "type": "802-11-wireless",
                    "interface-name": interface, "autoconnect": False, "autoconnect-priority": dbus.Int32(20),
                },
                "802-11-wireless": {
                    "ssid": dbus.ByteArray(ssid.encode()), "mode": "infrastructure", "hidden": hidden,
                },
                "ipv4": {"method": "auto"},
                "ipv6": {"method": "auto"},
            }
            if security != "open":
                profile["802-11-wireless-security"] = {"key-mgmt": security, "psk": password}
            old_profiles = [
                profile_uuid for profile_uuid, profile_name in (
                    fields(line) for line in nmcli("-f", "UUID,NAME", "connection", "show").splitlines()
                ) if profile_name == name
            ]
            add_profile(profile)
            added = True
            nmcli("connection", "up", "uuid", profile_id, "ifname", interface, wait=35)
            nmcli("connection", "modify", "uuid", profile_id, "connection.autoconnect", "yes")
        except Exception as error:
            LOG.warning("Wi-Fi switch failed (%s)", type(error).__name__)
            self.message = "Could not join the selected network. Check its name, security and password."
            if added:
                try:
                    nmcli("connection", "delete", "uuid", profile_id)
                except COMMAND_ERRORS:
                    LOG.warning("Could not remove the failed Wi-Fi profile")
                try:
                    if previous:
                        nmcli("connection", "up", "uuid", previous, "ifname", interface, wait=20)
                    else:
                        self.start_hotspot(interface)
                except COMMAND_ERRORS:
                    LOG.warning("Could not immediately restore the previous Wi-Fi connection")
        else:
            self.message = f"Connected to {ssid}."
            for old_profile in old_profiles:
                try:
                    nmcli("connection", "delete", "uuid", old_profile)
                except COMMAND_ERRORS:
                    LOG.warning("Could not remove the previous Photobooth Wi-Fi profile")
        finally:
            try:
                self.read_device()
            except STATUS_ERRORS:
                self.status = {"available": False, "hotspot": None}
            self.last_scan = []
            self.connecting = False
            self.lock.release()
