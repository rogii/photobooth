# Raspberry Pi fotobås

Fotobåset körs som en lokal Flask-webbapp i Chromium kiosk mode. Gränssnittet är vanlig HTML, CSS och JavaScript, så det går att prova och ändra i en vanlig webbläsare utan Raspberry Pi eller kamera.

## Prova gränssnittet lokalt

Från projektmappen:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py --demo
```

Öppna kioskvisningen på [http://127.0.0.1:8080](http://127.0.0.1:8080) och adminpanelen på [http://127.0.0.1:8081](http://127.0.0.1:8081) eller `/admin`. Demoläget skapar exempelbilder och låtsasfoton utan kamera eller GPIO. Det går även att visa webbsidan från en annan dator på samma nätverk genom att starta servern med `--host 0.0.0.0`; använd Pi:ns eller datorns IP-adress på port 8080 för kiosken och port 8081 för adminpanelen.

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

- Alla exponeringar sparas lokalt i `~/Photobooth/` med tidsstämpel i filnamnet (`YYYYMMDD-HHMMSS-microseconds.jpg`). Varje ny session har en egen bildmapp; äldre sessioner använder eventnamnets mapp. Enstaka bilder ligger direkt i sessionsmappen. Fyrbildsläget sparar originalrutorna i `singles/` och kollaget i sessionsmappen, så endast kollaget läggs till i galleriet.
- Kioskens viloläge visar de senaste bilderna från aktiv session i en kolumninställbar bildvägg, nyast överst till vänster. Bildrutorna behåller bildens bildförhållande och den nedersta raden beskärs av skärmkanten. Under fotograferingen visas nedräkning och kamerans exponering. När nedräkningen når noll ligger "SMILE" kvar med information om att fotot fångas och laddas ned från kameran. För fyrbildssekvensen visas aktuell bild (1/4–4/4) med separat inställbar nedräkning inför varje bild. Resultatet visas så snart kamerafångst och bildbehandling är klara, utan en extra simulerad nedladdningsvy. En nedräkning på 0 utelämnar nedräkningen och "SMILE"-pausen.
- En ny fotografering kan startas direkt från resultatbilden med `A` (en bild) eller `B` (fyra bilder). Annars återgår kiosken efter den konfigurerade visningstiden.
- Kiosken på port 8080 visar vid start en lista över sparade, synliga sessioner, nyast först, eller låter dig skapa en ny session med skärmtangentbordet. Adminpanelen på port 8081 kan skapa och välja session, dölja sessioner från kioskens startlista, ladda ned en sessions exponeringar som ZIP och radera en session med dess bilder. Den visar även lagringsutrymme och internetstatus. En session kan fästas på displayen så den återställs efter omstart och kiosken hoppar över valdialogen. Att avfästa eller stoppa sessionen återför kiosken direkt till sessionsvalet. Kioskens bildvägg visar internetstatus i sidfoten.
- GPIO-blixt med standard BCM 17. Driv inte LED-slingor direkt från Pi:n; använd lämplig transistor/MOSFET eller LED-styrenhet och separat strömförsörjning.
- Beständig lokal uppladdningskö. `upload_url` och `upload_token` i `config.json` styr multipart-uppladdning.

## Inställningar

Ändra nedräkning för en bild, separat nedräkning inför varje bild i fyrbildssekvensen, kamerans förtriggning, intervall, antal kolumner i vilogalleriet och visningstid i adminpanelen. Kamerans förtriggning startar gPhoto2-kommandot det valda antalet sekunder innan nedräkningens nollpunkt; den kan kalibreras separat för kameran och miljön. Ändringarna skrivs beständigt till `config.json`. Övriga hårdvaru- och uppladdningsinställningar finns fortfarande i samma fil.

Installationsskriptet ska köras som skrivbordsanvändaren eftersom det installerar en användartjänst och autostartfil i den användarens hemkatalog.
