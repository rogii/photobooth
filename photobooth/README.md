# Raspberry Pi fotobås

Fotobåset körs som en lokal Flask-webbapp i Chromium kiosk mode. Gränssnittet är vanlig HTML, CSS och JavaScript, så det går att prova och ändra i en vanlig webbläsare utan Raspberry Pi eller kamera.

## Prova gränssnittet lokalt

Från projektmappen:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py --demo
```

Öppna kioskvisningen på [http://127.0.0.1:8080](http://127.0.0.1:8080) och adminpanelen på [http://127.0.0.1:8081/admin](http://127.0.0.1:8081/admin). Demoläget skapar exempelbilder och låtsasfoton utan kamera eller GPIO. Det går även att visa webbsidan från en annan dator på samma nätverk genom att starta servern med `--host 0.0.0.0`; använd Pi:ns eller datorns IP-adress på port 8080 för kiosken och port 8081/admin för adminpanelen.

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

På Raspberry Pi OS använder kioskstartaren Chromium i helskärmsläge på `http://127.0.0.1:8080`. Servern lyssnar även på nätverksgränssnitten så en annan dator på samma nät kan öppna Pi:ns adress på port 8080 för kiosken eller 8081/admin för administration.

## Anslutning till befintlig Pi

- SSH-värd: `10.66.25.48`
- SSH-användare: `jonas`
- Klonad repo: `/home/jonas/photobooth`
- Appkatalog som tjänsten kör från: `/home/jonas/photobooth/photobooth`
- Tjänst: `photobooth.service` (systemd user service)

Anslut med `ssh jonas@10.66.25.48`. Synka projektets `photobooth/`-katalog till samma sökväg under klonens rot, med relativa sökvägar bevarade, så att appens `static/`-filer hamnar i appkatalogens `static/`. Starta sedan om tjänsten med `systemctl --user restart photobooth.service` och kontrollera den med `systemctl --user status photobooth.service`.

## Funktioner

- Alla exponeringar sparas lokalt i `~/Photobooth/<eventnamn>/` med tidsstämpel i filnamnet (`YYYYMMDD-HHMMSS-microseconds.jpg`). Enstaka bilder ligger direkt i eventmappen. Fyrbildsläget sparar originalrutorna i `singles/` och kollaget direkt i eventmappen, så endast kollaget läggs till i galleriet.
- Kioskens viloläge visar de senaste kolumnantalet i kvadrat av bilder från aktivt event i en kolumninställbar bildvägg, nyast överst till vänster. Bildrutorna fylls utan svarta fält och galleriet får inga rullningslister. Antalet rader beräknas automatiskt och originalfilerna används utan genererade miniatyrbilder. Under fotograferingen visas nedräkning och kamerans exponering. För fyrbildssekvensen visas aktuell bild (1/4–4/4) med separat inställbar nedräkning inför varje bild. Efter varje färdig kameraexponering visas simulerad "Capture download progress" innan nästa bild startar. En nedräkning på 0 utelämnar både nedräkningen och "SMILE"-pausen.
- En ny fotografering kan startas direkt från resultatbilden med `A` (en bild) eller `B` (fyra bilder). Annars återgår kiosken efter den konfigurerade visningstiden.
- Adminpanelen på port 8081 visar systemstatus, låter administratören starta ett event, ändra beständiga inställningar och starta om tjänsten. Kioskvisningen ligger på port 8080.
- GPIO-blixt med standard BCM 17. Driv inte LED-slingor direkt från Pi:n; använd lämplig transistor/MOSFET eller LED-styrenhet och separat strömförsörjning.
- Beständig lokal uppladdningskö. `upload_url` och `upload_token` i `config.json` styr multipart-uppladdning.

## Inställningar

Ändra nedräkning för en bild, separat nedräkning inför varje bild i fyrbildssekvensen, intervall, antal kolumner i vilogalleriet och visningstid i adminpanelen. Ändringarna skrivs beständigt till `config.json`. Övriga hårdvaru- och uppladdningsinställningar finns fortfarande i samma fil.

Installationsskriptet ska köras som skrivbordsanvändaren eftersom det installerar en användartjänst och autostartfil i den användarens hemkatalog.
