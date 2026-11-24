const $ = (selector) => document.querySelector(selector);
const fields = $("#wifi-fields");
const networks = $("#wifi-networks");
const ssidButton = $("#wifi-ssid");
const security = $("#wifi-security");
const passwordButton = $("#wifi-password");
const connectButton = $("#wifi-connect");
const message = $("#wifi-message");
const setup = $("#wifi-setup");
const editor = $("#wifi-editor");
const editorForm = $("#wifi-editor-form");
const input = $("#wifi-editor-input");
const editorError = $("#wifi-editor-error");

let wifi = null;
let scanResults = [];
let requestPending = false;
let requestVersion = 0;
let ssid = "";
let password = "";
let editing = null;
let caps = false;
let symbols = false;

async function api(path = "", body) {
  const response = await fetch(`/api/local-admin/wifi${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function render() {
  const open = security.value === "open";
  fields.disabled = !wifi?.available || Boolean(wifi.connecting) || requestPending;
  ssidButton.textContent = ssid || "Enter network name";
  passwordButton.textContent = password ? "Change Wi-Fi password" : "Enter Wi-Fi password";
  $("#wifi-password-field").hidden = open;
  connectButton.disabled = !ssid || (!open && !password);

  let status = "Wi-Fi is unavailable.";
  if (wifi?.connecting) {
    status = "Switching networks…";
  } else if (wifi?.hotspot) {
    status = `Hotspot active · ${wifi.hotspot.ssid} · ${wifi.hotspot.ip}`;
  } else if (wifi?.ssid) {
    status = `Connected to ${wifi.ssid} · ${wifi.ip || wifi.hostname}`;
  } else if (wifi?.available) {
    status = "Wi-Fi is disconnected.";
  }
  const statusOutput = $("#wifi-status");
  if (wifi && statusOutput.textContent !== status) statusOutput.textContent = status;
  const resultOutput = $("#wifi-result");
  const result = wifi?.message || "";
  if (resultOutput.textContent !== result) resultOutput.textContent = result;
}

async function refreshStatus() {
  const version = requestVersion;
  try {
    const status = await api();
    if (version === requestVersion && !requestPending) {
      wifi = status;
      render();
    }
  } catch (error) {
    if (version === requestVersion && !requestPending) {
      wifi = null;
      $("#wifi-status").textContent = error.message;
      render();
    }
  } finally {
    setTimeout(refreshStatus, 1500);
  }
}

async function wifiRequest(action) {
  if (requestPending || !wifi?.available || wifi.connecting) return;
  requestPending = true;
  requestVersion += 1;
  render();
  try {
    await action();
  } catch (error) {
    message.textContent = error.message;
  } finally {
    requestPending = false;
    render();
  }
}

$("#wifi-scan").addEventListener("click", () => wifiRequest(async () => {
  message.textContent = "Scanning for Wi-Fi networks…";
  const { networks: results, cached } = await api("/scan", {});
  scanResults = results;
  networks.replaceChildren(new Option("Enter a network manually", ""));
  results.forEach((network, index) => {
    const option = new Option(`${network.ssid} · ${network.security || "Open"} · ${network.signal}%`, index);
    option.disabled = /802\.1X|OWE|WEP/.test(network.security);
    networks.add(option);
  });
  message.textContent = cached
    ? "Live scanning is unavailable. Showing any recent results."
    : results.length ? "" : "No networks found. Enter the name manually or scan again.";
}));

networks.addEventListener("change", () => {
  if (!networks.value) {
    openEditor(ssidButton);
    return;
  }
  const network = scanResults[Number(networks.value)];
  ssid = network.ssid;
  password = "";
  $("#wifi-hidden").checked = false;
  security.value = !network.security ? "open"
    : network.security.includes("WPA3") && !network.security.includes("WPA2") ? "sae" : "wpa-psk";
  render();
  if (security.value !== "open") openEditor(passwordButton);
});

security.addEventListener("change", () => {
  if (security.value === "open") password = "";
  render();
});

connectButton.addEventListener("click", () => wifiRequest(async () => {
  message.textContent = "";
  await api("/connect", { ssid, security: security.value, password, hidden: $("#wifi-hidden").checked });
  password = "";
  wifi = { ...wifi, connecting: true, message: "" };
}));

function openEditor(button) {
  editing = button;
  const secret = button === passwordButton;
  $("#wifi-editor-title").textContent = secret ? "Wi-Fi password" : "Network name";
  input.type = secret ? "password" : "text";
  input.value = secret ? password : ssid;
  editorError.textContent = "";
  caps = false;
  symbols = false;
  renderKeys();
  setup.hidden = true;
  editor.hidden = false;
  input.focus();
}

function closeEditor() {
  input.value = "";
  editor.hidden = true;
  setup.hidden = false;
  editing.focus();
  editing = null;
}

ssidButton.addEventListener("click", () => openEditor(ssidButton));
passwordButton.addEventListener("click", () => openEditor(passwordButton));
$("#wifi-editor-cancel").addEventListener("click", closeEditor);
editor.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeEditor();
});

editorForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (editing === ssidButton) {
    if (new TextEncoder().encode(input.value).length > 32) {
      editorError.textContent = "Enter a network name of 1–32 bytes.";
      input.focus();
      return;
    }
    if (ssid !== input.value) {
      ssid = input.value;
      password = "";
      networks.value = "";
    }
  } else {
    password = input.value;
  }
  render();
  closeEditor();
});

function editText(text) {
  let start = input.selectionStart;
  const end = input.selectionEnd;
  if (text === "" && start === end && start > 0) {
    const previous = Array.from(input.value.slice(0, start)).pop();
    start -= previous.length;
  }
  input.setRangeText(text, start, end, "end");
  editorError.textContent = "";
  input.focus();
}

function keyButton(label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.textContent = label;
  button.addEventListener("pointerdown", (event) => event.preventDefault());
  button.addEventListener("click", action);
  return button;
}

const keyboard = $("#wifi-keyboard");
const keyRows = document.createElement("div");
keyRows.className = "wifi-key-rows";
const keyActions = document.createElement("div");
keyActions.className = "wifi-key-actions";
const capsKey = keyButton("Caps", () => { caps = !caps; renderKeys(); });
const symbolsKey = keyButton("Symbols", () => { symbols = !symbols; renderKeys(); });
keyActions.append(capsKey, symbolsKey, keyButton("Space", () => editText(" ")), keyButton("Backspace", () => editText("")));
keyboard.append(keyRows, keyActions);

function renderKeys() {
  const rows = symbols
    ? ["!\"#$%&'()*+", ",-./:;<=>?@", "[\\]^_`{|}~"]
    : ["1234567890", "qwertyuiop", "asdfghjklå", "zxcvbnmäö"];
  keyRows.replaceChildren(...rows.map((characters) => {
    const row = document.createElement("div");
    row.className = "wifi-key-row";
    for (const character of characters) {
      const key = caps ? character.toUpperCase() : character;
      row.append(keyButton(key, () => editText(key)));
    }
    return row;
  }));
  capsKey.setAttribute("aria-pressed", String(caps));
  symbolsKey.setAttribute("aria-pressed", String(symbols));
}

refreshStatus();
