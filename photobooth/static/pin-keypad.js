function setupPinKeypad(form, onComplete) {
  const input = form.querySelector("input");
  const pad = form.querySelector(".admin-pin-pad");
  const error = form.querySelector(".admin-pin-error");
  let length = 4;
  let pending = false;

  function reset(newLength = length) {
    length = newLength;
    input.maxLength = length;
    input.value = "";
    error.textContent = "";
    input.focus();
  }

  async function checkInput() {
    input.value = input.value.replace(/[^0-9]/g, "").slice(0, length);
    error.textContent = "";
    if (pending || input.value.length !== length) return;

    pending = true;
    const controls = [...form.querySelectorAll("input, button")];
    controls.forEach((control) => { control.disabled = true; });
    try {
      await onComplete(input.value);
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      input.value = "";
      controls.forEach((control) => { control.disabled = false; });
      pending = false;
      input.focus();
    }
  }

  for (const digit of "1234567890") {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.digit = digit;
    button.textContent = digit;
    button.addEventListener("click", () => {
      input.value += digit;
      checkInput();
    });
    pad.append(button);
  }

  const backspace = document.createElement("button");
  backspace.type = "button";
  backspace.textContent = "⌫";
  backspace.setAttribute("aria-label", "Backspace");
  backspace.addEventListener("click", () => {
    input.value = input.value.slice(0, -1);
    checkInput();
  });
  pad.append(backspace);

  input.addEventListener("input", checkInput);
  form.addEventListener("submit", (event) => event.preventDefault());
  return { reset, isPending: () => pending };
}
