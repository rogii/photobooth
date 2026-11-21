# photobooth

Första provskottet för fotobåset finns i [`photobooth/`](photobooth/). Det är en lokal Python-app för Raspberry Pi med touchgränssnitt, gPhoto2-kamerastyrning, Bluetoothknapp som tangentbord, GPIO-blixt, fyrbildskollage och beständig uppladdningskö.

Se [`photobooth/README.md`](photobooth/README.md) för installation och autostart. Prototypen använder gPhoto2:s `--capture-preview` för livevy; kontrollera först att det fungerar med kameramodellen.
