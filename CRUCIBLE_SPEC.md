# Crucible — Build Spec

**Crucible: an AI coding agent that refuses to ship broken code.** It separates the model into roles that cannot collude — one writes the spec, a blind adversary writes the tests, one implements, a surgeon repairs from counterexamples, an arbiter decides whether a failure is the code's fault or the test's. An executable oracle gates the output: the user only ever receives code that survived the gauntlet. Cerebras speed makes the whole propose→test→repair→verify loop feel live instead of overnight.

Slogan: *"Vanilla AI gives you code that looks right. Crucible gives you code that fought back and survived."*

Platform: Gemma 4 31B on Cerebras (model id `gemma-4-31b`, OpenAI-compatible Chat Completions, strict structured outputs, `time_info` per response, 100 RPM / 100K TPM, 65K MSL / 32K MCL).

---

## 1. The claim (read this before building anything)

The system does **not** claim 100% pass rate. A 31B model will miss some hard problems even with the loop. The claim is **calibration**: when Crucible says *done*, it is provably done because the oracle passed; when it can't solve something, it says exactly what it couldn't verify instead of shipping silent garbage. Vanilla Gemma's failures are silent and confident. Crucible's are loud and rare. **That contrast is the demo.** Do not let anyone soften this into "it always nails it" — that's the one overclaim that gets you caught by a judge who reads the code.

---

## 2. Architecture

Five LLM roles, each a separate call with its own system prompt and its own slice of context. They run **sequentially** (one Cerebras stream is all the TPM affords — fine, because propose→verify→repair is inherently sequential). A **deterministic Python orchestrator** — not an LLM — owns all control flow, so the control logic can never hallucinate.

```
            ┌─────────────┐
 prompt ───▶│  Architect  │── frozen spec ──┐
            └─────────────┘                 │
                                            ▼
            ┌─────────────┐         ┌─────────────────┐
   spec ───▶│  Adversary  │── oracle│  (spec ONLY —   │
            │  (blind)    │         │   never code)   │
            └─────────────┘         └─────────────────┘
                                            │
            ┌─────────────┐                 │
   spec ───▶│ Implementer │── candidate ────┤  (code ONLY —
            │  (blind)    │                 │   never oracle)
            └─────────────┘                 ▼
                                    ┌─────────────────┐
                                    │  ORACLE GAUNTLET│  (deterministic, fail-fast)
                                    │  AST→types→smoke│
                                    │  →examples→props│
                                    │  →differential  │
                                    └────────┬────────┘
                                             │
                         green ──────────────┼────────── red
                           │                 │            │
                           ▼                 │            ▼
                      DELIVER          (same stage    ┌──────────┐
                   (verified)          fails twice)──▶│ Arbiter  │
                                             │        └────┬─────┘
                                             ▼             │
                                       ┌──────────┐   code_bug│bad_test│underspec
                                       │ Surgeon  │◀──────────┘
                                       │ (repair) │   (patch oracle / revise spec / repair)
                                       └──────────┘
```

### Roles

| Role | Sees | Produces | Why it matters |
|---|---|---|---|
| **Architect** | the user prompt | frozen spec + explicit decisions on every ambiguity | the contract everyone downstream is bound to |
| **Adversary** | the spec **only** | property tests, boundary examples, differential reference | blind to the code → physically cannot weaken tests to bless a bug (anti-collusion) |
| **Implementer** | the spec | initial code | blind to the oracle → can't game it |
| **Surgeon** | failing code + minimal shrunk counterexample | targeted fix | focused debugging beats generalist per-iteration |
| **Arbiter** | spec + failing code + failing test | verdict: code_bug / bad_test / underspecified | resolves the spec gap bidirectionally; stops infinite loops on a bad oracle |

### Orchestrator (deterministic)

Owns: running the gauntlet, routing failures, the budget governor, the sequential-vs-fanout decision, Arbiter escalation, the graceful floor, and emitting the structured event stream the UI renders.

---

## 3. The oracle gauntlet

Fail-fast, cheap-first. Short-circuit at the first red. Each stage emits a structured `StageResult`; the model **never marks its own homework** — the oracle owns the score.

