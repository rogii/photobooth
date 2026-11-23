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

const kioskUrl = new URL(window.location.href);
kioskUrl.port = "8080";
kioskUrl.pathname = "/";
kioskUrl.search = "";
kioskUrl.hash = "";
$("#kiosk-link").href = kioskUrl.toString();

async function refreshPhotos() {
  $("#photo-summary").textContent = "Loading photos…";
  try {
    const sessionId = $("#session-filter").value;
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const data = await api(`/api/local-admin/photos${query}`);
    const filter = $("#session-filter");
    const selected = filter.value;
    filter.replaceChildren(new Option("All sessions", ""));
    data.sessions.forEach((item) => filter.add(new Option(item.name, item.id)));
    filter.value = data.sessions.some((item) => item.id === selected) ? selected : "";

    const grid = $("#photo-grid");
    grid.replaceChildren();
    $("#photo-summary").textContent = `${data.photos.length} photo${data.photos.length === 1 ? "" : "s"}`;
    if (!data.photos.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No photos found for this selection.";
      grid.append(empty);
    }
    data.photos.forEach((photo) => {
      const card = document.createElement("article");
      card.className = "photo-card";
      const urlPath = photo.relative_path.split("/").map(encodeURIComponent).join("/");
      const imageUrl = `/api/local-admin/photo/${encodeURIComponent(photo.session_id)}/${urlPath}`;
      const image = document.createElement("img");
      image.src = imageUrl;
      image.alt = `${photo.session_name}: ${photo.name}`;
      image.loading = "lazy";
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.sessionId = photo.session_id;
      checkbox.dataset.relativePath = photo.relative_path;
      checkbox.addEventListener("change", updateDeleteButton);
      label.append(checkbox, document.createTextNode("Select photo"));
      const meta = document.createElement("div");
      meta.className = "photo-meta";
      const name = document.createElement("span");
      name.className = "photo-name";
      name.textContent = photo.name;
      const session = document.createElement("span");
      session.textContent = `${photo.session_name} · ${photo.relative_path}`;
      meta.append(name, session);
      card.append(image, label, meta);
      grid.append(card);
    });
    updateDeleteButton();
  } catch (error) {
    $("#photo-summary").textContent = error.message;
    say(error.message, true);
  }
}

function updateDeleteButton() {
  const selected = $("#photo-grid").querySelectorAll("input[type=checkbox]:checked").length;
  $("#delete-selected").disabled = selected === 0;
  $("#delete-selected").textContent = selected ? `Move ${selected} selected to Deleted` : "Move selected to Deleted";
}

$("#session-filter").addEventListener("change", refreshPhotos);
$("#refresh").addEventListener("click", refreshPhotos);
$("#delete-selected").addEventListener("click", async () => {
  const selected = [...$("#photo-grid").querySelectorAll("input[type=checkbox]:checked")];
  if (!selected.length || !confirm(`Move ${selected.length} selected photo${selected.length === 1 ? "" : "s"} into the Deleted folder? They will disappear from the kiosk gallery and capture count, but remain in session ZIP downloads.`)) return;
  try {
    const photos = selected.map((input) => ({ session_id: input.dataset.sessionId, relative_path: input.dataset.relativePath }));
    const result = await api("/api/local-admin/delete-photos", { photos });
    say(`Moved ${result.moved} photo${result.moved === 1 ? "" : "s"} into Deleted. They remain in session ZIP downloads.`);
    await refreshPhotos();
  } catch (error) {
    say(error.message, true);
  }
});

$("#pin-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("#new-pin");
  try {
    await api("/api/local-admin/pin", { admin_pin: input.value });
    input.value = "";
    say("Admin PIN updated.");
  } catch (error) {
    say(error.message, true);
  }
});

$("#shutdown").addEventListener("click", async () => {
  if (!confirm("Shut down the Raspberry Pi now? The photobooth will be unavailable until it is powered on again.")) return;
  const button = $("#shutdown");
  button.disabled = true;
  try {
    await api("/api/local-admin/shutdown", {});
    say("Raspberry Pi is shutting down…");
  } catch (error) {
    say(error.message, true);
    button.disabled = false;
  }
});

refreshPhotos();
