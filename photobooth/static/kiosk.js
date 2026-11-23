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
  $("#event-footer").classList.toggle("hidden", !current.session);
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

  const activePhases = ["countdown", "capturing", "downloading", "result"];
  $("#empty").classList.toggle("hidden", !!current.session);
  gallery.classList.toggle("hidden", !current.session || current.phase !== "idle");
  overlay.classList.toggle("hidden", !activePhases.includes(current.phase));
  $("#photo-position").classList.toggle("hidden", current.phase === "result" || current.photo_total < 2);
  $("#photo-position").textContent = current.photo_total > 1
    ? `PHOTO ${current.photo_number} / ${current.photo_total}`
    : "";
  $("#countdown").classList.toggle("hidden", current.phase !== "countdown");
  $("#countdown").textContent = current.phase === "countdown" ? current.countdown : "";
  $("#capture-status").classList.toggle("hidden", current.phase !== "capturing");
  $("#capture-status").textContent = current.phase === "capturing"
    ? (current.photo_total > 1 ? `CAPTURING ${current.photo_number} / ${current.photo_total}` : "CAPTURING PHOTO")
    : "";
  $("#progress").classList.toggle("hidden", current.phase !== "downloading");
  $("#result").classList.toggle("hidden", current.phase !== "result");
  if (current.phase === "downloading") {
    const progress = current.download_progress || 0;
    $("#bar-fill").style.width = `${progress}%`;
    $("#percent").textContent = `${progress}%`;
    $("#progress-title").textContent = current.photo_total > 1
      ? `Downloading photo ${current.photo_number} / ${current.photo_total}`
      : "Capture download progress";
  }
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
    $("#session-input").focus();
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

function renderKeyboard() {
  const keyboard = $("#onscreen-keyboard");
  ["1234567890", "qwertyuiop", "asdfghjklå", "zxcvbnmäö.-"].forEach((chars) => {
    const row = document.createElement("div"); row.className = "keyboard-row";
    [...chars].forEach((char) => {
      const key = document.createElement("button"); key.type = "button"; key.className = "key-button"; key.textContent = char;
      key.addEventListener("click", () => { $("#session-input").value += char; syncPickerName(); }); row.append(key);
    }); keyboard.append(row);
  });
  const row = document.createElement("div"); row.className = "keyboard-row";
  [["⌫", () => { $("#session-input").value = $("#session-input").value.slice(0, -1); }], ["Space", () => { $("#session-input").value += " "; }], ["Clear", () => { $("#session-input").value = ""; }]].forEach(([label, action]) => {
    const key = document.createElement("button"); key.type = "button"; key.className = "key-button wide"; key.textContent = label;
    key.addEventListener("click", () => { action(); syncPickerName(); }); row.append(key);
  }); keyboard.append(row);
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
  if (!connected) return;
  if (event.key.toLowerCase() === (state?.keys?.single || "a").toLowerCase()) capture(1);
  if (event.key.toLowerCase() === (state?.keys?.sequence || "b").toLowerCase()) capture(4);
});

refresh();
renderKeyboard();
$("#session-input").addEventListener("input", syncPickerName);
$("#create-session").addEventListener("click", createSession);
setInterval(refresh, 250);
window.addEventListener("resize", () => {
  galleryLayout = "";
  renderGallery();
  updateGallery();
});