1. **parse** — AST parse. Syntax valid?
2. **typecheck** — `pyright` (subprocess). Type-clean against the signature?
3. **smoke** — imports and runs on a trivial input without crashing (sandbox).
4. **examples** — frozen example tests from the Adversary.
5. **properties** — Hypothesis invariants. On failure, Hypothesis **shrinks** to a minimal counterexample → that minimal input is the Surgeon's feedback.
6. **differential** — candidate vs the Adversary's slow-but-obviously-correct reference over fuzzed inputs, `allclose`/equality. *Only runs when an independent, structurally-different correct reference exists* (e.g. O(n²) brute vs O(n) target). For stateful/time-based problems (rate limiter), this stage is skipped and properties carry the load.

**The counterexample is the secret sauce.** Feed back *"returns X for input Y, expected Z, failed at stage S"*, not *"tests failed"*. Repair success per iteration jumps and it's dramatic on screen.

### Verify the verifier (optional credibility slide)

Mutation testing: inject K bug classes into a gold solution, measure what fraction the gauntlet kills. 95%+ = a real bound on verifier strength. On screen: **"Verifier strength: 96%."** Converts trust into a number. Build only if time allows; not in the live loop.

---

## 4. Output gating & graceful floor

- The **deliverable pane shows only verified artifacts.** Every failure happens invisibly inside the loop. That's "we only see the wins" — the thing the user takes away is clean, every time.
- The **verification churn lives in a side panel** — stages flipping red→red→green, the shrinking counterexample, live tok/s from `time_info`. Hide failures from the *deliverable*, flaunt them in the *process view*.
- **Graceful floor** when the budget is exhausted before green: return the best partial, labeled with exactly which property it couldn't verify. Still a win — it's the only system honest enough to know what it didn't prove.

---

## 5. Repo layout

```
crucible/
  shared/
    schemas.py            # pydantic models — THE SEAM between the two builders
  agents/
    base.py               # Cerebras client + strict structured-output helper
    architect.py
    adversary.py
    implementer.py
    surgeon.py
    arbiter.py
    prompts/
      architect.txt       # full text in §8 of this spec
      adversary.txt
      implementer.txt
      surgeon.txt
      arbiter.txt
  oracle/
    gauntlet.py           # runs stages in order, short-circuits, emits StageResult
    sandbox.py            # persistent container + fresh subprocess per candidate
    stages/
      parse.py
      typecheck.py        # pyright subprocess
      smoke.py
      examples.py
      properties.py       # Hypothesis runner + counterexample shrink
      differential.py     # candidate vs reference over fuzzed inputs
  orchestrator/
    state_machine.py      # the loop in §7
    budget.py             # token / iteration / wall-clock governor
    events.py             # structured events emitted to UI
  bench/
    problems/             # curated demo problems + offline LCB-style set
    run_offline.py        # the small 30–50 problem delta run
    vanilla_baseline.py   # single-shot Gemma for comparison
  ui/
    server.py             # FastAPI: SSE event stream + REST
    static/index.html     # split-screen frontend
    static/app.js
    static/style.css
  docker/sandbox.Dockerfile
  requirements.txt
  .env.example            # CEREBRAS_API_KEY
  SPEC.md                 # this file
```

---

## 6. Schemas (the seam — agree these in hour 1)

