const $ = (selector) => document.querySelector(selector);

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
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

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const settings = Object.fromEntries(new FormData(event.currentTarget));
  if (!settings.upload_token) delete settings.upload_token;
  try {
    await api("/api/config", settings);
    say("Settings saved to config.json");
    refresh();
  } catch (error) {
    say(error.message);
  }
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
