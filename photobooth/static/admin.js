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
    const captureDisabled = !state.session || state.busy;
    $("#capture-one").disabled = captureDisabled;
    $("#capture-four").disabled = captureDisabled;
  } catch (error) {
    $("#status").textContent = error.message;
  }
}

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
