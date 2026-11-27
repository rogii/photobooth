function setupSettingAutosave(form, write) {
  const fields = new Map();
  let queue = Promise.resolve();
  let pending = 0;
  let version = 0;

  for (const input of Array.from(form.elements)) {
    const name = input.name;
    if (!name || input.type === "hidden" || fields.has(name)) continue;
    let feedback = form.querySelector(`[data-save-status="${name}"]`);
    if (!feedback) {
      const label = input.labels[0];
      const field = document.createElement("div");
      field.className = "autosave-field";
      label.before(field);
      feedback = document.createElement("div");
      field.append(label, feedback);
    }

    feedback.classList.add("save-feedback");
    const status = document.createElement("span");
    status.setAttribute("role", "status");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "secondary";
    retry.textContent = "Retry";
    retry.hidden = true;
    feedback.append(status, retry);
    fields.set(name, { status, retry, revision: 0, queued: -1, draft: false });
  }

  function report(field, message, state, retryInput) {
    field.status.textContent = message;
    field.status.dataset.state = state;
    field.retry.hidden = !retryInput;
    field.retry.onclick = retryInput ? () => save(retryInput) : null;
  }

  async function save(input) {
    const field = fields.get(input.name);
    const revision = field.revision;
    if (field.queued === revision) return;
    const credential = input.hasAttribute("data-save-credential");
    if (credential && !input.value.trim()) {
      field.draft = false;
      return;
    }
    if (!input.validity.valid) {
      report(field, input.validationMessage, "error");
      return;
    }

    const value = input.value;
    field.queued = revision;
    report(field, "Saving…", "pending");
    pending += 1;
    queue = queue.then(async () => {
      try {
        await write(input.name, value);
        version += 1;
        if (field.revision !== revision) return;
        if (credential) input.value = "";
        field.draft = false;
        report(field, "✓ Saved", "saved");
      } catch (error) {
        if (field.revision !== revision) return;
        field.queued = -1;
        report(field, error.message, "error", input);
      } finally {
        pending -= 1;
      }
    });
  }

  form.addEventListener("input", ({ target }) => {
    const field = fields.get(target.name);
    if (!field) return;
    field.revision += 1;
    field.draft = true;
    report(field, "", "");
  });
  form.addEventListener("change", ({ target }) => {
    if (fields.has(target.name)) save(target);
  });
  form.addEventListener("submit", (event) => event.preventDefault());
  form.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing || !(event.target instanceof HTMLInputElement)) return;
    if (!fields.get(event.target.name)?.draft) return;
    event.preventDefault();
    save(event.target);
  });

  return {
    get version() { return version; },
    get pending() { return pending > 0; },
    get settled() { return queue; },
    hasDraft: (name) => fields.get(name)?.draft,
  };
}
