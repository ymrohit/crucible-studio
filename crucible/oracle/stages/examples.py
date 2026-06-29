"""Stage 4 — frozen example tests from the Adversary (concrete input→expected pairs)."""

from __future__ import annotations

from ...shared.schemas import StageResult
from .. import harness
from . import StageContext, result_from_run


def run(ctx: StageContext) -> StageResult:
    examples = [
        {
            "input_repr": t.input_repr,
            "expected_repr": t.expected_repr,
            "boundary_category": t.boundary_category,
        }
        for t in ctx.oracle.example_tests
    ]
    if not examples:
        return StageResult(stage="examples", status="pass", detail="no example tests provided")

    program = harness.examples_program(ctx.candidate_code, ctx.function_name, examples)
    run_res = ctx.sandbox.run_python(program, timeout=ctx.timeout)
    parsed = harness.parse_result(run_res.stdout, run_res.nonce)
    return result_from_run("examples", run_res, parsed)
