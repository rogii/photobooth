const $ = (selector) => document.querySelector(selector);
let state = null;
let connected = false;
let serverInstanceId = null;
let lastVersion = "";
let galleryVersion = null;
let galleryRows = null;
let galleryPhotos = [];
let galleryRequest = false;
let galleryLayout = "";
let pickerOpen = false;
let capsLock = false;
let adminHoldTimer = null;

function showAdminPin() {
  adminHoldTimer = null;
  $("#admin-access").classList.remove("holding");
  $("#admin-pin-dialog").classList.remove("hidden");
  $("#admin-pin-input").value = "";
  $("#admin-pin-error").textContent = "";
  $("#admin-pin-input").focus();
}

function openAdminPanel() {
  const adminUrl = new URL(window.location.href);
  adminUrl.port = "8081";
  adminUrl.pathname = "/admin";
  adminUrl.search = "";
  adminUrl.hash = "";
  window.location.assign(adminUrl.toString());
}

function startAdminHold() {
  if (adminHoldTimer !== null) return;
  $("#admin-access").classList.add("holding");
  adminHoldTimer = window.setTimeout(showAdminPin, 1200);
}

function cancelAdminHold() {
  if (adminHoldTimer !== null) window.clearTimeout(adminHoldTimer);
  adminHoldTimer = null;
  $("#admin-access").classList.remove("holding");
}

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

function render(current) {
  state = current;
  $("#event").textContent = current.session?.name || "";
  $("#event-footer").classList.toggle("hidden", !current.session || current.phase === "result");
  $("#capture-count").textContent = Number(current.capture_count || 0).toLocaleString();
  const queuedUploads = Number(current.queued_uploads || 0);
  $("#upload-indicator").classList.toggle("pending", queuedUploads > 0);
  $("#upload-status").textContent = queuedUploads > 0 ? "UPLOADS PENDING" : "ALL UPLOADED";
  $("#upload-count").textContent = queuedUploads > 0 ? `${queuedUploads} queued` : "";
  const online = !!current.host_info?.internet_connected;
  $("#internet-status").textContent = online ? "ONLINE" : "OFFLINE";
  $("#internet-indicator").classList.toggle("offline", !online);
  const gallery = $("#gallery");
  const overlay = $("#overlay");
  renderGallery();

  const activePhases = ["countdown", "capturing", "result"];
  $("#empty").classList.toggle("hidden", !!current.session);
  gallery.classList.toggle("hidden", !current.session || current.phase !== "idle");
  overlay.classList.toggle("hidden", !activePhases.includes(current.phase));
  $("#photo-position").classList.toggle("hidden", current.phase === "result" || current.photo_total < 2);
  $("#photo-position").textContent = current.photo_total > 1
    ? `PHOTO ${current.photo_number} / ${current.photo_total}`
    : "";
  const showingCapture = current.phase === "capturing";
  $("#countdown").classList.toggle("hidden", !(current.phase === "countdown" || showingCapture) || !current.countdown);
  $("#countdown").textContent = current.phase === "countdown" || showingCapture ? current.countdown : "";
  $("#capture-detail").classList.toggle("hidden", !showingCapture);
  $("#capture-detail").textContent = current.photo_total > 1
    ? `Photo ${current.photo_number} of ${current.photo_total} is being captured and downloaded from the camera.`
    : "Your photo is being captured and downloaded from the camera.";
  $("#result").classList.toggle("hidden", current.phase !== "result");
  if (current.phase === "result" && current.recent_photo_version !== lastVersion) {
    lastVersion = current.recent_photo_version;
    $("#result").src = `/api/recent-photo?v=${encodeURIComponent(lastVersion)}`;
  }
  $("#error").textContent = current.status.startsWith("Capture failed") ? current.status : "";
  if (!current.session && !current.locked_session) showSessionPicker(current.sessions || []);
  if (current.session) closeSessionPicker();
}

