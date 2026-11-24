# Raspberry Pi Photobooth

The photobooth is the camera-connected client in the Photobooth Gallery system. It is designed to run on Raspberry Pi with Raspberry Pi OS Desktop and has been successfully tested on a Raspberry Pi 5. The app uses Flask, Chromium in kiosk mode, gPhoto2 for the camera, and GPIO for the flash. The web interface can also be tried in demo mode on a regular computer.

## Try the interface locally

From the project directory:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py --demo
```

Open the kiosk at `localhost:8080` and the regular admin panel at `localhost:8081`. Demo mode creates sample photos without a camera or GPIO.

## Install on Raspberry Pi

Use Raspberry Pi OS Desktop. Enable automatic desktop login if the kiosk should start after reboot. Run these commands from the project directory:

```sh
cd photobooth
chmod +x install.sh launch-kiosk.sh
./install.sh
```

Run the installer as the desktop user, not as root. The script installs dependencies, creates the Python virtual environment, installs a `systemd --user` service, and adds Chromium to the desktop autostart. Chromium is launched with its basic password store so kiosk startup does not ask to create a desktop keyring. It uses `sudo` for system packages and restricted permission to run the shutdown command. The installation user is added to the `gpio` group, and GPIO devices are given read and write access for that group. If the user was recently added to the group, restart the Pi so the service receives the new group access. Also add any other accounts that need to use the flash to the `gpio` group.

The installer stops and masks the desktop user's `gvfs-gphoto2-volume-monitor.service` so automatic camera mounting does not compete with Photobooth for the USB camera.

The installer adds `unclutter` (from `unclutter-xfixes`). On X11, the kiosk launcher starts it with the pointer hidden and hides it again after one second of inactivity. On Wayland, the kiosk page hides the pointer within its own window.

The kiosk is available locally on port 8080. The regular admin panel uses port 8081.

Restart the service and view its status or logs with:

```sh
systemctl --user restart photobooth.service
systemctl --user status photobooth.service
journalctl --user -u photobooth.service -f
```

Chromium reconnects after the service restarts. Connect the camera via USB. Check the camera with:

```sh
gphoto2 --auto-detect
gphoto2 --capture-preview --filename /tmp/preview.jpg
```

## Features

- All captures are stored directly in the session photo folder with timestamped filenames (`YYYYMMDD-HHMMSS-microseconds.jpg`). Four-photo mode stores its original frames and collage there; each saved capture appears on the local Photo Wall, while only the collage is queued for upload to the hosted Gallery. When a session overlay is active, composited copies are stored in that session’s `overlay/` folder with `_overlay` added before the file extension. The overlay image and pause state are configured per session.
- While idle, the kiosk shows the latest photos from the active session on the local Photo Wall, with configurable columns and newest photos at the top left. Tiles preserve the image aspect ratio, and the bottom row is cropped by the edge of the screen. During a photo session, the countdown and camera exposure are shown. When the countdown reaches zero, “SMILE” remains on screen with a message that the photo is being captured and downloaded from the camera. For a four-photo sequence, the current frame (1/4–4/4) is shown with a separately configurable countdown before each frame. The result appears as soon as camera capture and image processing are complete, without an extra simulated download screen. A countdown of 0 skips the countdown and the “SMILE” pause.
- A new photo session can be started directly from the result screen with `A` (one photo) or `B` (four photos). Otherwise, the kiosk returns to the Photo Wall after the configured display time.
- On startup, the kiosk on port 8080 shows a list of saved, visible sessions, newest first, or lets you create a new session using the on-screen keyboard. The regular admin panel on port 8081 retains its existing session, capture, settings, and ZIP download features. A separate local admin page can be opened from the kiosk by holding the internet status in the footer and entering the PIN (default `1234`). From there, photos can be previewed and moved to a `deleted/` folder without being permanently removed, and the Raspberry Pi can be shut down. Moved photos are hidden from the Photo Wall and capture count but are included in the session ZIP. A session can be pinned on the display so it is restored after reboot and the kiosk skips the selection dialog. Unpinning or stopping the session returns the kiosk directly to session selection. The Photo Wall shows internet status in the footer.
- The admin page on port 8081 shows booth and host status above a menu that opens each group of controls. Select **Remove captures** in the menu to preview photos, filter by session, and move selected captures to the `deleted/` folder.
- Use **Footer logos** on port 8081 to upload a PNG, JPEG, or WebP up to 2 MB. Activate a saved logo to show it beside the session name on the Photo Wall. Deactivate it to keep it for reuse, or remove it from the library. The active logo applies across sessions and survives a restart.
- In **Persistent settings** on port 8081, choose an **Accent color** and select **Save accent color**. The kiosk and both admin pages update automatically, and the choice is saved across restarts.
- The kiosk checks the PIN as soon as the last digit is entered. Set a new four-digit PIN in **Persistent settings** on port 8081, or select **Change admin PIN** in local admin and enter it twice. Existing longer PINs can still be used until changed.
- Select **Exit to desktop** in local admin to close the Chromium window started by `launch-kiosk.sh` and return to the Raspberry Pi desktop. The photobooth service continues running. Run `launch-kiosk.sh` again to reopen the kiosk.
- The GPIO flash can be configured for the installed hardware. Do not drive LED strips directly from the Pi; use a suitable transistor/MOSFET or LED controller and a separate power supply.
- A persistent local upload queue holds photos for the hosted Gallery. Set `upload_url` to the Gallery's multipart upload endpoint and `upload_token` to its booth credential in `config.json` or the admin panel to enable delivery. Photos remain queued while uploads are unconfigured or the Gallery is unreachable; the Photo Wall and local photo storage work independently of the hosted service. The kiosk footer shows whether Gallery uploads are off, pending, or up to date.

## Settings

Change the single-photo countdown, the separate countdown before each frame in a four-photo sequence, camera pre-trigger, interval, number of columns in the idle Photo Wall, and display time in the admin panel. Camera pre-trigger starts the gPhoto2 command the selected number of seconds before the countdown reaches zero; it can be calibrated separately for the camera and environment. Changes are saved persistently to `config.json`. Other hardware and upload settings remain in the same file.

The installer must be run as the desktop user because it installs a user service and an autostart file in that user's home directory.

## Wi-Fi setup and fallback hotspot

The Pi needs a NetworkManager-managed Wi-Fi adapter with access-point support. If the adapter cannot join a saved Wi-Fi network, the Photobooth service starts a WPA2-protected hotspot after giving NetworkManager about 20 seconds to reconnect. The Photo Wall footer and session picker show when the hotspot is active. The hotspot stays up until you use Wi-Fi setup to join a network.

| Hotspot setting | Value |
| --- | --- |
| Network name (SSID) | `Photobooth Setup` |
| Password (PSK) | `photobooth-setup` |
| Raspberry Pi address | `10.42.0.1` |
| Admin page | [http://10.42.0.1:8081](http://10.42.0.1:8081) |

1. Connect your device to **Photobooth Setup**, or open port 8081 on the Pi's current address if it is already on Wi-Fi. Stay connected if your device reports that the hotspot has no internet access.
2. Under **Wi-Fi setup**, select **Scan for networks** and choose one. You can also enter the network name and security manually. Use **Hidden network** for a network that does not broadcast its name. The guide supports open, WPA/WPA2 Personal, and WPA3 Personal networks. Some adapters can only show recent scan results while hosting the hotspot.
3. Enter the Wi-Fi password if required and the booth's admin PIN, then select **Join network**. The Pi saves a successful connection for future boots. If it cannot join, it tries to restore the previous Wi-Fi connection or the setup hotspot.
4. Join the new network on your device and reopen the admin page using the Pi's new address or the `.local` hostname shown during the switch. If the switch failed, reconnect to the previous network and reopen the page to see the result.

The hotspot credentials are shared across installations. Use a distinct admin PIN for each booth. Changing the PIN from **Persistent settings** requires the current PIN.

## Bluetooth selfie button

1. Run `./install.sh` on the Pi to install BlueZ and Linux input support. Reboot after the installer adds the user to the Bluetooth input group.
2. On a phone or computer on the same network, open the Pi's admin page on port 8081. Put the selfie button in pairing mode, then use **Bluetooth selfie button → Scan for buttons**.
3. Choose the remote by name or Bluetooth address and select **Pair or reconnect**. Wait for **Selfie button connected**, then press the button with a photo session active.

On Raspberry Pi OS desktops using `wf-panel-pi`, the installer removes the Bluetooth widget from the kiosk user's panel so it cannot open a connection dialog over the kiosk. Pairing is available in Photobooth Admin. Restart the desktop session if it was already running during installation.

Either volume key starts one photo with the configured single-photo countdown. Holding the button and pressing it during a capture are ignored after the initial press. The button works while the kiosk browser is unfocused. The selected remote is saved across restarts. Wake the remote to reconnect or use **Pair or reconnect** from admin.

The Photo Wall footer shows **Connected** or **Disconnected** after the remote has connected during the active photo session. The indicator stays hidden until that first connection.

Select **Forget button** in the admin panel to remove the pairing from the Pi and clear Photobooth's saved selection. Scan and pair again to use the remote.