```python
# shared/schemas.py
from pydantic import BaseModel
from typing import Literal, Optional

class ExplicitDecision(BaseModel):
    ambiguity: str
    decision: str

class Spec(BaseModel):
    function_name: str
    signature: str                       # full def line with type hints
    description: str
    input_constraints: list[str]
    output_constraints: list[str]
    explicit_decisions: list[ExplicitDecision]
    acceptance_criteria: list[str]
    illustrative_examples: list[dict]    # {"input":..,"output":..} — NOT the test suite

class ExampleTest(BaseModel):
    input_repr: str                      # python literal as string
    expected_repr: str
    boundary_category: str

class PropertyTest(BaseModel):
    name: str
    strategy: str                        # Hypothesis strategy source, e.g. "lists(tuples(integers(),integers()))"
    code: str                            # runnable test body referencing `candidate`

class Oracle(BaseModel):
    boundary_categories: list[str]
    example_tests: list[ExampleTest]
    property_tests: list[PropertyTest]
    differential_reference: Optional[str]  # runnable slow-correct impl, or None

class Candidate(BaseModel):
    code: str
    reasoning: str

class Counterexample(BaseModel):
    input_repr: str
    actual_repr: str
    expected_repr: str
    failing_stage: str

class StageResult(BaseModel):
    stage: Literal["parse","typecheck","smoke","examples","properties","differential"]
    status: Literal["pass","fail","error"]
    detail: str
    counterexample: Optional[Counterexample] = None

class ArbiterVerdict(BaseModel):
    verdict: Literal["code_bug","bad_test","underspecified"]
    reasoning: str
    recommended_action: str
    offending_test: Optional[str] = None
```

Event types emitted over SSE: `agent_start{role}`, `agent_token{role,text}`, `agent_done{role,summary}`, `stage_start{stage}`, `stage_result{StageResult}`, `arbiter_verdict{ArbiterVerdict}`, `candidate_delivered{code}`, `floor_reached{code,unverified_property}`, `metrics{tokens_used,tokens_per_sec,ttft}`.

---

## 7. Orchestrator state machine

```python
def run(prompt: str) -> Result:
    budget = Budget(max_tokens=60_000, max_iters=8, max_seconds=90)

    spec      = architect(prompt, budget)            # → Spec
    oracle    = adversary(spec, budget)              # blind: spec only → Oracle
    candidate = implementer(spec, budget)            # blind: no oracle → Candidate

    fail_counts = defaultdict(int)
    best = None

    while not budget.exhausted():
        result = gauntlet.run(candidate, oracle)     # emits stage events, short-circuits
        best = track_best(best, candidate, result)

        if result.all_pass:
            emit("candidate_delivered", candidate.code)
            return Verified(candidate)

        stage = result.first_failure.stage
        fail_counts[stage] += 1

        # escalate to Arbiter when stuck on the SAME stage
        if fail_counts[stage] >= 2:
            verdict = arbiter(spec, candidate, result.first_failure, budget)
            if verdict.verdict == "bad_test":
                oracle = patch_oracle(oracle, verdict)        # regen offending test, audited
                fail_counts[stage] = 0
                continue
            if verdict.verdict == "underspecified":
                spec   = architect_revise(spec, verdict, budget)
                oracle = adversary(spec, budget)              # rebuild oracle from new spec
                fail_counts.clear()
                continue
            # code_bug → repair, and fan out because we're stuck
            candidates = [surgeon(candidate, result.counterexample, budget)
                          for _ in range(3)]                  # k=3 ONLY when stalled
            candidate = best_by_gauntlet(candidates, oracle)
            continue

        # first failure on this stage → plain sequential repair
        candidate = surgeon(candidate, result.counterexample, budget)

    # budget exhausted → graceful floor
    emit("floor_reached", best.code, unverified=best.first_unpassed_stage)
    return Floor(best)
```

Rules baked in: sequential by default; **fan out (k=3) only when stalled**, never lead with best-of-N (it multiplies tokens); the budget governor hard-caps tokens/iters/wall so it physically cannot run away and brick the rate limit.

---

## 8. The five system prompts

Store each as `agents/prompts/<role>.txt`. All agents use strict JSON structured output matching the schema in §6.

### architect.txt
```
You convert an informal coding request into a precise, FROZEN specification that every
other agent is bound to. You are the contract.

Your most important job: resolve EVERY ambiguity explicitly. Real requests are vague about
edge cases — empty input, singletons, duplicates, ties, boundary values, ordering,
overflow, unicode/whitespace, malformed input. For each one that applies, MAKE A DECISION
and state it in explicit_decisions. Downstream agents must never have to guess; if they
guess differently from each other, the loop thrashes.

Pick the simplest signature that satisfies the request. illustrative_examples are to
communicate intent — they are NOT the test suite and must not be relied on for coverage.

Output ONLY valid JSON matching the Spec schema. No prose outside the JSON.
```

