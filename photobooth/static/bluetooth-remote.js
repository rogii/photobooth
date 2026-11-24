function setupBluetoothRemote(api) {
  const dialog = document.querySelector("[data-bluetooth-api]");
  const path = dialog.dataset.bluetoothApi;
  const scan = dialog.querySelector("#selfie-scan");
  const device = dialog.querySelector("#selfie-device");
  const pair = dialog.querySelector("#selfie-pair");
  const forget = dialog.querySelector("#selfie-forget");
  const connection = dialog.querySelector("#selfie-connection");
  const message = dialog.querySelector("#selfie-message");
  let busy = false;
  let configured = false;
  let scanDeadline = 0;
  let timer;
  let revision = 0;
  let listedDevices = "";

  function syncControls() {
    scan.disabled = busy;
    device.disabled = busy || device.options.length <= 1;
    pair.disabled = busy || !device.value;
    forget.disabled = busy || !configured;
  }

  function updateOptions(devices) {
    const snapshot = JSON.stringify(devices);
    if (listedDevices === snapshot) return;
    listedDevices = snapshot;
    const selected = device.value;
    device.replaceChildren(new Option("Choose a device", ""));
    for (const { name, address } of devices) {
      device.add(new Option(name === address ? address : `${name} (${address})`, address));
    }
    device.value = devices.some(({ address }) => address === selected) ? selected : "";
  }

  function showConnection(text) {
    if (connection.textContent !== text) connection.textContent = text;
  }

  function stopPolling() {
    clearTimeout(timer);
    revision += 1;
  }

  async function poll() {
    if (!dialog.open || busy) return;
    const currentRevision = revision;
    const scanning = scanDeadline !== 0;
    try {
      const state = await api(scanning ? path : `${path}?status_only=1`);
      if (currentRevision !== revision || !dialog.open) return;
      configured = state.configured;
      showConnection(state.connected ? "Bluetooth remote connected"
        : configured ? "Bluetooth remote disconnected" : "No Bluetooth remote selected");
      if (scanning) {
        updateOptions(state.devices);
        if (Date.now() >= scanDeadline) {
          scanDeadline = 0;
          message.textContent = state.devices.length ? "Scan complete." : "No devices found. Check pairing mode and scan again.";
        }
      }
      syncControls();
    } catch (error) {
      if (currentRevision !== revision || !dialog.open) return;
      if (scanning) {
        scanDeadline = 0;
        message.textContent = error.message;
      } else {
        showConnection(error.message);
      }
    }
    timer = setTimeout(poll, 2000);
  }

  async function update(body, pending, success) {
    if (busy) return;
    stopPolling();
    scanDeadline = 0;
    busy = true;
    syncControls();
    message.textContent = pending;
    try {
      await api(path, body);
      if (body.scan) scanDeadline = Date.now() + 43000;
      if (body.forget) {
        configured = false;
        updateOptions([]);
      }
      if (success) message.textContent = success;
    } catch (error) {
      message.textContent = error.message;
    } finally {
      busy = false;
      syncControls();
      poll();
    }
  }

  document.querySelector("[data-open-bluetooth-remote]").addEventListener("click", () => {
    dialog.showModal();
    poll();
  });
  dialog.addEventListener("close", stopPolling);
  scan.addEventListener("click", () => update({ scan: true }, "Scanning for Bluetooth devices…"));
  device.addEventListener("change", syncControls);
  dialog.querySelector("#selfie-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (device.value) {
      update({ address: device.value }, "Pairing or reconnecting…",
        "Remote saved. With a session active, press a remote button to test capture.");
    }
  });
  forget.addEventListener("click", () => update({ forget: true }, "Forgetting Bluetooth remote…", "Bluetooth remote forgotten."));
}
