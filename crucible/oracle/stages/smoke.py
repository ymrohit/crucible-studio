"""Stage 3 — smoke. Does the candidate import and run on one concrete input without crashing?

Uses the first available concrete input (an Adversary example, else a spec illustrative
example). If neither exists it falls back to merely confirming the function is callable.
"""

from __future__ import annotations

from ...shared.schemas import StageResult
from .. import harness
from . import StageContext, result_from_run


def _trivial_input(ctx: StageContext) -> str | None:
    if ctx.oracle.example_tests:
        return ctx.oracle.example_tests[0].input_repr
    if ctx.spec and ctx.spec.illustrative_examples:
        ex = ctx.spec.illustrative_examples[0]
        if isinstance(ex, dict) and "input" in ex:
            return str(ex["input"])
    return None


def run(ctx: StageContext) -> StageResult:
    inp = _trivial_input(ctx)
    if inp is None:
        # No concrete input known — just confirm the function binds and is callable.
        program = (
            harness._COMMON
            + f"\n{ctx.candidate_code}\ncandidate = {ctx.function_name}\n"
            + "_emit({'status':'pass','detail':'function defined and callable'} if callable(candidate) "
            + "else {'status':'fail','detail':'target is not callable'})\n"
        )
    else:
        program = harness.smoke_program(ctx.candidate_code, ctx.function_name, inp)

    run_res = ctx.sandbox.run_python(program, timeout=min(ctx.timeout, 10.0))
    parsed = harness.parse_result(run_res.stdout, run_res.nonce)
    return result_from_run("smoke", run_res, parsed)
