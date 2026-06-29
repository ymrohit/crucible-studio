# Claude Code — Build Brief for Crucible

> Paste this whole file as your opening message to Claude Code, with `SPEC.md` present in the repo root. This is your build brief; `SPEC.md` is the source of truth for agent prompts, schemas, the demo protocol, and the storyboard. When they disagree, SPEC.md wins.

---

## Mission

Build **Crucible**, a verification-first AI coding agent. The user gives a coding request; the system runs five non-colluding LLM roles (Architect → Adversary → Implementer → Surgeon → Arbiter) around a deterministic orchestrator and an executable oracle gauntlet, and **only ever returns code that passed the gauntlet**. The model is Gemma 4 31B on Cerebras. Read `SPEC.md` in full before writing code — especially §2 (architecture), §6 (schemas — the seam), §7 (state machine), §8 (the five system prompts, verbatim), §10 (sandbox), §3 (gauntlet).

The win condition for this build: a working end-to-end loop on one demo problem, driving a split-screen web UI where the left pane shows vanilla Gemma's fast-but-wrong answer and the right pane shows Crucible's pipeline lighting up, a property test going red with a shrunk counterexample, the Surgeon patching it, and the gauntlet going green — with a live tok/s readout throughout.

## Stack

Python 3.12. `pydantic` v2, `httpx` (Cerebras Chat Completions, OpenAI-compatible), `hypothesis`, `pyright` (subprocess), `fastapi` + `uvicorn` + SSE for the UI server, vanilla HTML/CSS/JS for the frontend (no build step). Docker for the sandbox container. `CEREBRAS_API_KEY` from a `.env`. Pin everything in `requirements.txt`.

## Build in phases. After each phase, run it and show me it works before moving on.

### Phase 0 — Scaffold + the seam
Create the repo layout from SPEC.md §5. Implement `shared/schemas.py` EXACTLY as in §6 (every model, every field). Implement `orchestrator/events.py` with the event types listed at the end of §6. Implement `agents/base.py`: a Cerebras client that takes a system prompt + user content + a pydantic schema, calls Chat Completions with `model="gemma-4-31b"` and strict json_schema `response_format`, validates the response into the schema (one cheap retry on validation failure with the error appended), and returns `(parsed_obj, usage, time_info)`. Add a `reasoning_effort` parameter (default off).
**Gate:** a throwaway script calls `base.py` with a trivial schema and prints back a validated object + token usage + tokens/sec.

### Phase 1 — Spec → code (no oracle yet)
Implement `architect.py` and `implementer.py` using the verbatim prompts in SPEC.md §8 (create `agents/prompts/architect.txt` and `implementer.txt` from §8 and load them). Architect uses `reasoning_effort="medium"`, Implementer off.
**Gate:** `python -m crucible "merge overlapping booking intervals"` prints a populated `Spec` (with explicit_decisions) and a `Candidate`.

### Phase 2 — The gauntlet + sandbox
Implement `oracle/sandbox.py` per SPEC.md §10: one persistent `python:3.12-slim`+`pyright`+`hypothesis` container (`--network none`, mem limit, ro except `/tmp`), each candidate in a fresh subprocess with a hard timeout → kill → fail. Seed `PYTHONHASHSEED=0` and Hypothesis. Implement `oracle/gauntlet.py` running stages in order with short-circuit, each returning a `StageResult`. Implement stages `parse`, `typecheck`, `smoke` first.
**Gate:** feed a known-good and a known-broken function through parse/typecheck/smoke; correct pass/fail + structured failure detail.

### Phase 3 — Adversary + the catching stages
Implement `adversary.py` (verbatim prompt, blind to code — it receives ONLY the Spec). Implement `stages/examples.py`, `stages/properties.py` (Hypothesis runner that **shrinks** failures into a minimal `Counterexample`), and `stages/differential.py` (candidate vs `oracle.differential_reference` over fuzzed inputs, equality/`allclose`; skip cleanly when the reference is None).
**Gate:** on a deliberately off-by-one interval-merge, the properties stage fails and returns a minimal counterexample `(input, actual, expected, "properties")`.

