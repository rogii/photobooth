function setupPinKeypad(form, onComplete) {
  const input = form.querySelector("input");
  const progress = form.querySelector(".admin-pin-progress");
  const pad = form.querySelector(".admin-pin-pad");
  const error = form.querySelector(".admin-pin-error");
  let length = 4;
  let digits = "";
  let pending = false;

  function renderDigits() {
    if (input) input.value = digits;
    if (progress) progress.value = "●".repeat(digits.length) + "○".repeat(length - digits.length);
  }

  function focusKeypad() {
    (input ?? form).focus();
  }

  function reset(newLength = length) {
    length = newLength;
    if (input) input.maxLength = length;
    digits = "";
    renderDigits();
    error.textContent = "";
    focusKeypad();
  }

  async function updateDigits(value) {
    if (pending) return;
    digits = value.replace(/[^0-9]/g, "").slice(0, length);
    renderDigits();
    error.textContent = "";
    if (digits.length !== length) return;

    pending = true;
    const controls = [...form.querySelectorAll("input, button")];
    controls.forEach((control) => { control.disabled = true; });
    try {
      await onComplete(digits);
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      digits = "";
      renderDigits();
      controls.forEach((control) => { control.disabled = false; });
      pending = false;
      focusKeypad();
    }
  }

  pad.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    updateDigits(button.hasAttribute("data-backspace") ? digits.slice(0, -1) : digits + button.dataset.digit);
  });

  if (input) {
    input.addEventListener("input", () => updateDigits(input.value));
  } else {
    form.addEventListener("keydown", (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "Backspace") {
        event.preventDefault();
        updateDigits(digits.slice(0, -1));
      } else if (/^[0-9]$/.test(event.key)) {
        event.preventDefault();
        updateDigits(digits + event.key);
      }
    });
  }

  form.addEventListener("submit", (event) => event.preventDefault());
  return { reset, isPending: () => pending };
}
