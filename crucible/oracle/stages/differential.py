"""Stage 6 — differential. Candidate vs the Adversary's slow-but-obviously-correct reference
over fuzzed inputs, float-tolerant equality. Skipped cleanly when no reference exists
(stateful/time-based problems lean on properties instead, per the spec).
"""

from __future__ import annotations

from ...shared.schemas import StageResult
from .. import harness
from . import StageContext, result_from_run


def _input_strategy(ctx: StageContext) -> str | None:
    """Reuse the property strategies to fuzz the same input domain the reference expects."""
    for prop in ctx.oracle.property_tests:
        if prop.strategy.strip():
            return prop.strategy
    return None


def run(ctx: StageContext) -> StageResult:
    ref = ctx.oracle.differential_reference
    if not ref or not ref.strip():
        return StageResult(
            stage="differential", status="pass", detail="skipped: no differential reference"
        )

    strategy = _input_strategy(ctx)
    if strategy is None:
        return StageResult(
            stage="differential",
            status="pass",
            detail="skipped: reference present but no fuzzing strategy available",
        )

    program = harness.differential_program(
        ctx.candidate_code,
        ctx.function_name,
        ref,
        strategy,
        max_examples=ctx.max_differential_examples,
    )
    run_res = ctx.sandbox.run_python(program, timeout=ctx.timeout)
    parsed = harness.parse_result(run_res.stdout, run_res.nonce)
    return result_from_run("differential", run_res, parsed)
