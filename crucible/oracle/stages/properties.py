"""Stage 5 — Hypothesis property tests. On failure, Hypothesis SHRINKS to a minimal input,
which becomes the Surgeon's counterexample. Each property runs in its own sandbox process so
the first violation yields a precise, minimal counterexample.
"""

from __future__ import annotations

from ...shared.schemas import StageResult
from .. import harness
from . import StageContext, result_from_run


def run(ctx: StageContext) -> StageResult:
    props = ctx.oracle.property_tests
    if not props:
        return StageResult(stage="properties", status="pass", detail="no property tests provided")

    passed = 0
    for prop in props:
        program = harness.properties_program(
            ctx.candidate_code,
            ctx.function_name,
            prop.strategy,
            prop.code,
            max_examples=ctx.max_property_examples,
        )
        run_res = ctx.sandbox.run_python(program, timeout=ctx.timeout)
        parsed = harness.parse_result(run_res.stdout, run_res.nonce)
        result = result_from_run("properties", run_res, parsed)

        if result.status != "pass":
            # Annotate with which property failed; keep the shrunk counterexample.
            result.detail = f"property '{prop.name}' — {result.detail}"
            return result
        passed += 1

    return StageResult(
        stage="properties",
        status="pass",
        detail=f"{passed}/{len(props)} properties held",
    )
