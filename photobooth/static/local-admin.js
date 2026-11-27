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

function say(message, isError = false) {
  const output = $("#message");
  output.textContent = message;
  output.classList.toggle("error", isError);
}

const photoApi = $("[data-photo-api]").dataset.photoApi;
const photoGrid = $("#photo-grid");
const togglePhotoSelection = $("#toggle-photo-selection");

let movingPhotos = false;
let photoRequestId = 0;

async function refreshPhotos() {
  const requestId = ++photoRequestId;
  photoGrid.replaceChildren();
  updatePhotoActions();
  $("#photo-summary").textContent = "Loading photos…";
  try {
    const sessionId = $("#session-filter").value;
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const data = await api(`${photoApi}/photos${query}`);
    if (requestId !== photoRequestId) return;
    const filter = $("#session-filter");
    const selected = filter.value;
    filter.replaceChildren(new Option("All sessions", ""));
    data.sessions.forEach((item) => filter.add(new Option(item.name, item.id)));
    filter.value = data.sessions.some((item) => item.id === selected) ? selected : "";

    $("#photo-summary").textContent = `${data.photos.length} photo${data.photos.length === 1 ? "" : "s"}`;
    if (!data.photos.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No photos found for this selection.";
      photoGrid.append(empty);
    }
    data.photos.forEach((photo) => {
      const card = document.createElement("article");
      card.className = "photo-card";
      const urlPath = photo.relative_path.split("/").map(encodeURIComponent).join("/");
      const imageUrl = `${photoApi}/photo/${encodeURIComponent(photo.session_id)}/${urlPath}`;
      const image = document.createElement("img");
      image.src = imageUrl;
      image.alt = `${photo.session_name}: ${photo.name}`;
      image.loading = "lazy";
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.sessionId = photo.session_id;
      checkbox.dataset.relativePath = photo.relative_path;
      checkbox.addEventListener("change", updatePhotoActions);
      const selection = document.createElement("span");
      selection.className = "photo-selection";
      selection.append(checkbox, document.createTextNode("Select photo"));
      label.append(image, selection);
      const meta = document.createElement("div");
      meta.className = "photo-meta";
      const name = document.createElement("span");
      name.className = "photo-name";
      name.textContent = photo.name;
      const session = document.createElement("span");
      session.textContent = `${photo.session_name} · ${photo.relative_path}`;
      meta.append(name, session);
      card.append(label, meta);
      photoGrid.append(card);
    });
    updatePhotoActions();
  } catch (error) {
    if (requestId !== photoRequestId) return;
    $("#photo-summary").textContent = error.message;
    say(error.message, true);
  }
}

function updatePhotoActions() {
  const photos = photoGrid.querySelectorAll("input[type=checkbox]");
  const selected = photoGrid.querySelectorAll("input[type=checkbox]:checked").length;
  togglePhotoSelection.disabled = movingPhotos || photos.length === 0;
  togglePhotoSelection.textContent = photos.length > 0 && selected === photos.length
    ? "Unselect all"
    : "Select all";
  $("#delete-selected").disabled = movingPhotos || selected === 0;
  $("#delete-selected").textContent = selected ? `Move ${selected} selected to Deleted` : "Move selected to Deleted";
}

$("#session-filter").addEventListener("change", refreshPhotos);
$("#refresh").addEventListener("click", refreshPhotos);
togglePhotoSelection.addEventListener("click", () => {
  const photos = [...photoGrid.querySelectorAll("input[type=checkbox]")];
  const selectAll = photos.some((input) => !input.checked);
  photos.forEach((input) => { input.checked = selectAll; });
  updatePhotoActions();
});
$("#delete-selected").addEventListener("click", async () => {
  const selected = [...photoGrid.querySelectorAll("input[type=checkbox]:checked")];
  if (movingPhotos || !selected.length) return;
  movingPhotos = true;
  updatePhotoActions();
  try {
    const photos = selected.map((input) => ({ session_id: input.dataset.sessionId, relative_path: input.dataset.relativePath }));
    const result = await api(`${photoApi}/delete-photos`, { photos });
    say(`Moved ${result.moved} photo${result.moved === 1 ? "" : "s"} into Deleted. They remain in session ZIP downloads.`);
    await refreshPhotos();
  } catch (error) {
    say(error.message, true);
  } finally {
    movingPhotos = false;
    updatePhotoActions();
  }
});

if ($("#kiosk-link")) {
  setupBluetoothRemote(api);
  const kioskUrl = new URL(window.location.href);
  kioskUrl.port = "8080";
  kioskUrl.pathname = "/";
  kioskUrl.search = "";
  kioskUrl.hash = "";
  $("#kiosk-link").href = kioskUrl.toString();

  const pinDialog = $("#change-pin-dialog");
  const pinTitle = $("#change-pin-title");
  const pinInstructions = pinDialog.querySelector("p");
  let newPin = "";

  function startPinChange() {
    newPin = "";
    pinTitle.textContent = "Enter new PIN";
    pinInstructions.textContent = "Choose a four-digit admin PIN.";
    changePinKeypad.reset(4);
  }

  const changePinKeypad = setupPinKeypad(pinDialog.querySelector("form"), async (pin) => {
    if (!newPin) {
      newPin = pin;
      pinTitle.textContent = "Confirm new PIN";
      pinInstructions.textContent = "Enter the same PIN again.";
      return;
    }
    if (newPin !== pin) {
      startPinChange();
      throw new Error("The PINs did not match. Choose a new PIN and try again.");
    }
    await api("/api/local-admin/pin", { admin_pin: newPin, confirm_pin: pin });
    pinDialog.close();
    say("Admin PIN updated.");
  });

  $("#change-pin").addEventListener("click", () => {
    pinDialog.showModal();
    startPinChange();
  });
  $("#cancel-pin-change").addEventListener("click", () => pinDialog.close());
  pinDialog.addEventListener("cancel", (event) => {
    if (changePinKeypad.isPending()) event.preventDefault();
  });
  pinDialog.addEventListener("close", () => { newPin = ""; });

  const systemActions = [
    { id: "exit-kiosk", label: "Exit to desktop", description: "The kiosk browser will close and the photobooth service will keep running.", message: "Closing the kiosk browser…" },
    { id: "reboot", label: "Restart", description: "The photobooth will be unavailable while the Raspberry Pi restarts.", message: "Raspberry Pi is restarting…" },
    { id: "shutdown", label: "Shut down", description: "The photobooth will be unavailable until the Raspberry Pi is powered on again.", message: "Raspberry Pi is shutting down…" },
  ];
  const confirmation = $("#system-confirmation");
  const confirmButton = $("#confirm-system-action");
  const systemButtons = systemActions.map(({ id }) => document.getElementById(id));
  let selectedAction;

  systemActions.forEach((action, index) => {
    const button = systemButtons[index];
    button.addEventListener("click", () => {
      selectedAction = action;
      $("#system-confirmation-title").textContent = `${button.textContent}?`;
      $("#system-confirmation-description").textContent = action.description;
      confirmButton.textContent = action.label;
      confirmButton.classList.toggle("danger", button.classList.contains("danger"));
      confirmation.showModal();
    });
  });
  confirmation.querySelector("form").addEventListener("submit", async (event) => {
    if (event.submitter !== confirmButton) return;
    event.preventDefault();
    const { id, message } = selectedAction;
    confirmation.close();
    systemButtons.forEach((button) => { button.disabled = true; });
    say(message);
    try {
      await api(`/api/local-admin/${id}`, {});
    } catch (error) {
      say(error.message, true);
      systemButtons.forEach((button) => { button.disabled = false; });
    }
  });
}

refreshPhotos();
