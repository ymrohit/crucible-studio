# Crucible

**The only Gemma harness fast enough to attack its own output five ways and prove it isn't a facade.**

A blind adversary writes the tests, an executable oracle gauntlet runs them, a surgeon repairs from
counterexamples, and only verified code ships. Powered by **Gemma 4 31B on Cerebras (~1,800 tok/s)**.

> Vanilla AI gives you code that looks right. Crucible gives you code that fought back and survived.

The Gemma team's stated #1 gripe is models that produce "the shape of correct" - facades that pass a
glance and fail in production. Crucible is built to answer exactly that: it splits one model into five
**non-colluding roles** and never lets any of them grade its own homework. Pass/fail comes only from
executing code, never from an LLM judging itself.

```
prompt -> Architect (frozen spec) -> Adversary (blind tests) -> Implementer (blind code)
        -> ORACLE GAUNTLET  parse -> typecheck -> smoke -> examples -> properties -> differential
        -> green? DELIVER  |  red? Surgeon repairs from the shrunk counterexample
        -> same stage fails twice? Arbiter rules: code_bug / bad_test / underspecified
```

The roles **cannot collude** - it is enforced at the function-signature level:
- The **Adversary** sees the spec only, never the candidate code (it cannot weaken a test to bless a bug).
- The **Implementer** sees the spec only, never the oracle (it cannot game the tests).
- The **oracle owns the score** - verdicts come from real execution and static analysis, not self-judgement.

When a problem cannot be solved, Crucible says exactly what it could not verify instead of shipping
confident garbage. Calibration, not 100%.

## Three modes, one verify-first loop

**1. Code a function** - give it a problem, get back a function that survived the gauntlet.
```bash
python -m crucible "merge overlapping booking intervals"
```
Architect freezes the spec, the blind Adversary writes property + example tests, the Implementer codes
blind to those tests, the oracle executes everything (with Hypothesis property fuzzing), and the Surgeon
repairs from the shrunk minimal counterexample until green.

**2. Build an app** - a real multi-file FastAPI service, verified by actually running it.
```bash
docker build -f docker/product.Dockerfile -t crucible-product:latest docker/   # once
python -m crucible.product "a URL-shortener REST service"
```
The Architect freezes the API contract, the blind Adversary writes an HTTP integration test, the
Implementer writes the files, and the oracle is a **real Docker container** that boots `uvicorn main:app`
(`--network none`) and runs the test. Only a service that boots and passes ships.

**3. Fix a repo** - point it at an existing codebase and say "build X" or "fix Y".
```bash
python -m crucible.repo <repo-path> "fix the discount calculation so the tests pass"
```
The Architect reads the repo and plans the minimal change plus a verify command, the Implementer makes
minimal search/replace edits, and the oracle **applies the change to a copy and runs the verification in
a container**. It ships a verified git diff. For web UIs it also renders the page in a headless browser
and the **vision model reviews the screenshot** to catch visual facades (missing controls, broken layout,
nothing rendered) that DOM tests cannot.

## Results

All numbers are reproducible; the loop **never sees the hidden scoring tests** (only its own blind
Adversary oracle does). Full methodology and run logs are in [`RESULTS.md`](RESULTS.md).

- **Hard recent LeetCode (rigorous, 3 seeds):** 39.2% -> **52.5%** pass@1, **+13.3 points**. The slice is
  40 Medium/Hard problems dated Feb-Mar 2025 (after model cutoffs, low contamination). Clean separation:
  Crucible's worst seed (48%) beats vanilla's best (42%).
- **Building real runnable products:** vanilla **0/4** -> Crucible **4/4**, every service **boot-verified
  in a `--network none` Docker container** against a blind HTTP integration test.
- **SWE-bench Lite (official harness):** Crucible **resolves real instances** end-to-end (e.g.
  `pallets__flask-4045`), running the verify-first loop inside each instance's real `/testbed`.
- **Vision QA catches visual facades:** the vision model correctly caught a missing input by looking at
  the rendered page, then passed the completed UI.

Crucible's failures are loud and rare; vanilla's are silent and confident. That contrast is the point.

## System requirements

- **Python 3.12**
- **Docker** for the execution sandbox (`docker info` reachable). A hardened local backend exists for
  hosts without a daemon, but `--network none` isolation is real only under Docker.
- **~4 GB RAM free** (candidate subprocesses are memory-capped, default 2 GB each).
- **A Cerebras API key with Gemma 4 31B access** (required).
- **A Google AI Studio key** for the same model (optional; used only for the vanilla speed race).

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then open .env and fill in your keys
cd frontend && npm install && npm run build && cd ..
```

## Run

```bash
# one-command judge/demo path
./run_studio.sh                       # -> http://127.0.0.1:8001
```
Then open **http://127.0.0.1:8001**.

In the UI, type a prompt and watch live: vanilla Gemma streams fast-but-unverified code on the LEFT; on
the RIGHT the pipeline lights up, the gauntlet stages flip green/red, a counterexample card appears with
the Hypothesis-shrunk minimal input, the Surgeon patches it, and the gauntlet goes green. Only verified
code reaches the deliverable. A live tokens/sec readout (from Cerebras `time_info`) runs the whole time.

See [`JUDGE_QUICKSTART.md`](JUDGE_QUICKSTART.md) for the short clone-to-demo instructions.

## Architecture

See [`SPEC.md`](SPEC.md) for the full spec.

| Path | What |
|---|---|
| `crucible/shared/schemas.py` | the seam - every pydantic model, drives strict json_schema |
| `crucible/agents/` | Cerebras client, the 5 roles, verbatim prompts |
| `crucible/oracle/` | `gauntlet.py`, `sandbox.py`, stages, program builders |
| `crucible/orchestrator/` | state machine, budget, events, console |
| `crucible/bench/` | `vanilla_baseline.py`, benchmarks, curated problems |
| `crucible/ui/` | FastAPI SSE server + the split-screen frontend |

### Hard guarantees baked in
- **Output is gated.** Nothing ships unless the gauntlet is all-green, or a clearly-labeled graceful floor
  (best partial + the exact stage it could not verify).
- **Budget is hard.** 60k tokens / 8 iterations / 90s, charged from real usage - the loop cannot run away.
- **Timeout = fail, never hang.** Every sandbox subprocess has a hard kill (process-group SIGKILL).
- **Determinism.** `PYTHONHASHSEED=0`, Hypothesis `derandomize=True`, fixed fuzz space.
- **Tamper-proof verdicts.** The verdict line is tagged with a secret per-run nonce so candidate code
  cannot forge a passing result.
