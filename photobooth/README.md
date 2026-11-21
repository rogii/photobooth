# Raspberry Pi fotobås – provskott

En första, lokal prototyp med Python/Tkinter. Den kan köras med mus/touch eller med en Bluetooth-knapp som skickar tangentbordskommandona `a` (en bild) och `b` (fyra bilder). Fyrbildsläget sparar originalen och skapar ett 2×2-kollage.

## Installation på Raspberry Pi OS

Lägg projektet på Pi:n och kör från skrivbordsterminalen:

```sh
cd photobooth
chmod +x install.sh
./install.sh
```

Skriptet installerar Python, Tkinter, GPIOZero/lgpio och gPhoto2, skapar en virtuell miljö och lägger till en desktop-autostartfil för den inloggade skrivbordsanvändaren. För autostart efter omstart ska Raspberry Pi OS starta direkt till skrivbordet med automatisk inloggning aktiverad (ställ in via `sudo raspi-config` → System Options → Boot / Auto Login → Desktop Autologin). Appen startar då från skrivbordets autostart. Den behöver en grafisk session; detta är inte en headless systemd-tjänst.

Kameran ansluts via USB. Kontrollera först att den upptäcks och prova livevy:

```sh
gphoto2 --auto-detect
gphoto2 --capture-preview --filename /tmp/preview.jpg
```

Installationsskriptet måste köras som den användare som ska logga in på skrivbordet (vid körning via sudo används `SUDO_USER`).

## Inställningar

Redigera `config.json`:

- `countdown_seconds`: nedräkningens standardvärde (kan också justeras i touchvyn).
- `sequence_interval_seconds`: intervall mellan exponeringarna i fyrbildsläget (justeras också i touchvyn).
- `gpio_flash_pin`: GPIO-nummer, standard BCM 17.
- `flash_seconds`: hur länge GPIO-signalen är aktiv vid varje exponering.
- `key_single` / `key_sequence`: tangentkommandon från Bluetoothknappen.
- `upload_url` / `upload_token`: multipart-API för uppladdning; lämna URL tom för lokal drift.

Uppladdnings-API:t förväntas ta emot multipart-fälten `image`, `session_id`, `session_name` och `idempotency_key`. Jobben ligger beständigt i `~/Photobooth/upload-queue/` och försöks igen tills API:t ger 2xx.

## Säkerhet och hårdvara

GPIO-pinnen är endast en styrsignal. Driv inte LED-slingan direkt från Pi:n; använd en transistor/MOSFET eller lämplig LED-styrenhet med separat strömförsörjning och gemensam jord enligt slingans specifikation. Standardinställningen håller blixten aktiv 180 ms vid varje exponering; anpassa efter vald hårdvara.

## Begränsningar i provskottet

- Livevyn är en återkommande stillbild från `gphoto2 --capture-preview`, inte en flytande videoström. Uppdatering och stöd beror på kameran. Om kameran inte stöder preview samtidigt med fjärrstyrning behöver den delen anpassas till kamerans liveview-läge.
- Flaskning/sekvenstakt beror på kamerans exponering, autofokus och bildöverföring. Det här provskottet väntar på att varje fil hämtas innan nästa exponering.
- Uppladdningsendpointen och webbappens API-kontrakt är ännu inte definierade. Prototypen köar lokalt tills `upload_url` konfigureras.
- Sessionens grundflöde finns, men avancerad sessionskonfiguration, användarhantering och galleri hör till nästa iteration.
