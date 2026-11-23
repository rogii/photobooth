const $ = (selector) => document.querySelector(selector);

const ui = {
  connection: $("#connection-label"),
  connectionWrap: $(".connection"),
  connectionDot: $("#connection-dot"),
  demoBadge: $("#demo-badge"),
  photo: $("#photo-image"),
  photoPlaceholder: $("#photo-placeholder"),
  photoLabel: $("#photo-label"),
  statusTitle: $("#status-title"),
  statusDetail: $("#status-detail"),
  countdown: $("#countdown-overlay"),
  sessionName: $("#session-name"),
  sessionDialog: $("#session-dialog"),
  sessionInput: $("#session-input"),
  resumeButton: $("#resume-session"),
  cancelButton: $("#cancel-session"),
  createButton: $("#create-session"),
  error: $("#dialog-error"),
  single: $("#single-capture"),
  sequence: $("#sequence-capture"),
  flash: $("#flash-state"),
  queue: $("#queue-label"),
  toast: $("#toast"),
};

let currentState = null;
let lastRecentVersion = "";
let shiftNext = false;
let toastTimer = null;

function showToast(message) {
  ui.toast.textContent = message;
  ui.toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ui.toast.classList.remove("visible"), 2800);
}

function setDialog(state) {
  ui.error.textContent = "";
  ui.sessionInput.value = "";
  ui.createButton.disabled = true;
  if (state?.last_session) {
    ui.resumeButton.textContent = `Resume “${state.last_session.name}”`;
    ui.resumeButton.classList.remove("hidden");
  } else {
    ui.resumeButton.classList.add("hidden");
  }
  ui.cancelButton.classList.toggle("hidden", !state?.session);
  if (!ui.sessionDialog.open) ui.sessionDialog.showModal();
  setTimeout(() => ui.sessionInput.focus(), 60);
}

function renderKeyboard() {
  const keyboard = $("#onscreen-keyboard");
  const rows = ["1234567890", "qwertyuiop", "asdfghjklå", "zxcvbnmäö.-"];
  keyboard.replaceChildren();
  rows.forEach((chars, rowIndex) => {
    const row = document.createElement("div");
    row.className = "keyboard-row";
    [...chars].forEach((char) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "key-button";
      button.textContent = shiftNext ? char.toLocaleUpperCase("sv-SE") : char;
      button.addEventListener("click", () => insertText(shiftNext ? char.toLocaleUpperCase("sv-SE") : char));
      row.append(button);
    });
    if (rowIndex === 3) {
      const shift = document.createElement("button");
      shift.type = "button";
      shift.className = "key-button wide";
      shift.textContent = shiftNext ? "Shift ▲" : "Shift";
      shift.addEventListener("click", () => {
        shiftNext = !shiftNext;
        renderKeyboard();
      });
      row.prepend(shift);
    }
    keyboard.append(row);
  });
  const controls = document.createElement("div");
  controls.className = "keyboard-row";
  [
    ["Bksp", "wide", backspace],
    ["Space", "space", () => insertText(" ")],
    ["Clear", "wide", () => { ui.sessionInput.value = ""; syncName(); }],
  ].forEach(([label, size, callback]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `key-button ${size}`;
    button.textContent = label;
    button.addEventListener("click", callback);
    controls.append(button);
  });
  keyboard.append(controls);
}

function insertText(text) {
  const input = ui.sessionInput;
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? input.value.length;
  input.setRangeText(text, start, end, "end");
  if (shiftNext) {
    shiftNext = false;
    renderKeyboard();
  }
  syncName();
  input.focus();
}

function backspace() {
  const input = ui.sessionInput;
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? input.value.length;
  if (start !== end) input.setRangeText("", start, end, "end");
  else if (start > 0) input.setRangeText("", start - 1, start, "end");
  syncName();
  input.focus();
}

function syncName() {
  ui.createButton.disabled = !ui.sessionInput.value.trim();
}

