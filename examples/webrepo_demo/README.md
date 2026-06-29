# Score Meter (demo frontend repo — planted visual bug)

Vanilla JS, self-contained, no network. A score meter: enter a `value` and a `max`,
the green bar fills to `value/max` and a label shows `value / max`.

- `barWidth(value, max)` -> CSS width string, e.g. `barWidth(75, 100) === "75%"`,
  clamped to `0%..100%`.
- `label(value, max)` -> `"75 / 100"`.

Wired to the page in `app.js`; the bar's width is set from `barWidth(...)`.

Run tests: `npm test` (uses `node --test`).

## Planted bug (for the repo-fix / vision-QA demo)
`barWidth` returns the raw ratio as a percent string (`"0.75%"`) instead of scaling to
a percentage and clamping. On screen the green bar is **essentially invisible even at a
high score** — the fix (`* 100` + clamp to 0..100) makes the bar visibly fill to the
correct level, which the vision QA pass can confirm from the rendered screenshot.
`npm test` fails on this bug and goes green after the fix.
