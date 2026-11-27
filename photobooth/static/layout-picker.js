const form = document.querySelector("#layout-form");
const sample = document.querySelector("#sample");

form.elements.event_font.addEventListener("change", (event) => {
  sample.dataset.font = event.target.value;
});

const autosave = setupSettingAutosave(form, async (name, value) => {
  const response = await fetch(form.action, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: form.elements.token.value, [name]: value }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.saved) {
    throw new Error(data.error || "Reopen the layout picker or try saving again.");
  }
});

document.querySelector("#back-to-admin").addEventListener("click", async (event) => {
  if (!autosave.pending || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const href = event.currentTarget.href;
  event.preventDefault();
  await autosave.settled;
  if (!autosave.hasDraft("capture_layout") && !autosave.hasDraft("event_font")) location.assign(href);
});
