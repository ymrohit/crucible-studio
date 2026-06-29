// Tip calculator logic (also wired to the DOM when loaded in a browser).
function calculateTip(amount, pct) {
  return (amount * pct) / 100;
}
function totalWithTip(amount, pct) {
  return amount + calculateTip(amount, pct);
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    const calc = document.getElementById("calc");
    calc.addEventListener("click", () => {
      const amount = parseFloat(document.getElementById("amount").value) || 0;
      const pct = parseFloat(document.getElementById("tip").value) || 0;
      document.getElementById("result").textContent =
        "Total: $" + totalWithTip(amount, pct).toFixed(2);
    });
  });
}

if (typeof module !== "undefined") {
  module.exports = { calculateTip, totalWithTip };
}
