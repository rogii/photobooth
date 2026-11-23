# Raspberry Pi fotobås

Fotobåset är avsett att köras på Raspberry Pi med Raspberry Pi OS Desktop. Installationen har testats framgångsrikt på en Raspberry Pi 5. Appen använder Flask, Chromium i kiosk-läge, gPhoto2 för kameran och GPIO för blixten. Webbgränssnittet kan även provas i demoläge på en vanlig dator.

## Prova gränssnittet lokalt

Från projektmappen:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py --demo
```

Öppna kiosken på `localhost:8080` och den vanliga adminpanelen på `localhost:8081`. Demoläget skapar exempelbilder utan kamera eller GPIO.

## Installera på Raspberry Pi

Använd Raspberry Pi OS Desktop. Aktivera automatisk inloggning till skrivbordet om kiosken ska starta efter omstart. Kör från projektmappen:

```sh
cd photobooth
chmod +x install.sh launch-kiosk.sh
./install.sh
```

Kör installationsskriptet som skrivbordsanvändaren, inte som root. Skriptet installerar beroenden, skapar den virtuella Python-miljön, installerar en `systemd --user`-tjänst och lägger Chromium i skrivbordets autostart. Det använder `sudo` för systempaket och för begränsade rättigheter till avstängningskommandot. Installationsanvändaren läggs till i gruppen `gpio`, och GPIO-enheterna får läs- och skrivåtkomst för den gruppen. Om användaren nyligen lagts till i gruppen behöver Pi:n startas om så att tjänsten får den nya gruppåtkomsten. Lägg även till andra konton som ska använda blixten i gruppen `gpio`.

Kiosken öppnas lokalt på port 8080. Den vanliga adminpanelen använder port 8081.

Starta om tjänsten och visa dess status eller loggar med:

```sh
systemctl --user restart photobooth.service
systemctl --user status photobooth.service
journalctl --user -u photobooth.service -f
```

Chromium ansluter igen när tjänsten har startats om. Kameran ansluts via USB. Kontrollera kameran med:

```sh
gphoto2 --auto-detect
gphoto2 --capture-preview --filename /tmp/preview.jpg
```

## Funktioner

- Alla exponeringar sparas lokalt i `~/Photobooth/` med tidsstämpel i filnamnet (`YYYYMMDD-HHMMSS-microseconds.jpg`). Varje ny session har en egen bildmapp; äldre sessioner använder eventnamnets mapp. Enstaka bilder ligger direkt i sessionsmappen. Fyrbildsläget sparar originalrutorna i `singles/` och kollaget i sessionsmappen, så endast kollaget läggs till i galleriet.
- Kioskens viloläge visar de senaste bilderna från aktiv session i en kolumninställbar bildvägg, nyast överst till vänster. Bildrutorna behåller bildens bildförhållande och den nedersta raden beskärs av skärmkanten. Under fotograferingen visas nedräkning och kamerans exponering. När nedräkningen når noll ligger "SMILE" kvar med information om att fotot fångas och laddas ned från kameran. För fyrbildssekvensen visas aktuell bild (1/4–4/4) med separat inställbar nedräkning inför varje bild. Resultatet visas så snart kamerafångst och bildbehandling är klara, utan en extra simulerad nedladdningsvy. En nedräkning på 0 utelämnar nedräkningen och "SMILE"-pausen.
- En ny fotografering kan startas direkt från resultatbilden med `A` (en bild) eller `B` (fyra bilder). Annars återgår kiosken efter den konfigurerade visningstiden.
- Kiosken på port 8080 visar vid start en lista över sparade, synliga sessioner, nyast först, eller låter dig skapa en ny session med skärmtangentbordet. Den vanliga adminpanelen på port 8081 behåller sina befintliga funktioner för sessioner, fångst, inställningar och ZIP-nedladdning. En separat lokal admin öppnas från kiosken genom att hålla på internetstatusen i sidfoten och ange PIN-koden (standard `1234`). Där kan foton förhandsgranskas, flyttas till en `deleted/`-mapp utan att tas bort permanent, och Raspberry Pi:n stängas av. Flyttade foton döljs från galleriet och räknaren men följer med i sessions-ZIP:en. PIN-koden ändras i den lokala adminsidan. En session kan fästas på displayen så den återställs efter omstart och kiosken hoppar över valdialogen. Att avfästa eller stoppa sessionen återför kiosken direkt till sessionsvalet. Kioskens bildvägg visar internetstatus i sidfoten.
- GPIO-blixten kan konfigureras efter installationens hårdvara. Driv inte LED-slingor direkt från Pi:n; använd lämplig transistor/MOSFET eller LED-styrenhet och separat strömförsörjning.
- Beständig lokal uppladdningskö. `upload_url` och `upload_token` i `config.json` styr multipart-uppladdning.

## Inställningar

Ändra nedräkning för en bild, separat nedräkning inför varje bild i fyrbildssekvensen, kamerans förtriggning, intervall, antal kolumner i vilogalleriet och visningstid i adminpanelen. Kamerans förtriggning startar gPhoto2-kommandot det valda antalet sekunder innan nedräkningens nollpunkt; den kan kalibreras separat för kameran och miljön. Ändringarna skrivs beständigt till `config.json`. Övriga hårdvaru- och uppladdningsinställningar finns fortfarande i samma fil.

Installationsskriptet ska köras som skrivbordsanvändaren eftersom det installerar en användartjänst och autostartfil i den användarens hemkatalog.
