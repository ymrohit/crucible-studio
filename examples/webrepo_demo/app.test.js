const test = require("node:test");
const assert = require("node:assert");
const { barWidth, label } = require("./app.js");

test("fills to the right percentage", () => {
  assert.strictEqual(barWidth(75, 100), "75%");   // bar should be 3/4 full
});

test("half of 200 is 50 percent", () => {
  assert.strictEqual(barWidth(100, 200), "50%");
});

test("clamps overflow to 100 percent", () => {
  assert.strictEqual(barWidth(150, 100), "100%");  // never wider than the track
});

test("clamps negatives to 0 percent", () => {
  assert.strictEqual(barWidth(-10, 100), "0%");
});

test("label shows value out of max", () => {
  assert.strictEqual(label(75, 100), "75 / 100");
});
