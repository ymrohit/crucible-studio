// Score meter logic (also wired to the DOM when loaded in a browser).
// barWidth(value, max) -> a CSS width string like "75%" for a value out of max,
// clamped to the 0..100% range. e.g. barWidth(75, 100) === "75%".
function barWidth(value, max) {
  const ratio = value / max;            // BUG: returns a fraction string ("0.75%"),
  return ratio + "%";                   // never scaled to a percentage, never clamped.
}

function label(value, max) {
  return value + " / " + max;
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    const render = () => {
      const value = parseFloat(document.getElementById("value").value) || 0;
      const max = parseFloat(document.getElementById("max").value) || 100;
      document.getElementById("fill").style.width = barWidth(value, max);
      document.getElementById("label").textContent = label(value, max);
    };
    document.getElementById("value").addEventListener("input", render);
    document.getElementById("max").addEventListener("input", render);
    render();
  });
}

if (typeof module !== "undefined") {
  module.exports = { barWidth, label };
}
