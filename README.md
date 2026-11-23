# photobooth

Fotobåset finns i [`photobooth/`](photobooth/). Det är en lokal Flask-webbapp som körs som en systemd-användartjänst med Chromium kiosk-gränssnitt, gPhoto2-kamerastyrning, Bluetoothknapp, GPIO-blixt, fyrbildskollage och beständig uppladdningskö.

Appen hämtar inte livebilder i viloläge; senaste fotot visas i 10 sekunder efter exponering. Se [`photobooth/README.md`](photobooth/README.md) för lokal demokörning, installation och kiosk-autostart.