### Phase 4 — Surgeon + Arbiter + the loop
Implement `surgeon.py` and `arbiter.py` (verbatim prompts). Implement `orchestrator/budget.py` (`max_tokens=60_000`, `max_iters=8`, `max_seconds=90`, charged from every response's usage) and `orchestrator/state_machine.py` EXACTLY as the pseudocode in SPEC.md §7: sequential repair by default; escalate to Arbiter when the same stage fails twice; on `bad_test` patch the oracle, on `underspecified` revise spec + rebuild oracle, on `code_bug` fan out k=3 and keep the best by gauntlet; graceful floor on budget exhaustion. Emit every event from §6 at the right points.
**Gate:** end-to-end on the off-by-one interval problem — it converges to all-green and emits `candidate_delivered`. Force a bad test and confirm the Arbiter routes to `bad_test` and the loop recovers.

### Phase 5 — UI (the visceral part)
Implement `ui/server.py`: a FastAPI app with a `POST /run` that starts a task and an SSE endpoint streaming the orchestrator's events. Implement `ui/static/` as a single page with a **split screen**: LEFT pane runs a plain single-shot Gemma call (`bench/vanilla_baseline.py`) and shows its output fast; RIGHT pane renders the live event stream — agents lighting up in sequence, the gauntlet stages flipping ✅/❌, a **counterexample card** when properties fail, the Surgeon's diff, and a **live tokens/sec counter** from the `metrics` events. The **deliverable area shows only the final verified code**; the churn lives in a side panel. Add a "feed both the counterexample" button that shows vanilla returning wrong and Crucible correct.
**Gate:** open the page, type the prompt, watch the full red→green story play out live on the right while the left shows the fast-but-wrong vanilla answer.

### Phase 6 — Offline runner (separate, runs in background)
Implement `bench/run_offline.py`: load 30–50 problems from `bench/problems/`, run Condition A (vanilla single-shot) and Condition B (full Crucible loop) per SPEC.md §12, scoring pass@1 on each problem's HIDDEN tests. **The loop must NEVER see the hidden scoring tests** — only its own Adversary-generated oracle. Print `pass@1 A vs B` and median wall-clock A vs B. This is standalone; it does not block the UI.
**Gate:** runs on 3 sample problems and prints a comparison table.

## Hard constraints (do NOT violate)

- **Roles cannot collude.** The Adversary receives the Spec only — never the candidate code. The Implementer receives the Spec only — never the oracle. Enforce this at the function-signature level; do not pass the forbidden object in.
- **The oracle owns the score.** Pass/fail comes only from `StageResult`. No agent ever judges its own output.
- **Output is gated.** Nothing reaches the deliverable area until the gauntlet is all-green (or the floor returns a clearly-labeled partial). Never present unverified code as done.
- **Hidden tests stay hidden.** In the offline runner, the loop sees only Adversary-generated tests; hidden scoring tests are read only by the scorer.
- **Budget is hard.** The governor caps tokens/iters/wall and forces the floor on exhaustion. The loop must be unable to run away.
- **Timeout = fail, never hang.** Every sandbox subprocess has a hard kill.
- **Structured output everywhere.** Every agent call uses strict json_schema matching §6; validate before use.

## Do NOT do these (time sinks / scope traps)

- Do not implement docker-per-candidate isolation — use the persistent container + fresh subprocess.
- Do not build a SWE-bench harness. Function-level problems only for this build.
- Do not add best-of-N to the happy path — fan-out (k=3) fires only when stalled, per §7.
- Do not build the mutation-testing rig unless everything else is done (it's an optional credibility slide).
- Do not fake latency in the UI — show vanilla finishing fast-but-wrong and Crucible taking ~20s but right.
- Do not use localStorage/sessionStorage in the frontend — keep state in memory.

## Final acceptance

`python -m crucible.ui.server` serves a page where I type *"merge overlapping booking intervals"* and watch: vanilla (left) emit fast-but-wrong code; Crucible (right) run Architect→Adversary→Implementer, fail a property test with a visible shrunk counterexample, the Surgeon patch it, the gauntlet go all-green, and the verified code appear in the deliverable area — with a live tok/s readout the whole time. Plus `bench/run_offline.py` produces a vanilla-vs-Crucible pass@1 table on sample problems.

Start with Phase 0. Read SPEC.md first.
```