### adversary.txt
```
You are a hostile QA engineer. Your goal is to write tests that EXPOSE bugs in an
implementation you will NEVER see. You see only the specification.

Because you cannot read the code, you cannot target specific lines — target the SPEC's
dangerous regions instead: boundaries, empty/singleton/duplicate inputs, ordering and
ties, off-by-one, overflow, and especially every item in the spec's explicit_decisions
(those are where a competent implementer is most likely to diverge).

Produce three kinds of checks:
1. example_tests: concrete input→expected pairs derived strictly from the spec, each
   tagged with the boundary_category it attacks.
2. property_tests: invariants that must hold for ALL inputs, as runnable Hypothesis tests.
   Examples of invariants: output is a permutation of input; result is sorted/monotonic;
   decode(encode(x)) == x; totals are conserved; idempotence; no negative/illegal values.
   Reference the candidate as `candidate`.
3. differential_reference: a SLOW but OBVIOUSLY-CORRECT reference implementation to diff
   against over fuzzed inputs. Prefer brute-force clarity (O(n^2)) over cleverness — it
   must be trivially, independently correct. Provide it ONLY when such a reference exists
   AND is structurally different from the expected efficient solution. If the problem is
   stateful or time-based (e.g. a rate limiter) and no clean reference exists, set it to
   null and lean on properties.

Never weaken a test to be "safe". Your job is to break things. Output ONLY valid JSON
matching the Oracle schema.
```

### implementer.txt
```
You implement the specification. You see the spec only — you will NOT see the test suite,
so do not try to guess or game it. Write correct, reasonably efficient code that satisfies
every acceptance_criterion and respects every explicit_decision exactly.

Match the given signature precisely. Output ONLY valid JSON matching the Candidate schema:
the full function code, plus one or two sentences of reasoning.
```

### surgeon.txt
```
You are a debugger making the SMALLEST change that fixes one specific failure.

You are given: the current failing code, and a MINIMAL counterexample — a specific input,
the actual output, the expected output, and which oracle stage failed. Diagnose why this
exact input produces the wrong result, then fix it without breaking anything that already
passed. Do not refactor for style. Do not broaden scope. One precise fix.

Output ONLY valid JSON matching the Candidate schema: the full corrected code, plus a
diff_explanation in the reasoning field stating what you changed and why it resolves this
counterexample.
```

### arbiter.txt
```
You are a senior engineer adjudicating a dispute. An implementation keeps failing the same
test, and the loop cannot tell whose fault it is. You must rule.

You see: the spec, the current code, the failing test, and the counterexample. Decide:
- code_bug: the spec is clear, the test correctly encodes it, the code is wrong.
- bad_test: the test asserts something the spec does NOT require (or contradicts an
  explicit_decision). Name the offending test and explain the contradiction.
- underspecified: the spec genuinely does not determine the answer for this input. State
  exactly what decision the spec must add.

Reason explicitly about what the spec REQUIRES vs what the test ASSERTS vs what the code
DOES. Output ONLY valid JSON matching the ArbiterVerdict schema.
```

---

## 9. Cerebras client notes (`agents/base.py`)

- OpenAI-compatible Chat Completions; `model="gemma-4-31b"`; base URL = Cerebras endpoint; `CEREBRAS_API_KEY` from env.
- **Strict structured output** per agent: pass the pydantic schema as `response_format` json_schema with `strict: true`. Validate the response into the schema; on validation failure, one cheap retry with the validation error appended, then surface.
- `reasoning_effort`: **off** for Implementer and Surgeon (speed). **low/medium** for Architect and Arbiter (judgment-heavy). Reasoning adds tokens and latency — that's the tradeoff.
- Capture `usage` (prompt/completion/total) and `time_info` from every response; forward to `metrics` events and to the Budget governor.
- Image input (base64 data URI) is **not** needed for v1. Optional Track-1 booster: let the Architect accept a screenshot (failing tests / a behavior diagram) as an extra content block — wire only if there's spare time.

---

## 10. Sandbox (`oracle/sandbox.py`)

