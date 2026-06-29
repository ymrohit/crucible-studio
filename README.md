# Crucible Studio

**Trust, but verify for generated code.**

Crucible Studio is a Gemma 4 / Cerebras agent system that refuses to ship code just because it
looks plausible. It turns a prompt into a frozen contract, generates adversarial tests blind to the
candidate, executes a real oracle gauntlet, repairs from counterexamples, and only marks the result
verified when the runtime evidence goes green.

[Watch the demo video](Crucible.mp4)

Public repo: https://github.com/ymrohit/crucible-studio

## What It Shows

Most coding demos stop at "the model wrote code". Crucible shows the missing half:

```text
Prompt
  -> Architect freezes the spec
  -> Adversary writes tests without seeing the code
  -> Implementer writes code without seeing the tests
  -> Oracle executes parse, typecheck, smoke, examples, properties, differential
  -> Surgeon repairs from the failing counterexample
  -> Arbiter handles repeated failures as code bug, bad test, or underspecified prompt
  -> Verified code ships, or a clearly labeled floor is returned
```

The UI puts this next to a vanilla Gemma baseline so judges can see the difference live: fast
unverified output on one side, evidence-backed output on the other.

## Why It Matters

LLMs are very good at producing code-shaped text. The hard part is knowing when the answer is
actually correct.

Crucible makes correctness observable:

- The test writer cannot see the implementation.
- The implementation writer cannot see the tests.
- The model never grades itself.
- The verdict comes from execution, not prose.
- Counterexamples are surfaced in the UI so judges can inspect the exact failure.
- Generated tests, final code, and gauntlet output remain visible instead of disappearing between tabs.

This is especially useful for complex prompts where one-shot generation often looks impressive but
silently misses state, boundary, idempotency, ordering, or mutation bugs.

## Demo Modes

### Code

Generate a fresh function from a complex prompt. Crucible creates the contract, writes hostile tests,
runs the gauntlet, repairs failures, and returns verified code.

Good demo prompts include stateful or edge-heavy tasks:

- Per-user rolling-window rate limiting with duplicate event IDs and out-of-order timestamps.
- Nested rules engines with stable rejection explanations.
- Inventory ledgers with reservation, release, expiry, and invalid-event accounting.

### Fix

Paste broken code on the left and get corrected code on the right. This is the fastest judge demo:
they can edit the broken function, run it, open the Test tab, inspect the generated adversarial cases,
and open Output to see the actual failure and repair trail.

The included limiter example intentionally fails at boundary/idempotency behavior. Crucible catches
the concrete counterexample, patches it, and shows the tests that forced the repair.

### Build

Generate a small interactive application and run a verification loop against the rendered result.
This mode is designed to show that Crucible is not only a function harness; it can also reason about
product behavior and UI output.

## Quick Start

```bash
git clone https://github.com/ymrohit/crucible-studio.git
cd crucible-studio
cp .env.example .env
```

Fill in `.env`:

```bash
CEREBRAS_API_KEY=your_cerebras_api_key_here
AISTUDIO_GEMMA4_KEY=your_google_ai_studio_key_here
CRUCIBLE_MODEL=gemma-4-31b
CRUCIBLE_SANDBOX=local
```

Run the studio:

```bash
./run_studio.sh
```

Open:

```text
http://127.0.0.1:8001
```

The script creates a virtualenv if needed, installs Python dependencies, installs frontend
dependencies when missing, builds the Svelte UI, and starts the FastAPI SSE server.

## Judge Path

For a fast review:

1. Open `http://127.0.0.1:8001`.
2. Choose **Fix**.
3. Keep the **broken limiter** case selected.
4. Click **Run**.
5. Open **Test** to inspect the adversarial examples/properties.
6. Open **Output** to inspect the gauntlet stages, counterexample, and repair.
7. Open **Fixed** to see the corrected implementation.

No credentials are committed. Use `.env.example` as the template.

## Architecture

| Path | Purpose |
|---|---|
| `crucible/agents/` | Architect, Adversary, Implementer, Surgeon, Arbiter, and provider runtime |
| `crucible/oracle/` | Deterministic gauntlet stages and sandboxed execution harness |
| `crucible/orchestrator/` | Repair state machine, budgets, event stream, and routing |
| `crucible/ui/server.py` | FastAPI server and SSE fan-in for live runs |
| `frontend/src/` | Svelte Studio UI |
| `examples/` | Bundled demo repositories and sample repair targets |
| `JUDGE_QUICKSTART.md` | Short setup instructions for reviewers |

## Guarantees

- **Blind roles:** Adversary and Implementer do not share hidden context.
- **Executable verdicts:** parse, typecheck, smoke, examples, property tests, and differential checks
  are real stages, not model self-evaluation.
- **Visible evidence:** generated tests, counterexamples, output, and final code are inspectable.
- **Floor instead of bluffing:** if verification cannot finish, the UI labels the best partial result
  and the unverified stage.
- **No secrets in repo:** credentials live only in `.env`; `.env.example` documents required keys.

## Demo Video

The submitted demo video is included at:

```text
Crucible.mp4
```

If GitHub does not inline-play it in your browser, download the file from the repository root.