function showSessionPicker(sessions) {
  const dialog = $("#session-dialog");
  if (!pickerOpen) {
    pickerOpen = true;
    dialog.classList.remove("hidden");
    $("#picker-options").classList.remove("hidden");
    $("#new-session-form").classList.add("hidden");
  }
  const list = $("#session-list");
  const signature = sessions.map((item) => `${item.id}:${item.name}`).join("|");
  if (list.dataset.signature === signature) return;
  list.dataset.signature = signature;
  list.replaceChildren();
  if (!sessions.length) {
    const empty = document.createElement("p");
    empty.className = "session-empty";
    empty.textContent = "No saved sessions yet.";
    list.append(empty);
  }
  sessions.forEach((session) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-choice";
    button.innerHTML = `<strong></strong><span></span>`;
    button.querySelector("strong").textContent = session.name;
    button.querySelector("span").textContent = session.created_at ? new Date(session.created_at).toLocaleString() : "Saved session";
    button.addEventListener("click", async () => {
      try {
        await api("/api/session/select", { id: session.id });
        closeSessionPicker();
        await refresh();
      } catch (error) { $("#picker-error").textContent = error.message; }
    });
    list.append(button);
  });
}

function closeSessionPicker() {
  pickerOpen = false;
  $("#session-dialog").classList.add("hidden");
}

function openNewSessionForm() {
  $("#picker-options").classList.add("hidden");
  $("#new-session-form").classList.remove("hidden");
  $("#picker-error").textContent = "";
  $("#session-input").focus();
}

function returnToSessionOptions() {
  $("#new-session-form").classList.add("hidden");
  $("#picker-options").classList.remove("hidden");
  $("#picker-error").textContent = "";
}

function renderKeyboard() {
  const keyboard = $("#onscreen-keyboard");
  keyboard.replaceChildren();
  ["1234567890", "qwertyuiop", "asdfghjklå", "zxcvbnmäö.-"].forEach((chars) => {
    const row = document.createElement("div"); row.className = "keyboard-row";
    [...chars].forEach((lowerChar) => {
      const char = capsLock ? lowerChar.toLocaleUpperCase("sv-SE") : lowerChar;
      const key = document.createElement("button"); key.type = "button"; key.className = "key-button"; key.textContent = char;
      key.addEventListener("click", () => insertPickerText(char)); row.append(key);
    }); keyboard.append(row);
  });
  const row = document.createElement("div"); row.className = "keyboard-row";
  const caps = document.createElement("button");
  caps.type = "button"; caps.className = `key-button wide${capsLock ? " selected" : ""}`; caps.textContent = "⇧ Caps"; caps.setAttribute("aria-pressed", String(capsLock));
  caps.addEventListener("click", () => { capsLock = !capsLock; renderKeyboard(); });
  row.append(caps);
  [["⌫", "wide", () => { const input = $("#session-input"); input.value = input.value.slice(0, -1); syncPickerName(); }], ["Space", "space", () => insertPickerText(" ")], ["Clear", "wide", () => { $("#session-input").value = ""; syncPickerName(); }]].forEach(([label, size, action]) => {
    const key = document.createElement("button"); key.type = "button"; key.className = `key-button ${size}`; key.textContent = label;
    key.addEventListener("click", () => { action(); syncPickerName(); }); row.append(key);
  }); keyboard.append(row);
}

function insertPickerText(text) {
  const input = $("#session-input");
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? input.value.length;
  input.setRangeText(text, start, end, "end");
  syncPickerName();
  input.focus();
}

function syncPickerName() { $("#create-session").disabled = !$("#session-input").value.trim(); }

async function createSession() {
  try {
    await api("/api/session", { name: $("#session-input").value });
    closeSessionPicker(); await refresh();
  } catch (error) { $("#picker-error").textContent = error.message; }
}

function setConnectionStatus(isConnected) {
  connected = isConnected;
  $("#connection-status").classList.toggle("hidden", isConnected);
}


function renderGallery() {
  if (!state) return;
  const gallery = $("#gallery");
  const columns = Math.max(1, Number(state.gallery_columns) || 3);
  const layout = `${columns}:${galleryPhotos.map((photo) => photo.name).join("|")}`;
  if (layout === galleryLayout) return;
  galleryLayout = layout;
  gallery.replaceChildren();
  gallery.style.gridTemplateColumns = `repeat(${columns},minmax(0,1fr))`;
  gallery.style.gridTemplateRows = "none";
  gallery.style.gridAutoRows = `${window.innerWidth / columns * 9 / 16}px`;
  galleryPhotos.forEach((photo, index) => {
    const image = new Image();
    image.src = `${photo.url}?v=${encodeURIComponent(photo.name)}`;
    image.alt = `Photo ${index + 1}`;
    gallery.append(image);
  });
}

