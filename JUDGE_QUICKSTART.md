# Judge Quickstart

Crucible is a verification-first coding agent UI. It runs a fast baseline on the left, then runs a non-colluding Architect -> Adversary -> Implementer -> Surgeon -> Arbiter loop on the right. The right side exposes generated tests, counterexamples, and verified/floor code.

## 1. Clone And Configure

```bash
git clone <repo-url>
cd crucible
cp .env.example .env
```

Edit `.env`:

```bash
CEREBRAS_API_KEY=your_cerebras_key_here
AISTUDIO_GEMMA4_KEY=your_google_ai_studio_key_here
CRUCIBLE_SANDBOX=local
```

`CEREBRAS_API_KEY` is required for the agent loop. `AISTUDIO_GEMMA4_KEY` is optional but enables the Google AI Studio / Gemma baseline speed race on the left.

## 2. Run The Studio

```bash
./run_studio.sh
```

Open:

```text
http://127.0.0.1:8001
```

The script creates `.venv`, installs Python dependencies, installs frontend dependencies, builds the Svelte UI, and starts the FastAPI/SSE server.

## 3. Demo Prompts

Use the built-in cases from the case picker:

- `Code -> rate limiter`: stateful rolling-window/idempotency edge cases.
- `Build -> incident triage`: renders and verifies an interactive app.
- `Fix -> broken limiter`: paste-code repair mode with source on the left and fixed code on the right.

In Code mode, click any gauntlet row such as `examples`, `properties`, or `differential` to inspect the generated tests/reference behind the pass/fail status.

## Notes

- The repo does not include real API keys.
- For strongest sandbox isolation, install Docker and set `CRUCIBLE_SANDBOX=docker`.
- Without an AI Studio key, the baseline pane falls back to the Cerebras vanilla baseline when available.
