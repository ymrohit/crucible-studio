"""The deterministic orchestrator (§7). Owns ALL control flow — no LLM decides routing.

Sequential repair by default; escalate to the Arbiter when the SAME stage fails twice; on
bad_test patch the oracle, on underspecified revise the spec + rebuild the oracle, on
code_bug fan out k=3 (only when stalled) and keep the best by gauntlet; graceful floor on
budget exhaustion. Output is gated: nothing is returned as 'verified' unless the gauntlet is
all-green; otherwise a clearly-labeled floor.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional

from ..agents.adversary import adversary
from ..agents.arbiter import arbiter
from ..agents.architect import architect, architect_revise
from ..agents.implementer import implementer
from ..agents.runtime import AgentContext
from ..agents.surgeon import surgeon
from ..oracle import gauntlet, harness
from ..oracle.gauntlet import GauntletResult
from ..oracle.sandbox import Sandbox, get_sandbox
from ..shared.schemas import ArbiterVerdict, Candidate, Counterexample, Oracle, Spec
from .budget import Budget
from .events import Sink


@dataclass
class RunResult:
    status: str  # "verified" | "floor" | "error"
    code: str
    spec: Optional[Spec] = None
    oracle: Optional[Oracle] = None
    candidate: Optional[Candidate] = None
    last_result: Optional[GauntletResult] = None
    unverified_stage: Optional[str] = None
    budget: Optional[dict] = None
    error: Optional[str] = None


@dataclass
class _Best:
    candidate: Candidate
    result: GauntletResult


def track_best(best: Optional[_Best], candidate: Candidate, result: GauntletResult) -> _Best:
    if best is None or result.passed_count > best.result.passed_count:
        return _Best(candidate, result)
    return best


def counterexample_for(failure) -> Counterexample:
    """The Surgeon always wants a counterexample; synthesize one for stage-level failures
    (parse/typecheck/smoke) that don't carry an input."""
    if failure.counterexample:
        return failure.counterexample
    return Counterexample(
        input_repr="(no specific input — stage-level failure)",
        actual_repr=failure.detail,
        expected_repr=f"stage '{failure.stage}' to pass",
        failing_stage=failure.stage,
    )


def patch_oracle(oracle: Oracle, failure, verdict: ArbiterVerdict, ctx: AgentContext) -> Oracle:
    """bad_test → remove the offending test the Arbiter ruled invalid (audited)."""
    new = oracle.model_copy(deep=True)
    stage = failure.stage
    removed = "unknown"
    if stage == "properties":
        name = None
        m = re.search(r"property '([^']+)'", failure.detail)
        if m:
            name = m.group(1)
        elif verdict.offending_test:
            name = verdict.offending_test
        before = len(new.property_tests)
        new.property_tests = [p for p in new.property_tests if p.name != name]
        if len(new.property_tests) == before and new.property_tests:
            # name didn't match; drop the first as a fallback so we don't loop forever.
            removed = new.property_tests[0].name
            new.property_tests = new.property_tests[1:]
        else:
            removed = f"property '{name}'"
    elif stage == "examples" and failure.counterexample:
        ci = failure.counterexample.input_repr
        new.example_tests = [t for t in new.example_tests if t.input_repr != ci]
        removed = f"example {ci}"
    elif stage == "differential":
        new.differential_reference = None
        removed = "differential reference"
    ctx.emitter.note(f"oracle patched (bad_test): removed {removed}")
    return new


def sanitize_oracle(oracle: Oracle, sandbox: Sandbox, ctx: AgentContext) -> Oracle:
    """Drop tests that are themselves broken (invalid Hypothesis strategy, uncompilable
    property body, uneval-able expected, broken reference) BEFORE the loop runs, so the
    Surgeon never wastes iterations trying to 'fix' code against a malformed test."""
    props = [{"name": p.name, "strategy": p.strategy, "code": p.code} for p in oracle.property_tests]
    exps = [t.expected_repr for t in oracle.example_tests]
    program = harness.oracle_lint_program(props, exps, oracle.differential_reference)
    res = sandbox.run_python(program, timeout=15.0)
    parsed = harness.parse_result(res.stdout, res.nonce)
    if not parsed or parsed.get("status") != "pass":
        return oracle  # lint itself failed — let the loop's arbiter handle bad tests

    new = oracle.model_copy(deep=True)
    bad_props = set(parsed.get("bad_properties", []))
    bad_ex = set(parsed.get("bad_examples", []))
    if bad_props:
        new.property_tests = [p for p in new.property_tests if p.name not in bad_props]
        ctx.emitter.note(f"oracle lint: dropped {len(bad_props)} malformed property test(s)")
    if bad_ex:
        new.example_tests = [t for i, t in enumerate(new.example_tests) if i not in bad_ex]
        ctx.emitter.note(f"oracle lint: dropped {len(bad_ex)} malformed example test(s)")
    if parsed.get("bad_reference"):
        new.differential_reference = None
        ctx.emitter.note("oracle lint: dropped malformed differential reference")
    return new


def best_by_gauntlet(
    candidates: list[Optional[Candidate]], eval_fn: Callable[[Candidate], GauntletResult]
) -> Candidate:
    """k=3 fan-out selection: keep the candidate that gets furthest through the gauntlet."""
    real = [c for c in candidates if c is not None]
    best: Optional[_Best] = None
    for c in real:
        r = eval_fn(c)
        best = track_best(best, c, r)
        if r.all_pass:
            break
    return best.candidate if best else real[0]


