# Photobooth Remote

The remote will pair with the photobooth's Raspberry Pi as a Bluetooth Low Energy (BLE) HID keyboard. One button will trigger a single photo and the other will trigger a four-shot sequence. This folder contains the hardware and firmware design. The Arduino sketch will live here once implemented.

## Parts

- Seeed Studio XIAO nRF52840 (standard model).
- One protected, single-cell 3.7 V LiPo battery rated for the board's charge current.
- Two normally open momentary pushbuttons and hookup wire.
- A USB-C data cable for programming and charging.

## Wiring diagram

```text
Seeed Studio XIAO nRF52840                 External wiring

D1 (P0.03)  ────────────────────o/ o────┐  SW1 · Single photo
D2 (P0.28)  ────────────────────o/ o────┤  SW2 · Four-shot sequence
GND         ────────────────────────────┘  Common switch return

BAT+ (underside) ────────────────────────  LiPo positive (+)
BAT− (underside) ────────────────────────  LiPo negative (−)
```

Configure `D1` and `D2` as `INPUT_PULLUP`. Each input reads `HIGH` at rest and `LOW` when its switch closes to `GND`. The pull-ups are internal to the nRF52840. On a four-leg tactile switch, use a pair of terminals that only gains continuity when the button is pressed.

Check battery polarity against the board's underside pinout and use the dedicated battery pads. The board charges the cell over USB-C. Check that the selected charge current suits the cell before charging. [Seeed board pinout and charging documentation](https://wiki.seeedstudio.com/XIAO_BLE/)

## Arduino firmware plan

1. Add the [Seeed Boards Manager index](https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json) in Arduino IDE preferences. Install **Seeed nRF52 Boards** and select the board entry for the standard XIAO nRF52840.
2. Use the bundled Adafruit Bluefruit nRF52 library (`bluefruit.h`) and its `BLEHidAdafruit` service. Start with **File → Examples → Adafruit Bluefruit nRF52 Libraries → Peripheral → blehid_keyboard** to verify keyboard pairing over BLE. [Seeed BLE keyboard example](https://wiki.seeedstudio.com/XIAO-BLE-Sense-Bluetooth_Usage/)
3. Advertise as **Photobooth Remote** and resume advertising on disconnect so a paired Pi can reconnect. The firmware should start on battery power without waiting for the USB serial monitor.
4. Debounce each input independently. On a stable press while connected, send one unmodified key press followed by a key release. Require a physical release before sending another keystroke. Discard button presses made while disconnected.

| Button | GPIO | Default key | Photobooth action |
| --- | --- | --- | --- |
| SW1 | `D1` | `a` | Single photo |
| SW2 | `D2` | `b` | Four-shot sequence |

Pair the remote through **Bluetooth remote** in the kiosk's PIN-protected local admin or in the network admin. The backend reads the selected device's HID key presses through Linux input. The table above is the remote mapping and applies independently of the configurable kiosk shortcuts, including when Chromium is out of focus. [Photobooth setup](../photobooth/README.md#bluetooth-capture-remote)

For battery reporting, the firmware can expose an estimated percentage through Bluefruit's standard BLE Battery Service (`BLEBas`). The Pi can read the level through BlueZ's `org.bluez.Battery1` D-Bus interface if available for the connected device. [BlueZ Battery API](https://bluez.readthedocs.io/en/latest/battery-api/)

## Prototype checks

- Before selecting the remote in Photobooth Admin, verify that it pairs as a BLE keyboard and each button types its expected letter once, even when held down.
- After selecting the remote in Photobooth Admin, verify single-photo and four-shot capture with an active session and the kiosk out of focus. Confirm that the remote's keys stay out of any focused text field.
- Disconnect USB-C to verify battery operation, then reset the remote and confirm that it reconnects without pairing again or triggering a capture on reconnect.
