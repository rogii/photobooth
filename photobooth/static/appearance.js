(() => {
  const selector = document.querySelector("#accent-color");
  let savedColor;

  async function refreshAppearance() {
    try {
      const response = await fetch("/api/appearance", { cache: "no-store" });
      if (!response.ok) return;
      const { accent_color: color, colors } = await response.json();

      if (color !== savedColor) {
        const root = document.documentElement;
        root.style.setProperty("--accent", colors[color]);
        root.toggleAttribute("data-accent-tinted", color !== "green");
      }
      if (selector && selector.disabled) {
        for (const name of Object.keys(colors)) {
          selector.add(new Option(name[0].toUpperCase() + name.slice(1), name));
        }
        selector.value = color;
        selector.disabled = false;
      }
      savedColor = color;
    } catch {
      // Keep the last applied accent while the server is unreachable.
    } finally {
      setTimeout(refreshAppearance, 2000);
    }
  }

  refreshAppearance();
})();