async function updateGallery() {
  const version = state?.gallery_version;
  const columns = Math.max(1, Number(state?.gallery_columns) || 3);
  const tileHeight = window.innerWidth / columns * 9 / 16;
  const rows = Math.max(1, Math.min(12, Math.ceil(window.innerHeight / tileHeight)));
  if (!version || (version === galleryVersion && rows === galleryRows) || galleryRequest) return;
  galleryRequest = true;
  try {
    const data = await api(`/api/gallery?rows=${rows}`);
    if (state?.gallery_version === version) {
      galleryPhotos = data.photos || [];
      galleryVersion = version;
      galleryRows = rows;
      renderGallery();
    }
  } catch (error) {
    $("#error").textContent = error.message;
  } finally {
    galleryRequest = false;
    const currentRows = Math.max(1, Math.min(12, Math.ceil(window.innerHeight / (window.innerWidth / Math.max(1, Number(state?.gallery_columns) || 3) * 9 / 16))));
    if (state?.gallery_version !== galleryVersion || currentRows !== galleryRows) updateGallery();
  }
}

async function refresh() {
  try {
    const current = await api("/api/state");
    if (serverInstanceId !== null && current.server_instance_id !== serverInstanceId) {
      window.location.reload();
      return;
    }
    serverInstanceId = current.server_instance_id ?? serverInstanceId;
    setConnectionStatus(true);
    render(current);
    updateGallery();
  } catch (error) {
    setConnectionStatus(false);
    $("#error").textContent = error.message;
  }
}

async function capture(count) {
  if (!connected || !state?.session || state.busy) return;
  try {
    await api("/api/capture", { count });
    await refresh();
  } catch (error) {
    if (error instanceof TypeError) setConnectionStatus(false);
    $("#error").textContent = error.message;
  }
}

document.addEventListener("keydown", (event) => {
  if (!connected || !$("#admin-pin-dialog").classList.contains("hidden")) return;
  if (event.key.toLowerCase() === (state?.keys?.single || "a").toLowerCase()) capture(1);
  if (event.key.toLowerCase() === (state?.keys?.sequence || "b").toLowerCase()) capture(4);
});

refresh();
renderKeyboard();
$("#session-input").addEventListener("input", syncPickerName);
$("#start-new-session").addEventListener("click", openNewSessionForm);
$("#back-to-sessions").addEventListener("click", returnToSessionOptions);
$("#create-session").addEventListener("click", createSession);
setInterval(refresh, 250);
window.addEventListener("resize", () => {
  galleryLayout = "";
  renderGallery();
  updateGallery();
});

const adminAccess = $("#admin-access");
adminAccess.addEventListener("pointerdown", (event) => {
  if (!event.isPrimary || (event.pointerType === "mouse" && event.button !== 0)) return;
  event.preventDefault();
  startAdminHold();
});
["pointerup", "pointercancel", "pointerleave"].forEach((name) => adminAccess.addEventListener(name, cancelAdminHold));
adminAccess.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    startAdminHold();
  }
});
["keyup", "blur"].forEach((name) => adminAccess.addEventListener(name, cancelAdminHold));

$("#admin-pin-back").addEventListener("click", () => $("#admin-pin-dialog").classList.add("hidden"));
$(".admin-pin-pad").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const input = $("#admin-pin-input");
  if (button.dataset.pinDigit !== undefined) input.value += button.dataset.pinDigit;
  if (button.dataset.pinAction === "clear") input.value = "";
  if (button.dataset.pinAction === "delete") input.value = input.value.slice(0, -1);
});
$("#admin-pin-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = $("#admin-pin-form button[type='submit']");
  submit.disabled = true;
  $("#admin-pin-error").textContent = "";
  try {
    await api("/api/admin/unlock", { pin: $("#admin-pin-input").value });
    openAdminPanel();
  } catch (error) {
    $("#admin-pin-error").textContent = error.message === "Invalid PIN" ? "Incorrect PIN. Try again." : error.message;
    $("#admin-pin-input").select();
  } finally {
    submit.disabled = false;
  }
});
