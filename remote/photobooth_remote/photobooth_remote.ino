#include <bluefruit.h>
#include <FreeRTOS.h>
#include <task.h>
#include <nrf_gpio.h>

namespace {

constexpr uint8_t SingleLed = D3;
constexpr uint8_t SequenceLed = D4;
constexpr uint8_t BoostEnable = D5;
constexpr uint32_t DebounceMs = 25;
constexpr uint32_t BlinkHalfPeriodMs = 500;
constexpr uint32_t IdleTimeoutMs = 15 * 60 * 1000;
constexpr uint32_t RetryMs = 20;
constexpr uint32_t SingleEdge = 1 << 0;
constexpr uint32_t SequenceEdge = 1 << 1;
constexpr uint32_t ButtonEdges = SingleEdge | SequenceEdge;
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
  bool ready(uint16_t handle) {
    ble_gap_conn_sec_t security{};
    if (handle == BLE_CONN_HANDLE_INVALID ||
        sd_ble_gap_conn_sec_get(handle, &security) != NRF_SUCCESS ||
        security.sec_mode.sm != 1 || security.sec_mode.lv < 2) {
      return false;
    }

    // Bluefruit uses input report ID 1 for the keyboard in report mode.
    BLECharacteristic& input = isBootMode() ? *_chr_boot_keyboard_input : _chr_inputs[0];
    return input.notifyEnabled(handle);
  }
};

RemoteKeyboard keyboard;
TaskHandle_t loopTask;
uint32_t events;
uint32_t lastActivity;
uint32_t blinkStarted;
bool wasReady;
bool captureArmed;
bool releasePending;
bool stopping;

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

void onBleEvent(ble_evt_t* event) {
  switch (event->header.evt_id) {
    case BLE_GAP_EVT_CONNECTED:
    case BLE_GAP_EVT_DISCONNECTED:
      xTaskNotify(loopTask, LinkChanged, eSetBits);
      break;
    case BLE_GAP_EVT_CONN_SEC_UPDATE:
    case BLE_GATTS_EVT_WRITE:
    case BLE_GATTS_EVT_SYS_ATTR_MISSING:
      xTaskNotify(loopTask, HidChanged, eSetBits);
      break;
  }
}

void setLeds(bool on) {
  digitalWrite(SingleLed, on);
  digitalWrite(SequenceLed, on);
}

void waitForEvent(uint32_t waitMs) {
  // Zero ticks can miss a short deadline on cores with a coarse tick period.
  const TickType_t ticks = pdMS_TO_TICKS(waitMs);
  events = 0;
  xTaskNotifyWait(0, UINT32_MAX, &events, ticks ? ticks : 1);
}

void cancelShutdown(uint32_t now) {
  lastActivity = now;
  blinkStarted = now;
  stopping = false;
  digitalWrite(BoostEnable, HIGH);
  Bluefruit.Advertising.restartOnDisconnect(true);
  if (Bluefruit.connHandle() == BLE_CONN_HANDLE_INVALID && !Bluefruit.Advertising.isRunning()) {
    Bluefruit.Advertising.start(0);
  }
}

void finishShutdown(uint32_t now) {
  for (const Button& button : buttons) {
    nrf_gpio_cfg_sense_input(g_ADigitalPinMap[button.pin], NRF_GPIO_PIN_PULLUP, NRF_GPIO_PIN_SENSE_LOW);
  }
  setLeds(false);
  digitalWrite(BoostEnable, LOW);

  // Check again with wake sense armed. An edge during shutdown counts as activity.
  uint32_t pending = 0;
  xTaskNotifyWait(0, UINT32_MAX, &pending, 0);
  if (!(pending & ButtonEdges) && digitalRead(D1) == HIGH && digitalRead(D2) == HIGH) {
    // The SoftDevice owns the power peripheral while Bluefruit is running.
    sd_power_system_off();
  }

  // System OFF normally resets on wake. This path handles an abort or failed entry.
  for (const Button& button : buttons) {
    pinMode(button.pin, INPUT_PULLUP);
  }
  cancelShutdown(now);
  events |= pending;
}

}  // namespace

void setup() {
  loopTask = xTaskGetCurrentTaskHandle();
  const uint8_t outputs[] = {SingleLed, SequenceLed, BoostEnable};
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
  keyboard.begin();

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addAppearance(BLE_APPEARANCE_HID_KEYBOARD);
  Bluefruit.Advertising.addService(keyboard);
  Bluefruit.Advertising.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setIntervalMS(20, 150);
  Bluefruit.Advertising.start(0);

  lastActivity = blinkStarted = millis();
  digitalWrite(BoostEnable, HIGH);
}

void loop() {
  const uint32_t now = millis();
  const uint16_t handle = Bluefruit.connHandle();
  const bool ready = !stopping && keyboard.ready(handle);
  const bool linkChanged = events & LinkChanged;
  if (!ready || !wasReady || linkChanged) {
    captureArmed = false;
  }
  if (linkChanged || handle == BLE_CONN_HANDLE_INVALID) {
    releasePending = false;
  }
  if (wasReady && (!ready || linkChanged)) {
    blinkStarted = now;
  }
  wasReady = ready;

  uint32_t waitMs = IdleTimeoutMs;
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
      waitMs = min(waitMs, DebounceMs - elapsed);
    } else if (button.pressed != raw) {
      button.pressed = raw;
      if (raw) {
        lastActivity = now;
        if (captureArmed && !releasePending && keyboard.keyPress(handle, button.key)) {
          releasePending = !keyboard.keyRelease(handle);
        }
      }
    }
    allReleased &= !raw && !button.pressed && elapsed >= DebounceMs;
  }
  if (ready && allReleased) {
    captureArmed = true;
  }
  if (ready && releasePending) {
    waitMs = min(waitMs, RetryMs);
  }

  if (stopping && (!allReleased || (events & ButtonEdges))) {
    cancelShutdown(now);
  }

  const uint32_t idleMs = now - lastActivity;
  if (idleMs < IdleTimeoutMs) {
    waitMs = min(waitMs, IdleTimeoutMs - idleMs);
  } else if (allReleased) {
    if (!stopping) {
      stopping = true;
      captureArmed = false;
      Bluefruit.Advertising.restartOnDisconnect(false);
    }
    if (Bluefruit.Advertising.isRunning()) {
      Bluefruit.Advertising.stop();
    }
    const uint16_t shutdownHandle = Bluefruit.connHandle();
    if (shutdownHandle != BLE_CONN_HANDLE_INVALID) {
      sd_ble_gap_disconnect(shutdownHandle, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
    } else if (!Bluefruit.Advertising.isRunning()) {
      finishShutdown(now);
      return;
    }
    waitForEvent(RetryMs);
    return;
  }

  const uint32_t blinkMs = (now - blinkStarted) % (2 * BlinkHalfPeriodMs);
  setLeds(ready || blinkMs < BlinkHalfPeriodMs);
  if (!ready) {
    waitMs = min(waitMs, BlinkHalfPeriodMs - blinkMs % BlinkHalfPeriodMs);
  }
  waitForEvent(waitMs);
}