For a 24h demo, **persistent container + fresh subprocess per candidate** is the pragmatic choice (docker-per-candidate is the "correct" production answer but adds ~1–2s startup you don't have).

- One long-lived container: `python:3.12-slim` + `pyright` + `hypothesis`. `--network none`, memory limit, read-only except `/tmp`.
- Each candidate runs in a fresh subprocess inside it with a **hard timeout → kill → treat as fail (never hang)**.
- Seed everything: `PYTHONHASHSEED=0`, fixed Hypothesis seed/`derandomize`, fixed fuzz seed for differential. The demo and the backups must be reproducible.

---

## 11. Demo problems + pre-vetting protocol

Pick problems where vanilla Gemma **reliably misses an edge** AND a **property or differential stage** (not just example test #4) does the catching — so the Adversary looks genuinely smart and the hard-to-fake stages are visibly what catch the bug.

Candidate pool (all have clean invariants):
- **Sliding-window rate limiter** — off-by-one at the window edge; behavior at exactly-N. Property: never more than N in any window.
- **Topological sort + cycle detection** — must report a cycle, not silently return a partial order. Property: output respects all edges; cycles detected. Differential vs Kahn's.
- **Inventory/interval allocation** — conservation: total allocated == min(demand, supply); no negatives. Property-based.
- **Unicode/whitespace normalization** — NFC/NFKC, zero-width chars, combining marks. Differential vs a `unicodedata` reference.
- **Pagination** — last page / empty set / page beyond range / off-by-one on total_pages. Property: pages partition the set exactly, no overlap or gap.

**Pre-vetting (do this before recording — the live demo is stochastic and this is the real risk):**
1. Run **vanilla Gemma single-shot 20×** (temp ~0.7) on each candidate. Keep problems where vanilla fails the target edge **≥60%** of the time (reliable faceplant).
2. Run the **full Crucible loop 20×** on each survivor. Keep problems where the Adversary generates the catching test **≥80%** of the time AND the loop converges to green **≥90%**.
3. Rank by *visual clarity of the catch* — bug explainable in one sentence, caught by a property/differential.
4. Pick the **top 1 as the live demo; freeze 2–3 as backups** with pinned model/temp/seed.

**Hard line:** curating the *demo problem* is fine showmanship. Curating the *benchmark slice* is fraud. Never blur the two.

---

## 12. Offline number (detachable booster — never load-bearing)

A small number beats no number for a judge, but a rushed benchmark is a trap. So timebox a tiny run and keep it detachable.

- Pull **30–50 LiveCodeBench problems with release_date AFTER Gemma 4 31B's cutoff** (contamination provably zero — that's LCB's whole point), medium/hard for headroom.
- **Condition A (vanilla):** single-shot, pass@1 on the hidden tests, record median wall-clock.
- **Condition B (Crucible):** full loop, pass@1 on the **same** hidden tests. **The loop sees only its own Adversary-generated oracle + any LCB public tests — NEVER the hidden scoring tests.** Same scaffold as A; differ only in the loop.
- Report `pass@1 A→B` and `median wall-clock A vs B`.
- Token math: ~40 × ~60K = ~2.4M tokens for Crucible ≈ ~24 min of pure generation, ~1–2h wall with sandbox time. Vanilla is trivial. **Run it offline in the background mid-build.** Lands clean → closing slide. Weak/flaky → drop it; the pitch stands on architecture + the live catch.
- Precedent to cite regardless: Meta's CWM (open weights) lifted SWE-bench Verified ~53.9% → ~65.8% with exactly this propose-plus-generated-tests scaling. You're making a published result *live*.

SWE-bench Verified is a **showcase, not the live benchmark** — use one real GitHub-issue task as a flex if time allows (it ships its own hidden FAIL_TO_PASS/PASS_TO_PASS oracle; the loop must not see those). Don't build the full SWE-bench harness in 24h.

---

## 13. The 60-second storyboard (timed to ~20s of real churn)

The full 5-role loop with ~3 repair cycles is ~8–10 sequential calls plus sandbox runs — realistically **~15–25s end to end**, not 3. Build around ~20s of visible verification; lightly speed the video (1.2–1.5×, standard and honest) if needed. Say *"while you watch,"* never *"instant."* UK→US RTT is ~1s total across the task — don't bother relocating to US-cloud; generation + sandbox is the cost.

| Time | Screen |
|---|---|
| 0:00–0:05 | Hook card: *"Vanilla AI gives you code that looks right. Crucible gives you code that fought back and survived."* |
| 0:05–0:08 | User types the prompt. Split screen: **LEFT = Vanilla Gemma**, **RIGHT = Crucible**. |
| 0:08–0:11 | LEFT: vanilla emits code fast. Looks clean. (Subtly wrong.) |
| 0:11–0:30 | RIGHT: pipeline lights up. Architect (spec card flashes the explicit_decision). Adversary (boundary categories enumerate, a property appears). Implementer (code streams). Gauntlet: AST ✅ Types ✅ Examples ✅ → **Property ❌** + counterexample card (input → got → expected). Surgeon: one-line diff. Re-run: ✅✅✅✅✅✅. tok/s counter spinning throughout. |
| 0:30–0:40 | Punchline: feed BOTH solutions the counterexample. LEFT returns wrong. RIGHT correct. Caption: *"The model was wrong. Crucible caught it before the user did."* |
| 0:40–0:50 | Deliverable pane: Crucible ships ONLY the verified code. Optional "Verifier strength: 96%" badge + the offline delta bar if it landed. |
| 0:50–0:60 | Close: name + slogan + *"Powered by Gemma 4 31B on Cerebras"* + the tok/s number as the speed flex. |

Track fit: strongest for **Track 2** (visceral/viral) and **Track 3** (enterprise = code reliability). For **Track 1** (needs multimodal), add the screenshot-input adapter from §9 if time allows.

---

## 14. Two-person split

Agree the **schemas (§6) and event types** in hour 1, then build in parallel against that seam.

**Person A — Loop / backend**
- `agents/base.py` (Cerebras client + strict structured output)
- the 5 agents + prompt files
- `orchestrator/` (state machine, budget, events)
- `bench/run_offline.py` + `vanilla_baseline.py` — **owns the offline number**

**Person B — Oracle / frontend**
- `oracle/gauntlet.py` + all `stages/` + `sandbox.py`
- Hypothesis property runner + counterexample shrink + differential
- `ui/` (SSE server + the split-screen frontend) — **owns the demo video**
- `bench/problems/` curation + the pre-vetting runs

---

## 15. Hour-by-hour (rough, 24h)

| Hours | Person A | Person B |
|---|---|---|
| 0–1 | agree schemas + events, scaffold repo | (same) |
| 1–4 | Cerebras client + Architect + Implementer (prompt→spec→code) | gauntlet skeleton + sandbox + parse/typecheck/smoke |
| 4–8 | Adversary + Surgeon + orchestrator loop | examples + properties (Hypothesis) + differential + shrink |
| 8–10 | integrate → first full green loop on one easy problem | (same) |
| 10–13 | Arbiter + budget + floor + offline runner | SSE event stream + basic UI |
| 13–16 | kick off offline benchmark in background | curate + pre-vet demo problems (vanilla 20×) |
| 16–20 | tune prompts so the catch is reliable on the chosen problem | build the split-screen visceral UI |
| 20–22 | check offline number, prep slide if clean | record demo video (multiple takes) |
| 22–24 | buffer / polish / write Discord post + submission | backup takes |

---

## 16. Risks & mitigations

- **Live demo is stochastic** (needs vanilla to miss AND the blind Adversary to catch) → pre-vet 20×, structured Adversary that enumerates boundary categories, 2–3 frozen backups.
- **Offline number flaky** → detachable; drop it, pitch stands.
- **Sandbox too slow** → persistent container + fresh subprocess.
- **Rate limit** → budget governor, sequential default, offline run timeboxed.
- **Reasoning-mode token blowup** → reasoning off/low except Architect/Arbiter.
- **Demo looks like scrolling logs** → the split-screen + counterexample card + the "caught it before the user did" beat is the antidote. The hook is the catch, not the harness.
```
