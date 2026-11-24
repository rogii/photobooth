const $ = (selector) => document.querySelector(selector);

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

function say(message) {
  $("#message").textContent = message;
}

async function refresh() {
  try {
    const state = await api("/api/admin/state");
    $("#status").textContent = `State: ${state.status}\nEvent: ${state.session?.name || "None"}\nCapture: ${state.busy ? "In progress" : "Idle"} · ${state.phase}\nFlash: ${state.flash_available ? "Ready" : "Unavailable"}\nQueued uploads: ${state.queued_uploads}`;
    for (const [key, value] of Object.entries(state.config || {})) {
      const input = $(`[name="${key}"]`);
      if (input && document.activeElement !== input && key !== "upload_token") input.value = value;
    }
    renderSessions(state.sessions || [], state.session, state.locked_session);
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
  const disk = host.disk || {};
  const percent = Math.max(0, Math.min(100, Number(disk.used_percent || 0)));
  $("#disk-chart").style.setProperty("--usage", `${percent}%`);
  $("#disk-chart").setAttribute("aria-label", `Disk ${percent}% used`);
  $("#disk-summary").textContent = `${formatBytes(disk.used_bytes)} used of ${formatBytes(disk.total_bytes)} (${percent}%)`;
  $("#disk-detail").textContent = `${formatBytes(disk.free_bytes)} free · ${disk.path || "data volume"}`;
  const online = !!host.internet_connected;
  $("#admin-internet-status").textContent = online ? "Internet connection available" : "No internet connection";
  $("#admin-internet-indicator").classList.toggle("offline", !online);
}

function renderSessions(sessions, active, locked) {
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
    activate.addEventListener("click", async () => { try { await api("/api/session/select", { id: session.id }); say(`Active session: ${session.name}`); refresh(); } catch (error) { say(error.message); } });
    const download = document.createElement("a"); download.href = `/api/admin/session-download/${encodeURIComponent(session.id)}`; download.textContent = "Download ZIP";
    const hide = document.createElement("button"); hide.type = "button"; hide.className = "secondary"; hide.textContent = session.hidden ? "Show at startup" : "Hide at startup";
    hide.addEventListener("click", async () => { try { await api("/api/admin/session-hidden", { session_id: session.id, hidden: !session.hidden }); say(session.hidden ? "Session restored to startup list" : "Session hidden from startup list"); refresh(); } catch (error) { say(error.message); } });
    const pin = document.createElement("button"); pin.type = "button"; pin.className = "secondary"; pin.textContent = session.id === locked?.id ? "Unpin display" : "Pin display";
    pin.addEventListener("click", async () => { try { await api("/api/admin/session-lock", { session_id: session.id === locked?.id ? null : session.id }); say(session.id === locked?.id ? "Session unpinned; kiosk returned to selection" : `Display pinned to ${session.name}`); refresh(); } catch (error) { say(error.message); } });
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "danger"; remove.textContent = "Delete";
    remove.addEventListener("click", async () => {
      if (!confirm(`Delete “${session.name}” and all of its saved captures? This cannot be undone.`)) return;
      try { await api("/api/admin/session-delete", { session_id: session.id }); say(`Deleted ${session.name} and its captures`); refresh(); } catch (error) { say(error.message); }
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
    say("Active session stopped; kiosk returned to session selection");
    refresh();
  } catch (error) {
    say(error.message);
  }
});

$("#event-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/admin/event", { name: $("#event-name").value });
    $("#event-name").value = "";
    say("Event started");
    refresh();
  } catch (error) {
    say(error.message);
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

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const settings = Object.fromEntries(new FormData(event.currentTarget));
  if (!settings.upload_token) delete settings.upload_token;
  if (!settings.admin_pin) delete settings.admin_pin;
  try {
    await api("/api/config", settings);
    event.target.elements.admin_pin.value = "";
    say("Settings saved to config.json");
    refresh();
  } catch (error) {
    say(error.message);
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
  say(remove ? "Session overlay removed" : "Session overlay saved");
  refresh();
}

$("#overlay-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await saveOverlay(); } catch (error) { say(error.message); }
});
$("#remove-overlay").addEventListener("click", async () => {
  try { await saveOverlay(true); } catch (error) { say(error.message); }
});
$("#pause-overlay").addEventListener("click", async () => {
  try {
    const state = await api("/api/admin/state");
    if (!state.session?.overlay) throw new Error("Choose a session with an overlay first");
    const paused = !state.session.overlay_paused;
    await api(`/api/admin/session-overlay/${encodeURIComponent(state.session.id)}/pause`, { paused });
    say(paused ? "Overlay paused for future captures" : "Overlay resumed for future captures");
    refresh();
  } catch (error) { say(error.message); }
});

async function capture(count) {
  $("#capture-one").disabled = true;
  $("#capture-four").disabled = true;
  try {
    await api("/api/admin/capture", { count });
    say(count === 1 ? "Single photo capture started" : "Four photo capture started");
    refresh();
  } catch (error) {
    say(error.message);
    refresh();
  }
}

$("#capture-one").addEventListener("click", () => capture(1));
$("#capture-four").addEventListener("click", () => capture(4));
$("#restart").addEventListener("click", async () => {
  if (!confirm("Restart the photobooth service?")) return;
  try {
    await api("/api/restart", {});
    say("Photobooth is restarting…");
  } catch (error) {
    say(error.message);
  }
});

refresh();
setInterval(refresh, 2000);
