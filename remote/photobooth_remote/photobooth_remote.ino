#include <bluefruit.h>
#include <FreeRTOS.h>
#include <task.h>
#include <class/hid/hid.h>

namespace {

constexpr uint8_t SingleLed = D3;
constexpr uint8_t SequenceLed = D4;
constexpr uint8_t StatusLed = D5;
constexpr uint32_t DebounceMs = 25;
constexpr uint32_t BlinkHalfPeriodMs = 500;
constexpr uint32_t RetryMs = 20;
constexpr uint32_t SingleEdge = 1 << 0;
constexpr uint32_t SequenceEdge = 1 << 1;
constexpr uint32_t LinkChanged = 1 << 2;
constexpr uint32_t HidChanged = 1 << 3;

struct Button {
  uint8_t pin;
  char key;
  uint32_t edge;
  bool rawPressed;
  bool pressed;
  uint32_t changedAt;
};

Button buttons[] = {
  {D1, 'a', SingleEdge, false, false, 0},
  {D2, 'b', SequenceEdge, false, false, 0},
};

class RemoteKeyboard : public BLEHidAdafruit {
 public:
  void setLedReportCallback(BLECharacteristic::write_cb_t callback) {
    // Run in the BLE event task so writes and disconnects stay in event order.
    _chr_outputs[0].setWriteCallback(callback, false);
    _chr_boot_keyboard_output->setWriteCallback(callback, false);
  }

  bool notificationsEnabled(uint16_t handle) {
    // Bluefruit uses input report ID 1 for the keyboard in report mode.
    BLECharacteristic& input = isBootMode() ? *_chr_boot_keyboard_input : _chr_inputs[0];
    return input.notifyEnabled(handle);
  }
};

RemoteKeyboard keyboard;
TaskHandle_t loopTask;
uint32_t events;
uint32_t blinkStarted;
bool wasReady;
bool wasSecured;
bool captureArmed;
bool releasePending;

void notifyButtonEdge(uint32_t edge) {
  BaseType_t taskWoken = pdFALSE;
  xTaskNotifyFromISR(loopTask, edge, eSetBits, &taskWoken);
  portYIELD_FROM_ISR(taskWoken);
}

void singleEdge() {
  notifyButtonEdge(SingleEdge);
}

void sequenceEdge() {
  notifyButtonEdge(SequenceEdge);
}

void setButtonLeds(uint8_t mask) {
  digitalWrite(SingleLed, (mask & KEYBOARD_LED_NUMLOCK) != 0);
  digitalWrite(SequenceLed, (mask & KEYBOARD_LED_CAPSLOCK) != 0);
}

void onLedReport(uint16_t, BLECharacteristic*, uint8_t* data, uint16_t length) {
  // Both HID output characteristics already require an encrypted link.
  if (length == 1) {
    setButtonLeds(data[0]);
  }
}

void onBleEvent(ble_evt_t* event) {
  switch (event->header.evt_id) {
    case BLE_GAP_EVT_CONNECTED:
    case BLE_GAP_EVT_DISCONNECTED:
      setButtonLeds(0);
      xTaskNotify(loopTask, LinkChanged, eSetBits);
      break;
    case BLE_GAP_EVT_CONN_SEC_UPDATE:
    case BLE_GATTS_EVT_WRITE:
    case BLE_GATTS_EVT_SYS_ATTR_MISSING:
      xTaskNotify(loopTask, HidChanged, eSetBits);
      break;
  }
}

bool linkSecured(uint16_t handle) {
  ble_gap_conn_sec_t security{};
  return handle != BLE_CONN_HANDLE_INVALID &&
         sd_ble_gap_conn_sec_get(handle, &security) == NRF_SUCCESS &&
         security.sec_mode.sm == 1 && security.sec_mode.lv >= 2;
}

TickType_t ticksForMs(uint32_t waitMs) {
  // Zero ticks can miss a short deadline on cores with a coarse tick period.
  const TickType_t ticks = pdMS_TO_TICKS(waitMs);
  return ticks ? ticks : 1;
}

}  // namespace

void setup() {
  loopTask = xTaskGetCurrentTaskHandle();
  const uint8_t outputs[] = {SingleLed, SequenceLed, StatusLed};
  for (uint8_t pin : outputs) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
  }
  for (const Button& button : buttons) {
    pinMode(button.pin, INPUT_PULLUP);
  }
  attachInterrupt(D1, singleEdge, CHANGE);
  attachInterrupt(D2, sequenceEdge, CHANGE);

  Bluefruit.autoConnLed(false);
  Bluefruit.begin(1, 0);
  Bluefruit.setName("Photobooth Remote");
  Bluefruit.setEventCallback(onBleEvent);
  blinkStarted = millis();
  if (keyboard.begin() != NRF_SUCCESS) {
    return;
  }
  keyboard.setLedReportCallback(onLedReport);

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addAppearance(BLE_APPEARANCE_HID_KEYBOARD);
  Bluefruit.Advertising.addService(keyboard);
  Bluefruit.Advertising.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setIntervalMS(20, 150);
  Bluefruit.Advertising.start(0);
}

void loop() {
  const uint32_t now = millis();
  const uint16_t handle = Bluefruit.connHandle();
  const bool secured = linkSecured(handle);
  const bool ready = secured && keyboard.notificationsEnabled(handle);
  const bool linkChanged = events & LinkChanged;
  if (!ready || !wasReady || linkChanged) {
    captureArmed = false;
  }
  if (linkChanged || handle == BLE_CONN_HANDLE_INVALID) {
    releasePending = false;
  }
  if (!secured && (wasSecured || linkChanged)) {
    blinkStarted = now;
  }
  wasReady = ready;
  wasSecured = secured;

  TickType_t waitTicks = portMAX_DELAY;
  bool allReleased = true;
  if (ready && releasePending) {
    releasePending = !keyboard.keyRelease(handle);
  }

  for (Button& button : buttons) {
    const bool raw = digitalRead(button.pin) == LOW;
    if (raw != button.rawPressed || (events & button.edge)) {
      button.rawPressed = raw;
      button.changedAt = now;
    }
    const uint32_t elapsed = now - button.changedAt;
    if (elapsed < DebounceMs) {
      waitTicks = min(waitTicks, ticksForMs(DebounceMs - elapsed));
    } else if (button.pressed != raw) {
      button.pressed = raw;
      if (raw && captureArmed && !releasePending && keyboard.keyPress(handle, button.key)) {
        releasePending = !keyboard.keyRelease(handle);
      }
    }
    allReleased &= !raw && !button.pressed && elapsed >= DebounceMs;
  }
  if (ready && allReleased) {
    captureArmed = true;
  }
  if (ready && releasePending) {
    waitTicks = min(waitTicks, ticksForMs(RetryMs));
  }

  if (secured) {
    digitalWrite(StatusLed, LOW);
  } else {
    const uint32_t blinkMs = (now - blinkStarted) % (2 * BlinkHalfPeriodMs);
    digitalWrite(StatusLed, blinkMs < BlinkHalfPeriodMs);
    waitTicks = min(waitTicks, ticksForMs(BlinkHalfPeriodMs - blinkMs % BlinkHalfPeriodMs));
  }
  events = 0;
  xTaskNotifyWait(0, UINT32_MAX, &events, waitTicks);
}