async function request(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : {};
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function render(state) {
  currentState = state;
  ui.connection.textContent = state.busy ? "CAPTURING" : "SYSTEM READY";
  ui.connectionWrap.classList.add("connected");
  ui.connectionWrap.classList.remove("error");
  ui.demoBadge.classList.toggle("hidden", !state.demo);
  ui.statusTitle.textContent = state.busy ? "Capture in progress" : (state.status.startsWith("Capture failed") ? "Camera needs attention" : "Ready when you are");
  ui.statusDetail.textContent = state.status;
  ui.sessionName.textContent = state.session?.name || "No session selected";
  ui.single.disabled = !state.session || state.busy;
  ui.sequence.disabled = !state.session || state.busy;
  ui.countdown.textContent = state.countdown;
  ui.countdown.classList.toggle("hidden", !state.countdown);
  ui.flash.classList.toggle("available", state.flash_available);
  ui.flash.lastChild.textContent = state.flash_available ? " FLASH READY" : " FLASH OFF";
  ui.queue.textContent = `${state.queued_uploads} UPLOAD${state.queued_uploads === 1 ? "" : "S"} QUEUED`;
  const recentVersion = state.recent_photo_version || "";
  if (state.recent_photo && recentVersion) {
    ui.photoLabel.textContent = "JUST CAPTURED";
    if (recentVersion !== lastRecentVersion) {
      lastRecentVersion = recentVersion;
      ui.photo.onload = () => {
        ui.photo.hidden = false;
        ui.photoPlaceholder.classList.add("hidden");
      };
      ui.photo.onerror = () => {
        ui.photo.hidden = true;
        ui.photoPlaceholder.classList.remove("hidden");
        showToast("Could not load the captured photo");
      };
      ui.photo.src = `/api/recent-photo?v=${encodeURIComponent(recentVersion)}`;
    }
  } else {
    ui.photo.hidden = true;
    ui.photoPlaceholder.classList.remove("hidden");
    ui.photoLabel.textContent = state.busy ? "GETTING READY" : "READY FOR A PHOTO";
  }
  if (!state.session && !ui.sessionDialog.open) setDialog(state);
}

async function refresh() {
  try {
    render(await request("/api/state"));
  } catch (error) {
    ui.connection.textContent = "Server unavailable";
    ui.connectionWrap.classList.add("error");
    ui.statusTitle.textContent = "Photobooth server offline";
    ui.statusDetail.textContent = error.message;
  }
}

async function createSession() {
  try {
    await request("/api/session", { name: ui.sessionInput.value });
    ui.sessionDialog.close();
    await refresh();
    showToast("Session started");
  } catch (error) {
    ui.error.textContent = error.message;
  }
}

async function resumeSession() {
  try {
    await request("/api/session/resume", {});
    ui.sessionDialog.close();
    await refresh();
    showToast("Session resumed");
  } catch (error) {
    ui.error.textContent = error.message;
  }
}

async function capture(count) {
  if (!currentState?.session || currentState.busy) return;
  try {
    await request("/api/capture", {
      count,
      countdown: Number($("#countdown-input").value || 0),
      interval: Number($("#interval-input").value || 0),
    });
    await refresh();
  } catch (error) {
    showToast(error.message);
  }
}

$("#create-session").addEventListener("click", createSession);
$("#resume-session").addEventListener("click", resumeSession);
$("#cancel-session").addEventListener("click", () => ui.sessionDialog.close());
$("#session-button").addEventListener("click", () => setDialog(currentState));
$("#session-input").addEventListener("input", syncName);
$("#session-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && ui.sessionInput.value.trim()) createSession();
});
$("#single-capture").addEventListener("click", () => capture(1));
$("#sequence-capture").addEventListener("click", () => capture(4));
$("#exit-button").addEventListener("click", async () => {
  if (!window.confirm("Restart the photobooth service?")) return;
  try {
    await request("/api/restart", {});
    ui.statusTitle.textContent = "Photobooth restarting";
    ui.statusDetail.textContent = "This screen will reconnect in a moment.";
    setTimeout(() => location.reload(), 1800);
  } catch (error) {
    showToast(error.message);
  }
});
document.addEventListener("keydown", (event) => {
  if (ui.sessionDialog.open || event.target instanceof HTMLInputElement) return;
  if (event.key.toLowerCase() === "a") capture(1);
  if (event.key.toLowerCase() === "b") capture(4);
});

renderKeyboard();
refresh();
setInterval(refresh, 800);
