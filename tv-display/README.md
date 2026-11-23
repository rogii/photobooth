# TV Display

## Purpose

The TV Display is the Raspberry Pi Zero client for Photobooth Gallery. It is a separate deployable component from the hosted gallery server and has its own installation script. The gallery server stays available independently; the Pi connects to it to show the session assigned to that display.

This folder currently contains the design plan only.

## Planned behavior

- On first boot, provide a local Wi-Fi setup flow so the installer can connect the Pi to the venue network without manually editing files on the device.
- Open the same stable TV URL on the gallery server on every boot.
- Until paired, show a setup code on the TV. An administrator enters the code in the gallery admin interface and assigns a session to that TV.
- Store a revocable device credential after pairing. The setup code is temporary and must not be reused as the long-lived credential.
- Reconnect and resume the assigned session after a network interruption or reboot.
- Use four GPIO buttons for upvote, previous slide, next slide, and setup/menu. Button presses should have debouncing and visible on-screen feedback.
- Allow the TV to upvote only the currently eligible automatic slideshow appearance. Manual navigation makes slides ineligible, and resuming autoplay alone does not create a new vote opportunity.

## Proposed implementation

- A lightweight Python service handles GPIO input, local configuration, Wi-Fi setup mode, pairing state, and communication with the gallery API.
- A kiosk browser renders the slideshow from the gallery's stable TV URL. Keep the page and delivered image sizes lightweight for Raspberry Pi Zero hardware.
- Store Wi-Fi credentials and the paired device credential in local files with restrictive permissions. Provide a documented way to reset pairing and Wi-Fi configuration.
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
│   └── gallery_client.py   # Pairing and vote API requests
└── systemd/
    ├── tv-display.service  # Local controller service
    └── tv-kiosk.desktop    # Browser kiosk autostart
```

The exact Wi-Fi setup mechanism (temporary access point, Bluetooth-assisted setup, or another approach) remains to be selected based on Raspberry Pi OS support and venue usability.

## Setup and pairing flow

1. Install the TV Display software on the Pi Zero using its installation script.
2. Connect to the Pi's setup flow and enter venue Wi-Fi credentials.
3. The Pi opens the stable gallery TV URL and displays a setup code because it has not been paired yet.
4. In the gallery admin interface, enter the code and assign the session for that TV.
5. The gallery pairs the display and provides a revocable device credential; the TV then loads its assigned slideshow.

If the venue Wi-Fi changes, the local setup flow should be available without requiring a keyboard attached to the TV. If the TV is unpaired or its credential is revoked, it should return to the setup-code screen.
