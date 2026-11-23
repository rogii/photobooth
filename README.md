# photobooth

Fotobåset finns i [`photobooth/`](photobooth/). Projektet riktar sig till Raspberry Pi med Raspberry Pi OS Desktop och har testats framgångsrikt på Raspberry Pi 5. Det är en lokal Flask-webbapp som körs som en systemd-användartjänst med Chromium kiosk-gränssnitt, gPhoto2-kamerastyrning, Bluetoothknapp, GPIO-blixt, fyrbildskollage och beständig uppladdningskö.

Bilder sparas lokalt per event. Kiosken visar en sorterad bildvägg i viloläge och växlar till nedräkning, sparförlopp och helskärmsresultat vid fotografering. Adminpanelen körs på en separat port för status, inställningar och omstart. Se [`photobooth/README.md`](photobooth/README.md) för lokal demokörning, installation och kiosk-autostart.