def run(
    prompt: str,
    *,
    sink: Optional[Sink] = None,
    budget: Optional[Budget] = None,
    sandbox: Optional[Sandbox] = None,
    max_property_examples: int = 100,
    max_differential_examples: int = 200,
    stage_timeout: float = 20.0,
    inject_spec: Optional[Spec] = None,
    inject_oracle: Optional[Oracle] = None,
    inject_candidate: Optional[Candidate] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> RunResult:
    """Run the loop. ``inject_*`` bypass the respective agent — used by tests and frozen
    demo backups to make a specific scenario (e.g. a bad oracle test) reproducible. In the
    production path all three are None and the agents run normally; injection never lets a
    role see a forbidden object, so anti-collusion is preserved.
    """
    ctx = AgentContext.create(sink=sink, budget=budget or Budget())
    emitter = ctx.emitter
    sb = sandbox or get_sandbox()
    emitter.run_start(prompt)

    spec: Optional[Spec] = None
    oracle: Optional[Oracle] = None
    try:
        # --- propose ---------------------------------------------------------
        spec = inject_spec or architect(prompt, ctx)
        if inject_spec is not None:
            emitter.spec_ready(spec.model_dump())
        oracle = inject_oracle or adversary(spec, ctx)        # blind: spec only
        if inject_oracle is not None:
            emitter.oracle_ready(
                oracle.boundary_categories, [p.name for p in oracle.property_tests],
                len(oracle.example_tests),
                bool(oracle.differential_reference and oracle.differential_reference.strip()),
                [t.model_dump() for t in oracle.example_tests],
                [p.model_dump() for p in oracle.property_tests],
                oracle.differential_reference or "",
            )
        oracle = sanitize_oracle(oracle, sb, ctx)             # drop malformed tests upfront
        candidate = inject_candidate or implementer(spec, ctx)   # blind: no oracle
        if inject_candidate is not None:
            emitter.candidate_proposed(candidate.code, candidate.reasoning)

        def visible_gauntlet(cand: Candidate) -> GauntletResult:
            return gauntlet.run(
                cand, oracle, spec, emitter=emitter, sandbox=sb,
                max_property_examples=max_property_examples,
                max_differential_examples=max_differential_examples,
                timeout=stage_timeout,
            )

        def quiet_gauntlet(cand: Candidate) -> GauntletResult:
            return gauntlet.run(
                cand, oracle, spec, emitter=None, sandbox=sb,
                max_property_examples=max_property_examples,
                max_differential_examples=max_differential_examples,
                timeout=stage_timeout,
            )

        fail_counts: dict[str, int] = defaultdict(int)
        best: Optional[_Best] = None

        # --- verify → repair loop -------------------------------------------
        while not ctx.budget.exhausted():
            if should_stop is not None and should_stop():
                emitter.run_error("cancelled (client disconnected)")
                return RunResult("error", "", spec, oracle, candidate, None, None,
                                 ctx.budget.snapshot(), "cancelled")
            ctx.budget.tick()
            emitter.iteration(ctx.budget.iters)

            result = visible_gauntlet(candidate)
            best = track_best(best, candidate, result)

            if result.all_pass:
                emitter.candidate_delivered(candidate.code)
                emitter.run_done("verified", candidate.code, "all gauntlet stages passed")
                return RunResult(
                    "verified", candidate.code, spec, oracle, candidate, result,
                    None, ctx.budget.snapshot(),
                )

            failure = result.first_failure
            assert failure is not None
            stage = failure.stage
            fail_counts[stage] += 1

            # escalate to the Arbiter when stuck on the SAME stage
            if fail_counts[stage] >= 2:
                verdict = arbiter(spec, candidate, failure, oracle, ctx)
                if verdict.verdict == "bad_test":
                    oracle = patch_oracle(oracle, failure, verdict, ctx)
                    fail_counts[stage] = 0
                    continue
                if verdict.verdict == "underspecified":
                    spec = architect_revise(spec, verdict, ctx)
                    oracle = sanitize_oracle(adversary(spec, ctx), sb, ctx)  # rebuild + lint
                    fail_counts.clear()
                    continue
                # code_bug → repair and fan out (k=3) because we're stalled
                ce = counterexample_for(failure)
                emitter.note("stalled — fanning out k=3 repairs, keeping best by gauntlet")
                cands = [surgeon(candidate, ce, ctx) for _ in range(3)]
                candidate = best_by_gauntlet(cands, quiet_gauntlet)
                continue

            # first failure on this stage → plain sequential repair
            candidate = surgeon(candidate, counterexample_for(failure), ctx)

        # --- graceful floor --------------------------------------------------
        if best is None:
            # Budget exhausted during setup, before any gauntlet run — return the raw,
            # explicitly-unverified candidate rather than crashing.
            emitter.floor_reached(candidate.code, "not-run (budget exhausted before verification)")
            emitter.run_done("floor", candidate.code, f"budget exhausted before verifying: {ctx.budget.reason()}")
            return RunResult(
                "floor", candidate.code, spec, oracle, candidate, None,
                "not-run", ctx.budget.snapshot(),
            )
        emitter.floor_reached(best.candidate.code, best.result.first_unpassed_stage)
        emitter.run_done("floor", best.candidate.code, f"budget exhausted: {ctx.budget.reason()}")
        return RunResult(
            "floor", best.candidate.code, spec, oracle, best.candidate, best.result,
            best.result.first_unpassed_stage, ctx.budget.snapshot(),
        )

    except Exception as e:  # surface, never hang
        emitter.run_error(f"{type(e).__name__}: {e}")
        return RunResult("error", "", spec, oracle, None, None, None, ctx.budget.snapshot(), str(e))
