# TV Display

## Purpose

The TV Display is the Raspberry Pi Zero client for Photobooth Gallery. It is a separate deployable component from the hosted gallery server and has its own installation script. The gallery server stays available independently; the Pi connects to it to show the session assigned to that display.

This folder currently contains the design plan only.

## Planned behavior

- If no saved Wi-Fi connection reaches the internet, automatically start a temporary, password-protected Wi-Fi hotspot and local setup page.
- Show the hotspot name, password, and setup address on the TV screen, with a QR code where practical, so the installer can connect a phone without attaching a keyboard or using GPIO buttons for setup.
- Let the phone list nearby Wi-Fi networks by scanning from the Pi when supported, and allow manual SSID entry for hidden networks or when scanning is unavailable.
- Save the selected network credentials on the Pi, try the connection immediately, and use the saved network automatically on later boots.
- Open the same stable TV URL on the gallery server on every boot.
- Generate a random, stable device code on first boot and save it locally so the same TV is recognized after unexpected reboots. Include this device code in registration and subsequent identification calls to the gallery.
- Until paired, show the device code on the TV. An administrator enters it in the gallery admin interface and assigns a session to that TV.
- Treat the displayed device code as an identifier, not as a secret. After pairing, store and use a separate revocable device credential to authorize gallery API calls.
- Reconnect and resume the assigned session after a network interruption or reboot.
- Use GPIO buttons for upvote and previous/next slide controls; a fourth button can provide a playback control such as pause/resume. Wi-Fi and pairing setup should be completed from a phone, not through the buttons. Button presses should have debouncing and visible on-screen feedback.
- Allow the TV to upvote only the currently eligible automatic slideshow appearance. Manual navigation makes slides ineligible, and resuming autoplay alone does not create a new vote opportunity.

## Proposed implementation

- A lightweight Python service handles GPIO input, local configuration, hotspot fallback, the phone-based Wi-Fi setup page, pairing state, and communication with the gallery API.
- Use Raspberry Pi OS networking tools, preferably NetworkManager where available, to create the temporary access point, scan for networks, save credentials, and switch to the selected venue network. Scanning while the hotspot is active depends on the Wi-Fi adapter and driver; always offer manual SSID entry as a fallback.
- A kiosk browser renders the slideshow from the gallery's stable TV URL. Keep the page and delivered image sizes lightweight for Raspberry Pi Zero hardware.
- Store Wi-Fi credentials, the persistent device code, and the paired device credential locally with restrictive permissions. Provide a documented way to reset pairing and Wi-Fi configuration. Resetting or rotating the device code should require a new pairing.
- Install and manage the controller and kiosk startup as systemd user services, running as the normal Pi user rather than root. Use elevated privileges only where the installer needs them to configure system packages, GPIO access, or a network access point.
- Keep the gallery server authoritative for device pairing, session assignment, vote eligibility, and vote counts.

## Proposed folder structure

```text
tv-display/
├── README.md
├── install.sh              # Installs dependencies and configures the Pi client
├── requirements.txt        # Python dependencies for the local controller
├── config.example.json     # Non-secret defaults and gallery server URL
├── display/
│   ├── controller.py       # GPIO input and device state
│   ├── setup.py            # Local Wi-Fi and pairing setup flow
│   └── gallery_client.py   # Registration, pairing, and vote API requests
└── systemd/
    ├── tv-display.service  # Local controller service
    └── tv-kiosk.desktop    # Browser kiosk autostart
```

The Wi-Fi setup mechanism is a temporary access point with a phone-accessible local page. A scan list is preferred where supported; manual network name entry remains the fallback.

## Setup and pairing flow

1. Install the TV Display software on the Pi Zero using its installation script.
2. If Wi-Fi is not connected, the Pi starts its hotspot and displays the network name, password, and setup address (optionally as a QR code) on the TV.
3. Connect a phone to the hotspot and open the local setup page. Select a scanned venue network or enter its SSID manually, provide its password, and submit.
4. The Pi saves the credentials, attempts to connect, and turns off the setup hotspot after successful connection. It reuses the saved network on later boots.
5. The Pi creates and persists its random device code if it does not already have one, opens the stable gallery TV URL, and registers with the gallery using that code.
6. Until paired, the Pi displays its persistent device code. In the gallery admin interface, enter the code and assign the session for that TV.
7. The gallery pairs the display and provides a revocable device credential. The Pi stores that credential and uses it for authorized API calls; after a reboot, its saved device code and credential let it resume the same assignment.

If the saved Wi-Fi connection is unavailable, the Pi should return to hotspot setup and show the instructions on screen. If the TV is unpaired or its credential is revoked, it should show its persistent device code for pairing or re-pairing. GPIO buttons remain available for slideshow controls but are not needed to configure Wi-Fi or pairing.
