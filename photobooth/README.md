# Raspberry Pi Photobooth

The photobooth is designed to run on Raspberry Pi with Raspberry Pi OS Desktop. It has been successfully tested on a Raspberry Pi 5. The app uses Flask, Chromium in kiosk mode, gPhoto2 for the camera, and GPIO for the flash. The web interface can also be tried in demo mode on a regular computer.

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

Run the installer as the desktop user, not as root. The script installs dependencies, creates the Python virtual environment, installs a `systemd --user` service, and adds Chromium to the desktop autostart. It uses `sudo` for system packages and restricted permission to run the shutdown command. The installation user is added to the `gpio` group, and GPIO devices are given read and write access for that group. If the user was recently added to the group, restart the Pi so the service receives the new group access. Also add any other accounts that need to use the flash to the `gpio` group.

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

- All exposures are stored locally in `~/Photobooth/` with a timestamp in the filename (`YYYYMMDD-HHMMSS-microseconds.jpg`). Each new session has its own photo folder; older sessions use the event name as the folder name. Single photos are stored directly in the session folder. Four-photo mode stores the original frames in `singles/` and the collage in the session folder, so only the collage is added to the gallery.
- While idle, the kiosk shows the latest photos from the active session in a configurable-column photo wall, newest at the top left. Tiles preserve the image aspect ratio, and the bottom row is cropped by the edge of the screen. During a photo session, the countdown and camera exposure are shown. When the countdown reaches zero, “SMILE” remains on screen with a message that the photo is being captured and downloaded from the camera. For a four-photo sequence, the current frame (1/4–4/4) is shown with a separately configurable countdown before each frame. The result appears as soon as camera capture and image processing are complete, without an extra simulated download screen. A countdown of 0 skips the countdown and the “SMILE” pause.
- A new photo session can be started directly from the result screen with `A` (one photo) or `B` (four photos). Otherwise, the kiosk returns to the gallery after the configured display time.
- On startup, the kiosk on port 8080 shows a list of saved, visible sessions, newest first, or lets you create a new session using the on-screen keyboard. The regular admin panel on port 8081 retains its existing session, capture, settings, and ZIP download features. A separate local admin page can be opened from the kiosk by holding the internet status in the footer and entering the PIN (default `1234`). From there, photos can be previewed and moved to a `deleted/` folder without being permanently removed, and the Raspberry Pi can be shut down. Moved photos are hidden from the gallery and counter but are included in the session ZIP. Change the PIN on the local admin page. A session can be pinned on the display so it is restored after reboot and the kiosk skips the selection dialog. Unpinning or stopping the session returns the kiosk directly to session selection. The kiosk photo wall shows internet status in the footer.
- The GPIO flash can be configured for the installed hardware. Do not drive LED strips directly from the Pi; use a suitable transistor/MOSFET or LED controller and a separate power supply.
- Persistent local upload queue. `upload_url` and `upload_token` in `config.json` control multipart uploads.

## Settings

Change the single-photo countdown, the separate countdown before each frame in a four-photo sequence, camera pre-trigger, interval, number of columns in the idle gallery, and display time in the admin panel. Camera pre-trigger starts the gPhoto2 command the selected number of seconds before the countdown reaches zero; it can be calibrated separately for the camera and environment. Changes are saved persistently to `config.json`. Other hardware and upload settings remain in the same file.

The installer must be run as the desktop user because it installs a user service and an autostart file in that user's home directory.
