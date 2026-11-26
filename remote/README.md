# Photobooth Remote

The remote pairs with the photobooth's Raspberry Pi as a Bluetooth Low Energy (BLE) HID keyboard. One button triggers a single photo and the other triggers a four-shot sequence. The Arduino sketch is in [photobooth_remote](photobooth_remote/photobooth_remote.ino).

## Parts

- Seeed Studio XIAO nRF52840 (standard model).
- One protected, single-cell 3.7 V LiPo battery rated for the board's charge current.
- Two WANGCL ELZ22579 arcade buttons (ASIN B09SKZNWDH) with normally open microswitch contacts and separate LED terminals, plus hookup wire. [Button reference](https://www.amazon.se/dp/B09SKZNWDH)
- One Pololu U3V16F12 12 V boost module and one SPST switch (SW3) to disconnect its battery feed during charging. [Boost module pinout and load curves](https://www.pololu.com/product/4945)
- One TPS22918 load switch (U2), one 100 kΩ pull-down (R3), and one 2.2 µF ceramic input bypass capacitor (C1). [Load-switch datasheet](https://www.ti.com/lit/ds/symlink/tps22918.pdf)
- Two AO3400A N-channel MOSFETs (Q1, Q2) and two 100 kΩ gate pull-down resistors (R1, R2). [MOSFET datasheet](https://www.aosmd.com/res/datasheets/AO3400A.pdf)
- A USB-C data cable for programming and charging.

## Schematic

```text
Power
  Protected LiPo (+) ----+---------- XIAO BAT+
                         +-- SW3 --- U2 VIN (1)
  Protected LiPo (-) ----+---------- XIAO BAT-
                         +---------- GND
  U1 GND --------------------------- GND
  U1 VOUT -------------------------- +12V_LED
  U1 = Pololu U3V16F12
  U2 = TPS22918
  U2 VIN (1) ---- C1 2.2 µF --------- GND
  U2 GND (2) ----------------------- GND
  U2 VOUT (6) ---------------------- U1 VIN
  U2 CT (4) and QOD (5) left open
  XIAO D5 (P0.05) -----+------------ U2 ON (3)
                       +-- R3 100 kΩ -- GND

Button contacts
  XIAO D1 (P0.03) ---- SW1 (NO) ---- GND    Single photo
  XIAO D2 (P0.28) ---- SW2 (NO) ---- GND    Four-shot sequence
  XIAO GND ------------------------- GND

Button LED circuits
  +12V_LED ---- LED1 (+ to -) ------- Q1 D (3)    LED inside SW1
  XIAO D3 (P0.29) -----+------------ Q1 G (1)
                       +-- R1 100 kΩ -- GND
  GND ------------------------------ Q1 S (2)

  +12V_LED ---- LED2 (+ to -) ------- Q2 D (3)    LED inside SW2
  XIAO D4 (P0.04) -----+------------ Q2 G (1)
                       +-- R2 100 kΩ -- GND
  GND ------------------------------ Q2 S (2)

  Q1, Q2 = AO3400A
```

Configure `D1` and `D2` as `INPUT_PULLUP`. Each input reads `HIGH` at rest and `LOW` when its switch closes to `GND`. With power disconnected, use a continuity meter to identify the normally open contact pair on each button, then identify the separate LED terminals and polarity.

The boost module powers only the LED circuits. Leave the XIAO's USB 5 V and 3V3 pins disconnected from `+12V_LED`. The XIAO's 3.3 V GPIOs drive the MOSFET gates, and the 100 kΩ pull-downs hold the LEDs off during reset.

A retailer listing for the exact ASIN specifies 12 V illumination. The schematic assumes a 12 V LED assembly with built-in current limiting. Confirm the rating, polarity and current limiting on the actual parts before wiring them to the boost rail. [Retailer specifications](https://www.desertcart.in/products/469788738-wangcl-10pcs-led-lit-arcade-push-buttons-with-micro-switch) If a button contains a bare LED, add a series resistor in its branch based on that LED's forward voltage and rated current.

Check battery polarity against the board's underside pinout and use the dedicated battery pads. Open SW3 before USB-C charging to remove the LED and boost load from the cell. SW3 controls only the LED supply. Check that the selected charge current suits the cell before charging. [Seeed board pinout and charging documentation](https://wiki.seeedstudio.com/XIAO_BLE/)

## Build and upload

1. Add the [Seeed Boards Manager index](https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json) in Arduino IDE preferences. Install **Seeed nRF52 Boards** and select the board entry for the standard XIAO nRF52840.
2. Open `remote/photobooth_remote/photobooth_remote.ino` and upload over USB-C. The sketch uses the Bluefruit library bundled with the board package. It starts on battery power without waiting for a serial monitor. [Seeed BLE keyboard example](https://wiki.seeedstudio.com/XIAO-BLE-Sense-Bluetooth_Usage/)

The sketch compiles with Seeed nRF52 Boards 1.1.13. To build with Arduino CLI, run this from the repository root.

```sh
arduino-cli compile --fqbn Seeeduino:nrf52:xiaonRF52840 remote/photobooth_remote
```

## Operation

The device advertises as **Photobooth Remote** and resumes advertising after disconnects. Both button LEDs blink together at 1 Hz while advertising or waiting for a secure HID link. They stay lit once the link is encrypted and the host has enabled keyboard reports. Both buttons must be released before capture is armed after connecting. Each debounced press sends one unmodified key press and release. A held button sends a single keystroke, and presses made while disconnected are discarded.

| Button | GPIO | Default key | Photobooth action |
| --- | --- | --- | --- |
| SW1 | `D1` | `a` | Single photo |
| SW2 | `D2` | `b` | Four-shot sequence |

Pair the remote through **Bluetooth remote** in the kiosk's PIN-protected local admin or in the network admin. The backend reads the selected device's HID key presses through Linux input. The table above is the remote mapping and applies independently of the configurable kiosk shortcuts, including when Chromium is out of focus. [Photobooth setup](../photobooth/README.md#bluetooth-capture-remote)

Battery percentage reporting is optional future work. Bluefruit can expose an estimate through its standard BLE Battery Service (`BLEBas`), which BlueZ can expose through `org.bluez.Battery1`. [BlueZ Battery API](https://bluez.readthedocs.io/en/latest/battery-api/)

## Low-power operation

Use the nRF52840's **System ON idle** between button presses to keep the BLE HID connection active. Use GPIO interrupts on `D1` and `D2` to wake the application for button changes. Have the interrupt signal the application, then debounce and send HID reports outside the interrupt handler. Block the application while waiting for GPIO events or the next debounce or LED deadline so the BLE stack can handle scheduled radio events and the CPU can idle between them. [Nordic nRF52840 product specification](https://devzone.nordicsemi.com/cfs-file/__key/communityserver-discussions-components-files/4/nRF52840_5F00_PS_5F00_v1.8.pdf)

1. Start a 15-minute inactivity timer at boot or wake. Restart it on each debounced button press. Apply the timeout both while connected and while advertising so an unavailable Pi cannot keep the remote awake indefinitely.
2. At timeout, wait for both buttons to be released so a held button cannot immediately wake the remote. Drive `D3` and `D4` low to turn off the LEDs and drive `D5` low to disconnect the boost module from the battery. Disconnect BLE or stop advertising, configure both button inputs with pull-ups and active-low GPIO sense, then enter **System OFF**. If a new press arrives during shutdown, treat it as activity and stay awake.
3. Press either button to wake from System OFF. Wake resets the chip and preserves the bond stored in flash. Enable the boost module with `D5`, advertise, and blink both LEDs until the secure HID connection is restored. The wake press only wakes the remote. Require both buttons to be released and a fresh press after reconnect before sending a capture key.
4. The kiosk already shows a wake prompt when a configured remote is disconnected during an active, idle session and clears it when the remote reconnects.

R3 holds the boost feed off during reset. Measure total battery current with both LEDs lit and again in System OFF with SW3 closed to verify that the automatic cutoff saves power.

## Prototype checks

- With SW3 closed and USB-C unplugged, verify 12 V on `+12V_LED` with both LEDs on. Measure both LED branch currents and total battery current to check the load against the module's output curve and the cell's discharge rating.
- Confirm both LEDs blink during advertising and pairing, glow steadily once the HID link is secure, and resume blinking when the Pi disconnects. Check that both return to steady on after reconnecting.
- Leave the remote connected and idle, then verify that the first press of either button triggers its expected action once without reconnecting.
- Leave the remote idle for 15 minutes. Confirm that both LEDs go out, the boost input loses battery power, and the kiosk displays the wake prompt. Check the same timeout with the Pi unavailable. Wake with each button in turn, including a held press, and verify that the prompt clears on reconnect and capture requires a fresh press.
- Before selecting the remote in Photobooth Admin, verify that it pairs as a BLE keyboard and each button types its expected letter once, even when held down.
- After selecting the remote in Photobooth Admin, verify single-photo and four-shot capture with an active session and the kiosk out of focus. Confirm that the remote's keys stay out of any focused text field.
- Disconnect USB-C to verify battery operation, then reset the remote and confirm that it reconnects without pairing again or triggering a capture on reconnect.
