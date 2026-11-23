# Raspberry Pi fotobås

Fotobåset körs som en lokal Flask-webbapp i Chromium kiosk mode. Gränssnittet är vanlig HTML, CSS och JavaScript, så det går att prova och ändra i en vanlig webbläsare utan Raspberry Pi eller kamera.

## Prova gränssnittet lokalt

Från projektmappen:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py --demo
```

Öppna sedan [http://127.0.0.1:8080](http://127.0.0.1:8080). Demoläget skapar exempelbilder och låtsasfoton utan kamera eller GPIO. Det går även att visa webbsidan från en annan dator på samma nätverk genom att starta servern med `--host 0.0.0.0`; använd då Pi:ns eller datorns IP-adress på port 8080.

## Raspberry Pi kiosk

Kör på Raspberry Pi OS Desktop:

```sh
cd photobooth
chmod +x install.sh launch-kiosk.sh
./install.sh
```

Installationsskriptet installerar Python, Flask, gPhoto2 och Chromium, skapar `.venv`, installerar en `systemd --user`-tjänst och lägger Chromium kiosk i skrivbordets autostart. Kör skriptet som skrivbordsanvändaren, utan `sudo`. För autostart efter omstart ska Raspberry Pi OS starta till skrivbordet med automatisk inloggning (`sudo raspi-config` → System Options → Boot / Auto Login → Desktop Autologin).

Starta om webbservern över SSH eller från terminalen:

```sh
systemctl --user restart photobooth.service
```

Visa status och loggar med `systemctl --user status photobooth.service` och `journalctl --user -u photobooth.service -f`. Chromium ligger kvar öppet och ansluter igen efter omstarten.

Kameran ansluts via USB. Kontrollera anslutningen från terminalen:

```sh
gphoto2 --auto-detect
gphoto2 --capture-preview --filename /tmp/preview.jpg
```

På Raspberry Pi OS använder kioskstartaren Chromium i helskärmsläge på `http://127.0.0.1:8080`. Servern lyssnar även på nätverksgränssnitten så en annan dator på samma nät kan öppna Pi:ns adress på port 8080.

## Anslutning till befintlig Pi

- SSH-värd: `10.66.25.48`
- SSH-användare: `jonas`
- Klonad repo: `/home/jonas/photobooth`
- Appkatalog som tjänsten kör från: `/home/jonas/photobooth/photobooth`
- Tjänst: `photobooth.service` (systemd user service)

Anslut med `ssh jonas@10.66.25.48`. Synka projektets `photobooth/`-katalog till samma sökväg under klonens rot, med relativa sökvägar bevarade, så att appens `static/`-filer hamnar i appkatalogens `static/`. Starta sedan om tjänsten med `systemctl --user restart photobooth.service` och kontrollera den med `systemctl --user status photobooth.service`.

## Funktioner

- Ingen kameraförhandsvisning hämtas i viloläge. Efter en exponering visas fotot i huvudytan i 10 sekunder, eller tills nästa fotografering startar.
- Enstaka bilder och 2×2-kollage av fyra bilder, med justerbar nedräkning och intervall.
- Touchvänligt tangentbord för sessionsnamn och Bluetoothknapp som skickar `a` eller `b`.
- GPIO-blixt med standard BCM 17. Driv inte LED-slingor direkt från Pi:n; använd lämplig transistor/MOSFET eller LED-styrenhet och separat strömförsörjning.
- Beständig lokal uppladdningskö. `upload_url` och `upload_token` i `config.json` styr multipart-uppladdning.
- Tillfällig stoppknapp i gränssnittet för testkörningar.

## Inställningar

Redigera `config.json`:

- `countdown_seconds`: standardnedräkning.
- `sequence_interval_seconds`: standardpaus mellan fyrbildslägets exponeringar.
- `gpio_flash_pin` och `flash_seconds`: GPIO-signal och blixtlängd.
- `key_single` / `key_sequence`: tangentkommandon från Bluetoothknappen.
- `upload_url` / `upload_token`: uppladdnings-API. Jobben sparas i `~/Photobooth/upload-queue/` och försöks igen tills API:t ger 2xx.

Installationsskriptet ska köras som skrivbordsanvändaren eftersom det installerar en användartjänst och autostartfil i den användarens hemkatalog.
