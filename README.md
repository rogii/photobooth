# photobooth

The photobooth application is in [`photobooth/`](photobooth/). The project targets Raspberry Pi with Raspberry Pi OS Desktop and has been successfully tested on Raspberry Pi 5. It is a local Flask web app that runs as a systemd user service with a Chromium kiosk interface, gPhoto2 camera control, a Bluetooth button, a GPIO flash, four-photo collages, and a persistent upload queue.

Photos are stored locally for each event. The kiosk shows a sorted photo wall while idle, then switches to a countdown, save progress, and a full-screen result when taking a photo. The admin panel runs on a separate port for status, settings, and restarting the service. See [`photobooth/README.md`](photobooth/README.md) for running the local demo, installation, and kiosk autostart.
