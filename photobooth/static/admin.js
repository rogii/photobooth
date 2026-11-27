const $ = (selector) => document.querySelector(selector);
const settingsForm = $("#settings-form");
const editedSettings = new Set();
let renderedSessions;
let bootTime = null;

for (const trigger of document.querySelectorAll("[data-admin-panel]")) {
  trigger.addEventListener("click", () => document.getElementById(trigger.dataset.adminPanel).showModal());
}

settingsForm.addEventListener("input", (event) => editedSettings.add(event.target.name));

async function api(path, body) {
  const multipart = body instanceof FormData;
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body && !multipart ? { "Content-Type": "application/json" } : {},
    body: multipart ? body : body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function say(panel, message) {
  const dialog = document.getElementById(panel);
  dialog.querySelector("[data-admin-message]").textContent = message;
  if (!dialog.open) $("#message").textContent = message;
}

async function refresh() {
  try {
    const state = await api("/api/admin/state");
    $("#status").textContent = state.status;
    $("#admin-session").textContent = state.session?.name || "None";
    $("#admin-capture-status").textContent = state.busy
      ? "In progress"
      : state.phase === "result" ? "Showing result" : "Idle";
    $("#admin-flash").textContent = state.flash_available ? "Ready" : "Unavailable";
    $("#admin-uploads").textContent = `${state.queued_uploads} queued`;
    const singleMinimum = state.minimum_single_countdown_seconds;
    settingsForm.elements.countdown_seconds.min = singleMinimum;
    $("#single-countdown-help").textContent = `Minimum: ${singleMinimum} s based on camera timing.`;
    const minimum = state.minimum_sequence_countdown_seconds;
    settingsForm.elements.sequence_countdown_seconds.min = minimum;
    $("#sequence-countdown-help").textContent =
      `Minimum between poses: ${minimum} s based on camera timing. The first photo always gets at least 3 s.`;
    for (const [key, value] of Object.entries(state.config || {})) {
      const input = settingsForm.elements.namedItem(key);
      if (input && !editedSettings.has(key) && document.activeElement !== input) input.value = value;
    }
    $("#save-settings").disabled = false;
    renderSessions(state.sessions || [], state.session, state.locked_session);
    renderWifi(state.wifi);
    renderFooterLogos(state.footer_logos || [], state.active_footer_logo);
    const overlaySession = state.session;
    $("#overlay-status").textContent = overlaySession
      ? `${overlaySession.name}: ${overlaySession.overlay ? `overlay configured (${overlaySession.overlay})` : "no overlay configured"}`
      : "Choose or start a session to configure its overlay.";
    $("#overlay-file").disabled = !overlaySession || state.busy;
    $("#overlay-form button").disabled = !overlaySession || state.busy;
    $("#remove-overlay").disabled = !overlaySession || !overlaySession.overlay || state.busy;
    $("#pause-overlay").textContent = overlaySession?.overlay_paused ? "Resume overlay" : "Pause overlay";
    $("#pause-overlay").disabled = !overlaySession || !overlaySession.overlay || state.busy;
    renderHost(state.host_info || {});
    $("#admin-network-status").textContent = state.wifi?.hotspot
      ? `Hotspot active · ${state.wifi.hotspot.ssid}`
      : state.wifi?.ssid || "";
    const captureDisabled = !state.session || state.busy;
    $("#capture-one").disabled = captureDisabled;
    $("#capture-four").disabled = captureDisabled;
    $("#stop-session").hidden = !state.session;
    $("#stop-session").disabled = state.busy;
  } catch (error) {
    $("#status").textContent = error.message;
  }
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function renderHost(host) {
  bootTime = Number.isFinite(host.uptime_seconds) ? performance.now() - host.uptime_seconds * 1000 : null;
  renderUptime();
  const disk = host.disk || {};
  const percent = Math.max(0, Math.min(100, Number(disk.used_percent || 0)));
  $("#disk-chart").style.setProperty("--usage", `${percent}%`);
  $("#disk-summary").textContent = `${percent}% used · ${formatBytes(disk.used_bytes)} of ${formatBytes(disk.total_bytes)}`;
  $("#disk-detail").textContent = `${formatBytes(disk.free_bytes)} free · ${disk.path || "data volume"}`;
  const online = !!host.internet_connected;
  $("#admin-internet-status").textContent = online ? "Online" : "Offline";
  $("#admin-internet-indicator").classList.toggle("online", online);
  $("#admin-internet-indicator").classList.toggle("offline", !online);
}

function renderUptime() {
  const counter = $("#admin-uptime");
  if (bootTime === null) {
    counter.textContent = "—";
    return;
  }
  const elapsed = Math.floor((performance.now() - bootTime) / 1000);
  const days = Math.floor(elapsed / 86400);
  const hours = Math.floor(elapsed / 3600) % 24;
  const minutes = Math.floor(elapsed / 60) % 60;
  const seconds = elapsed % 60;
  const clock = [hours, minutes, seconds].map((part) => String(part).padStart(2, "0")).join(":");
  const value = days ? `${days}d ${clock}` : clock;
  if (counter.textContent !== value) counter.textContent = value;
}

function renderSessions(sessions, active, locked) {
  const snapshot = JSON.stringify([sessions, active?.id, locked?.id]);
  if (snapshot === renderedSessions) return;
  renderedSessions = snapshot;
  const list = $("#sessions");
  list.replaceChildren();
  if (!sessions.length) { list.textContent = "No saved sessions"; return; }
  sessions.forEach((session) => {
    const row = document.createElement("div"); row.className = "session-admin-row";
    const info = document.createElement("div");
    const name = document.createElement("strong"); name.textContent = session.name;
    const detail = document.createElement("small"); detail.textContent = `${session.created_at ? new Date(session.created_at).toLocaleString() : session.id}${session.id === active?.id ? " · Active" : ""}${session.id === locked?.id ? " · Locked to display" : ""}`;
    info.append(name, detail);
    const actions = document.createElement("div"); actions.className = "session-admin-actions";
    const activate = document.createElement("button"); activate.type = "button"; activate.className = "secondary"; activate.textContent = "Use";
    activate.addEventListener("click", async () => { try { await api("/api/session/select", { id: session.id }); say("sessions-panel", `Active session: ${session.name}`); refresh(); } catch (error) { say("sessions-panel", error.message); } });
    const download = document.createElement("a"); download.href = `/api/admin/session-download/${encodeURIComponent(session.id)}`; download.textContent = "Download ZIP";
    const hide = document.createElement("button"); hide.type = "button"; hide.className = "secondary"; hide.textContent = session.hidden ? "Show at startup" : "Hide at startup";
    hide.addEventListener("click", async () => { try { await api("/api/admin/session-hidden", { session_id: session.id, hidden: !session.hidden }); say("sessions-panel", session.hidden ? "Session restored to startup list" : "Session hidden from startup list"); refresh(); } catch (error) { say("sessions-panel", error.message); } });
    const pin = document.createElement("button"); pin.type = "button"; pin.className = "secondary"; pin.textContent = session.id === locked?.id ? "Unpin display" : "Pin display";
    pin.addEventListener("click", async () => { try { await api("/api/admin/session-lock", { session_id: session.id === locked?.id ? null : session.id }); say("sessions-panel", session.id === locked?.id ? "Session unpinned; kiosk returned to selection" : `Display pinned to ${session.name}`); refresh(); } catch (error) { say("sessions-panel", error.message); } });
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "danger"; remove.textContent = "Delete";
    remove.addEventListener("click", async () => {
      if (!confirm(`Delete “${session.name}” and all of its saved captures? This cannot be undone.`)) return;
      try { await api("/api/admin/session-delete", { session_id: session.id }); say("sessions-panel", `Deleted ${session.name} and its captures`); refresh(); } catch (error) { say("sessions-panel", error.message); }
    });
    actions.append(activate, download, hide, pin, remove); row.append(info, actions); list.append(row);
  });
}

let renderedFooterLogos;

async function updateFooterLogos(path, body, message) {
  const status = $("#footer-logo-message");
  try {
    await api(`/api/admin/footer-logos${path}`, body);
    status.textContent = message;
    await refresh();
    return true;
  } catch (error) {
    status.textContent = error.message;
    return false;
  }
}

function renderFooterLogos(logos, activeId) {
  const snapshot = JSON.stringify([logos, activeId]);
  if (snapshot === renderedFooterLogos) return;
  renderedFooterLogos = snapshot;
  const list = $("#footer-logo-list");
  list.replaceChildren();
  if (!logos.length) {
    list.textContent = "No saved logos";
    return;
  }
  for (const { id, name } of logos) {
    const active = id === activeId;
    const row = document.createElement("div");
    row.className = "session-admin-row";
    const preview = document.createElement("img");
    preview.className = "footer-logo-preview";
    preview.src = `/api/footer-logos/${encodeURIComponent(id)}`;
    preview.alt = "";
    const label = document.createElement("strong");
    label.className = "footer-logo-name";
    label.textContent = active ? `${name} (active)` : name;

    const actions = document.createElement("div");
    actions.className = "session-admin-actions";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "secondary";
    toggle.textContent = active ? "Deactivate" : "Activate";
    toggle.setAttribute("aria-label", `${toggle.textContent} ${name}`);
    toggle.addEventListener("click", () => updateFooterLogos(
      "/active", { id: active ? null : id }, active ? "Logo deactivated" : "Logo activated"
    ));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${name}`);
    remove.addEventListener("click", () => {
      if (confirm(`Remove “${name}” from the footer logo library?`)) {
        updateFooterLogos("/remove", { id }, "Logo removed");
      }
    });
    actions.append(toggle, remove);
    row.append(preview, label, actions);
    list.append(row);
  }
}

$("#footer-logo-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("#footer-logo-file").files[0];
  if (!file) return;
  const button = event.currentTarget.querySelector("button");
  const form = new FormData();
  form.set("logo", file);
  button.disabled = true;
  try {
    if (await updateFooterLogos("", form, "Logo uploaded")) $("#footer-logo-file").value = "";
  } finally {
    button.disabled = false;
  }
});

$("#stop-session").addEventListener("click", async () => {
  try {
    await api("/api/admin/session-stop", {});
    say("sessions-panel", "Active session stopped; kiosk returned to session selection");
    refresh();
  } catch (error) {
    say("sessions-panel", error.message);
  }
});

$("#event-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/admin/event", { name: $("#event-name").value });
    $("#event-name").value = "";
    say("sessions-panel", "Event started");
    refresh();
  } catch (error) {
    say("sessions-panel", error.message);
  }
});

$("#accent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const selector = $("#accent-color");
  const button = event.currentTarget.querySelector("button");
  const message = $("#accent-message");
  button.disabled = true;
  try {
    await api("/api/config", { accent_color: selector.value });
    message.textContent = "Accent color saved";
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const settings = Object.fromEntries(new FormData(event.currentTarget));
  for (const key of ["countdown_seconds", "sequence_countdown_seconds"]) {
    if (!editedSettings.has(key)) delete settings[key];
  }
  if (!settings.upload_token) delete settings.upload_token;
  if (!settings.admin_pin) {
    delete settings.admin_pin;
    delete settings.current_admin_pin;
  }
  try {
    await api("/api/config", { ...settings, save_on_camera: settings.save_on_camera === "true" });
    event.target.elements.admin_pin.value = "";
    event.target.elements.current_admin_pin.value = "";
    for (const [key, value] of Object.entries(settings)) {
      if (settingsForm.elements.namedItem(key)?.value === value) editedSettings.delete(key);
    }
    say("settings-panel", "Settings saved to config.json");
    refresh();
  } catch (error) {
    say("settings-panel", error.message);
  }
});

async function saveOverlay(remove = false) {
  const state = await api("/api/admin/state");
  if (!state.session) throw new Error("Choose or start a session first");
  const form = new FormData();
  if (remove) form.set("remove", "1");
  else {
    const file = $("#overlay-file").files[0];
    if (!file) throw new Error("Choose a PNG or WebP overlay image");
    form.set("overlay", file);
  }
  const response = await fetch(`/api/admin/session-overlay/${encodeURIComponent(state.session.id)}`, { method: "POST", body: form, cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  $("#overlay-file").value = "";
  say("overlay-panel", remove ? "Session overlay removed" : "Session overlay saved");
  refresh();
}

$("#overlay-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await saveOverlay(); } catch (error) { say("overlay-panel", error.message); }
});
$("#remove-overlay").addEventListener("click", async () => {
  try { await saveOverlay(true); } catch (error) { say("overlay-panel", error.message); }
});
$("#pause-overlay").addEventListener("click", async () => {
  try {
    const state = await api("/api/admin/state");
    if (!state.session?.overlay) throw new Error("Choose a session with an overlay first");
    const paused = !state.session.overlay_paused;
    await api(`/api/admin/session-overlay/${encodeURIComponent(state.session.id)}/pause`, { paused });
    say("overlay-panel", paused ? "Overlay paused for future captures" : "Overlay resumed for future captures");
    refresh();
  } catch (error) { say("overlay-panel", error.message); }
});

async function capture(count) {
  $("#capture-one").disabled = true;
  $("#capture-four").disabled = true;
  try {
    await api("/api/admin/capture", { count });
    say("capture-panel", count === 1 ? "Single photo capture started" : "Four photo capture started");
    refresh();
  } catch (error) {
    say("capture-panel", error.message);
    refresh();
  }
}

$("#capture-one").addEventListener("click", () => capture(1));
$("#capture-four").addEventListener("click", () => capture(4));
$("#restart").addEventListener("click", async () => {
  if (!confirm("Restart the photobooth service?")) return;
  try {
    await api("/api/restart", {});
    say("system-panel", "Photobooth is restarting…");
  } catch (error) {
    say("system-panel", error.message);
  }
});

const shutdownButton = $("#shutdown");
const shutdownDialog = $("#shutdown-dialog");
shutdownButton.addEventListener("click", () => {
  shutdownDialog.returnValue = "";
  shutdownDialog.showModal();
});
shutdownDialog.addEventListener("close", async () => {
  if (shutdownDialog.returnValue !== "shutdown") return;
  const status = $("#shutdown-status");
  shutdownButton.disabled = true;
  status.hidden = false;
  status.textContent = "Requesting shutdown…";
  try {
    await api("/api/admin/shutdown", {});
    status.textContent = "Raspberry Pi is shutting down…";
  } catch (error) {
    status.textContent = error.message;
    shutdownButton.disabled = false;
  }
});

setupBluetoothRemote(api);

setInterval(refresh, 2000);
setInterval(renderUptime, 1000);

const wifiFields = $("#wifi-fields");
const wifiForm = $("#wifi-form");
const wifiNetworks = $("#wifi-networks");
const wifiMessage = $("#wifi-message");
let wifiScanResults = [];
let wifiRequest = false;

function renderWifi(wifi) {
  wifiFields.disabled = !wifi.available || wifi.connecting || wifiRequest;
  let status = "Wi-Fi is unavailable.";
  if (wifi.hotspot) {
    status = `Hotspot active · ${wifi.hotspot.ssid} · ${wifi.hotspot.ip}:8081`;
  } else if (wifi.ssid) {
    status = `Connected to ${wifi.ssid} · ${wifi.ip || wifi.hostname}:8081`;
  } else if (wifi.available) {
    status = "Wi-Fi is disconnected.";
  }
  const current = wifi.connecting
    ? `Switching networks. Reopen this page at ${wifi.hostname}:8081 after joining the new network.`
    : status;
  if ($("#wifi-current").textContent !== current) $("#wifi-current").textContent = current;
  if ($("#wifi-result").textContent !== wifi.message) $("#wifi-result").textContent = wifi.message;
}

function updateWifiPassword() {
  const open = wifiForm.elements.security.value === "open";
  $("#wifi-password").hidden = open;
  wifiForm.elements.password.disabled = open;
  wifiForm.elements.password.required = !open;
}

$("#wifi-scan").addEventListener("click", async () => {
  wifiRequest = true;
  wifiFields.disabled = true;
  wifiMessage.textContent = "Scanning for Wi-Fi networks…";
  try {
    const { networks, cached } = await api("/api/admin/wifi/scan", {});
    wifiScanResults = networks;
    wifiNetworks.replaceChildren(new Option("Enter a network manually", ""));
    networks.forEach((network, index) => {
      const label = `${network.ssid} · ${network.security || "Open"} · ${network.signal}%`;
      const option = new Option(label, index);
      option.disabled = /802\.1X|OWE|WEP/.test(network.security);
      wifiNetworks.add(option);
    });
    wifiMessage.textContent = cached
      ? "Live scanning is unavailable. Showing any recent results. You can also enter a network name."
      : networks.length ? "Select a network or enter its name manually." : "No networks found. Enter the name manually or scan again.";
  } catch (error) {
    wifiMessage.textContent = error.message;
  } finally {
    wifiRequest = false;
    wifiFields.disabled = false;
  }
});

wifiNetworks.addEventListener("change", () => {
  if (!wifiNetworks.value) return;
  const network = wifiScanResults[Number(wifiNetworks.value)];
  wifiForm.elements.ssid.value = network.ssid;
  wifiForm.elements.hidden.checked = false;
  wifiForm.elements.password.value = "";
  wifiForm.elements.security.value = !network.security ? "open"
    : network.security.includes("WPA3") && !network.security.includes("WPA2") ? "sae" : "wpa-psk";
  updateWifiPassword();
  (wifiForm.elements.password.disabled ? wifiForm.elements.pin : wifiForm.elements.password).focus();
});

wifiForm.elements.security.addEventListener("change", updateWifiPassword);
wifiForm.elements.ssid.addEventListener("input", () => { wifiNetworks.value = ""; });

wifiForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(wifiForm));
  values.hidden = wifiForm.elements.hidden.checked;
  wifiRequest = true;
  wifiFields.disabled = true;
  wifiMessage.textContent = "";
  try {
    await api("/api/admin/wifi/connect", values);
    wifiForm.elements.password.value = "";
    wifiForm.elements.pin.value = "";
    wifiMessage.textContent = "Switch requested. If the page disconnects, join the new network and reopen the admin page. If the switch fails, reconnect to the previous network.";
  } catch (error) {
    wifiMessage.textContent = error.message;
    wifiFields.disabled = false;
  } finally {
    wifiRequest = false;
  }
});

refresh();
