/** Blocking inline script — runs before first paint to prevent theme flash. */
export function ThemeScript() {
  const script = `
(function () {
  try {
    var raw = localStorage.getItem("qa-theme");
    if (!raw) return;
    var mode = JSON.parse(raw);
    if (mode === "light") {
      document.documentElement.setAttribute("data-theme", "light");
    }
  } catch (e) {}
})();
`.trim();

  return <script dangerouslySetInnerHTML={{ __html: script }} />;
}
