const $ = (selector) => document.querySelector(selector);
if (new URLSearchParams(location.search).get("hide_cursor") === "1") {
  document.documentElement.classList.add("hide-cursor");
}

let state = null;
let connected = false;
let refreshPending = false;
let serverInstanceId = null;
let photoWallVersion = null;
let gallerySession = null;
let photoWallPhotos = [];
let photoWallRequest = false;
let galleryLayout = "";
const maxHistoryPhotos = 11;
let pickerOpen = false;
let capsLock = false;
let adminHoldTimer = null;
let adminHoldTarget = null;

function showAdminPin() {
  const trigger = adminHoldTarget;
  cancelAdminHold();
  if (trigger.closest(".hidden")) return;
  adminPinDialog.classList.remove("hidden");
  adminPinKeypad.reset(state?.admin_pin_length ?? 4);
}

function openAdminPanel() {
  const adminUrl = new URL(window.location.href);
  adminUrl.port = "8081";
  adminUrl.pathname = "/local-admin";
  adminUrl.search = "";
  adminUrl.hash = "";
  window.location.assign(adminUrl.toString());
}

function startAdminHold(trigger) {
  if (adminHoldTimer !== null || !adminPinDialog.classList.contains("hidden")) return;
  adminHoldTarget = trigger;
  trigger.classList.add("holding");
  adminHoldTimer = window.setTimeout(showAdminPin, 1200);
}

