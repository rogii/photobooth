# photobooth

The photobooth application is in [`photobooth/`](photobooth/). The project targets Raspberry Pi with Raspberry Pi OS Desktop and has been successfully tested on Raspberry Pi 5. It is a local Flask web app that runs as a systemd user service with a Chromium kiosk interface, gPhoto2 camera control, a Bluetooth button, a GPIO flash, four-photo collages, and a persistent upload queue.

Photos are stored locally for each event. The kiosk shows a sorted photo wall while idle, then switches to a countdown, save progress, and a full-screen result when taking a photo. The admin panel runs on a separate port for status, settings, and restarting the service. See [`photobooth/README.md`](photobooth/README.md) for running the local demo, installation, and kiosk autostart.

## Photobooth Gallery

The planned [`gallery/`](gallery/) service is a separate, always-available web app for browsing active photo sessions and displaying live slideshows on TVs. It will receive photos from one or more photobooth installations, support photo upvotes and reports, and provide a moderation workflow. The gallery is intended to run on a dedicated server or cloud service, so visitors can browse existing sessions even when no booths are running. A Raspberry Pi Zero or another browser-capable device can display a session slideshow.

The gallery is at the design stage; its initial architecture and proposed repository structure are documented in [`gallery/README.md`](gallery/README.md).