function cancelAdminHold() {
  if (adminHoldTimer !== null) window.clearTimeout(adminHoldTimer);
  adminHoldTimer = null;
  adminHoldTarget?.classList.remove("holding");
  adminHoldTarget = null;
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
  const cameraFailed = !current.demo && !current.camera_available;
  $("#camera-error").classList.toggle("hidden", !cameraFailed);
  $("#camera-error-detail").textContent = current.camera_error || "The camera is not responding.";
  $("#event").textContent = current.session?.name || "";
  const logo = $("#footer-logo");
  if (current.active_footer_logo) {
    const url = `/api/footer-logos/${encodeURIComponent(current.active_footer_logo)}`;
    if (logo.getAttribute("src") !== url) logo.src = url;
  } else {
    logo.removeAttribute("src");
  }
  logo.classList.toggle("hidden", !current.active_footer_logo);
  $("#event-footer").classList.toggle("hidden", !current.session);
  $("#capture-count").textContent = Number(current.capture_count || 0).toLocaleString();
  const queuedUploads = Number(current.queued_uploads || 0);
  const galleryUploadConfigured = !!current.gallery_upload_configured;
  $("#upload-indicator").classList.toggle("pending", queuedUploads > 0);
  const uploadOffLabel = current.capture_layout === "event-sidebar" ? "UPLOAD" : "GALLERY UPLOAD OFF";
  $("#upload-status").textContent = !galleryUploadConfigured
    ? uploadOffLabel
    : queuedUploads > 0 ? "GALLERY UPLOADS PENDING" : "GALLERY UP TO DATE";
  $("#upload-count").textContent = queuedUploads > 0 ? `${queuedUploads} queued` : "";
  const selfieStatus = current.selfie_button_status;
  const showSelfieWakePrompt = current.session && current.phase === "idle" &&
    !cameraFailed && current.selfie_button_configured && selfieStatus !== "connected";
  $("#selfie-wake-prompt").classList.toggle("hidden", !showSelfieWakePrompt);
  $("#selfie-stat").classList.toggle("hidden", !selfieStatus);
  $("#selfie-stat").toggleAttribute("data-connected", selfieStatus === "connected");
  $("#selfie-divider").classList.toggle("hidden", !selfieStatus);
  const selfieLabel = selfieStatus ? selfieStatus.toUpperCase() : "";
  if ($("#selfie-status").textContent !== selfieLabel) $("#selfie-status").textContent = selfieLabel;
  const online = !!current.host_info?.internet_connected;
  const hotspot = current.host_info?.hotspot;
  $("#picker-hotspot").classList.toggle("hidden", !hotspot);
  $("#picker-hotspot").textContent = hotspot ? `Hotspot active · ${hotspot.ssid} · ${hotspot.ip}:8081` : "";
  $("#internet-status").textContent = hotspot ? "HOTSPOT ACTIVE" : online ? "ONLINE" : "OFFLINE";
  const networkLabel = current.capture_layout === "event-sidebar" ? "" : "INTERNET";
  $("#network-detail").textContent = hotspot ? hotspot.ssid : networkLabel;
  $("#internet-indicator").classList.toggle("offline", !hotspot && !online);

  if (gallerySession !== current.session?.id) {
    gallerySession = current.session?.id;
    photoWallPhotos = [];
    photoWallVersion = null;
    galleryLayout = "";
  }
  const capturing = current.phase === "countdown" || current.phase === "capturing";
  $("#empty").classList.toggle("hidden", !!current.session);
  $("#photo-wall").classList.toggle("hidden", !current.session);
  renderPhotoWall();
  const lead = $(".lead-photo");
  const loadingResult = current.phase === "result" &&
    (photoWallVersion !== current.photo_wall_version || (lead && !lead.complete));
  $("#overlay").classList.toggle("hidden", !capturing && !loadingResult);
  $(".capture-trigger").classList.toggle("capture-trigger-busy", current.busy || capturing || loadingResult);
  const downloading = current.status === "Downloading four photos";
  const detail = $("#capture-detail");
  const preparingCollage = current.status === "Preparing collage" ||
    (loadingResult && detail.classList.contains("sequence-finish"));
  const finishingSequence = downloading || preparingCollage;
  $("#photo-position").classList.toggle("hidden",
    finishingSequence || current.phase === "result" || current.photo_total < 2 || current.photo_number < 1);
  $("#photo-position").textContent = current.photo_total > 1 && current.photo_number > 0
    ? `PHOTO ${current.photo_number} / ${current.photo_total}`
    : "";
  const showingCapture = current.phase === "capturing";
  const preparing = capturing && current.prepare_elapsed != null;
  const showProgress = preparing || loadingResult;
  const progress = $("#capture-progress");
  progress.classList.toggle("hidden", !showProgress);
  if (preparing && current.photo_number === current.photo_total && current.prepare_estimate > 0) {
    progress.value = Math.min(0.95, current.prepare_elapsed / current.prepare_estimate);
  } else if (!loadingResult) {
    progress.removeAttribute("value");
  }
  $("#countdown").classList.toggle("hidden", !capturing || !current.countdown);
  $("#countdown").textContent = capturing ? current.countdown : "";
  detail.classList.toggle("hidden", !showProgress && !showingCapture);
  detail.classList.toggle("sequence-finish", finishingSequence);
  detail.textContent = downloading ? "Downloading four photos…"
    : preparingCollage ? "Preparing collage…"
    : current.photo_total === 4 ? `Taking photo ${current.photo_number} of 4…`
    : "Preparing your photo…";
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


function contactSheetRows(wall) {
  const latest = photoWallPhotos[0];
  const image = latest && wall.querySelector(`img[data-url="${CSS.escape(latest.url)}"]`);
  if (!image?.naturalWidth || !wall.clientHeight) return 2;

  const style = getComputedStyle(wall);
  const gap = parseFloat(style.gap);
  const width = wall.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  const height = wall.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
  // Each history column gets one quarter of the grid width after both column gaps.
  const thumbnailHeight = (width - 2 * gap) / 4 * image.naturalHeight / image.naturalWidth;
  return Math.max(1, Math.min(Math.floor(maxHistoryPhotos / 2), Math.floor(
    (height + gap) / (thumbnailHeight + gap)
  )));
}

function renderPhotoWall() {
  const wall = $("#photo-wall");
  const name = state.capture_layout || "side-gallery";
  const screen = $("#screen");
  if (screen.dataset.layout !== name) screen.dataset.layout = name;
  if (screen.dataset.font !== state.event_font) screen.dataset.font = state.event_font || "system";
  const capacities = { filmstrip: 4, spotlight: 2, "print-table": 2 };
  let slots = capacities[name] || Number(state.photo_wall_columns) || 3;
  if (name === "event-sidebar") {
    const gap = parseFloat(getComputedStyle(wall).columnGap);
    // The history row has one quarter of the grid height after the gap.
    const thumbnailWidth = (wall.clientHeight - gap) / 4 * 1.5;
    slots = Math.max(1, Math.min(maxHistoryPhotos, Math.round(
      (wall.clientWidth + gap) / (thumbnailWidth + gap)
    )));
  }
  if (name === "contact-sheet") slots = 2 * contactSheetRows(wall);
  const capturing = state.phase === "countdown" || state.phase === "capturing";
  // Keep the old lead in the rail until the saved result arrives.
  const awaitingResult = state.phase === "result" && photoWallVersion !== state.photo_wall_version;
  const reserveLead = capturing || awaitingResult;
  const photos = photoWallPhotos.slice(0, slots + (reserveLead ? 0 : 1));
  const layout = JSON.stringify([name, slots, reserveLead, photos.map(photo => photo.url)]);
  $("#first-capture").classList.toggle("hidden", reserveLead || photos.length > 0 || !photoWallVersion);
  if (layout === galleryLayout) return;
  galleryLayout = layout;

  const existing = new Map(Array.from(wall.querySelectorAll("img"), img => [img.dataset.url, img]));
  const oldLead = wall.querySelector(".lead-photo");
  const before = oldLead?.getBoundingClientRect();
  wall.style.setProperty("--history-slots", slots);
  if (name === "contact-sheet") wall.style.setProperty("--contact-sheet-rows", slots / 2);
  photos.forEach((photo, index) => {
    const lead = !reserveLead && index === 0;
    const image = existing.get(photo.url) || new Image();
    if (!image.parentNode) {
      image.dataset.url = photo.url;
      image.src = photo.url;
      wall.append(image);
    }
    existing.delete(photo.url);
    if (lead) image.getAnimations().forEach(animation => animation.cancel());
    image.className = lead ? "lead-photo" : "history-photo";
    const position = reserveLead ? index + 1 : index;
    image.style.setProperty("--position", position);
    image.dataset.position = position;
    if (name === "contact-sheet" && !lead) {
      image.style.setProperty("--contact-sheet-row", Math.ceil(position / 2));
      image.style.setProperty("--contact-sheet-column", position % 2 ? 2 : 3);
    }
    image.alt = lead ? "Latest capture" : `Previous capture ${position}`;
  });
  for (const image of existing.values()) image.remove();
  if (capturing && oldLead?.isConnected && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const after = oldLead.getBoundingClientRect();
    if (after.width && after.height) {
      oldLead.animate([
        { transform: `translate(${before.x - after.x}px, ${before.y - after.y}px) scale(${before.width / after.width}, ${before.height / after.height})` },
        { transform: getComputedStyle(oldLead).transform },
      ], { duration: 300, easing: "ease-out" });
    }
  }
}

async function updatePhotoWall() {
  const version = state?.photo_wall_version;
  if (!state?.session || !version || version === photoWallVersion || photoWallRequest) return;
  photoWallRequest = true;
  try {
    const columns = Number(state.photo_wall_columns) || 3;
    const rows = Math.max(2, Math.ceil((maxHistoryPhotos + 1) / columns));
    const data = await api(`/api/photo-wall?rows=${rows}`);
    if (state.photo_wall_version === version) {
      photoWallPhotos = data.photos || [];
      photoWallVersion = version;
      renderPhotoWall();
    }
  } catch (error) {
    $("#error").textContent = error.message;
  } finally {
    photoWallRequest = false;
  }
}

async function refresh() {
  if (refreshPending) return;
  refreshPending = true;
  try {
    const current = await api("/api/state");
    if (serverInstanceId !== null && current.server_instance_id !== serverInstanceId) {
      window.location.reload();
      return;
    }
    serverInstanceId = current.server_instance_id ?? serverInstanceId;
    setConnectionStatus(true);
    render(current);
    updatePhotoWall();
  } catch (error) {
    setConnectionStatus(false);
    $("#error").textContent = error.message;
  } finally {
    refreshPending = false;
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
$("#photo-wall").addEventListener("load", (event) => {
  if (state?.capture_layout === "contact-sheet" && event.target.dataset.url === photoWallPhotos[0]?.url) {
    renderPhotoWall();
  }
}, true);
$("#session-input").addEventListener("input", syncPickerName);
$("#start-new-session").addEventListener("click", openNewSessionForm);
$("#back-to-sessions").addEventListener("click", returnToSessionOptions);
$("#create-session").addEventListener("click", createSession);
setInterval(refresh, 250);
const adminPinDialog = $("#admin-pin-dialog");
for (const trigger of [$("#admin-access"), $("#camera-admin-access"), $("#selfie-admin-access")]) {
  trigger.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    startAdminHold(trigger);
  });
  trigger.addEventListener("contextmenu", (event) => event.preventDefault());
  trigger.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (!event.repeat) startAdminHold(trigger);
  });
  for (const name of ["pointerup", "pointercancel", "pointerleave", "keyup", "blur"]) {
    trigger.addEventListener(name, () => {
      if (adminHoldTarget === trigger) cancelAdminHold();
    });
  }
}

adminPinDialog.addEventListener("click", (event) => {
  if (event.target !== adminPinDialog || adminPinKeypad.isPending()) return;
  adminPinDialog.classList.add("hidden");
});
const adminPinKeypad = setupPinKeypad($("#admin-pin-form"), async (pin) => {
  try {
    await api("/api/admin/unlock", { pin });
    openAdminPanel();
  } catch (error) {
    adminPinKeypad.reset(state?.admin_pin_length ?? 4);
    if (error.message === "Invalid PIN") throw new Error("Incorrect PIN. Try again.");
    throw error;
  }
});
