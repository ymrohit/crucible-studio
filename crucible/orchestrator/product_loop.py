"""Product-mode orchestrator: propose a multi-file FastAPI service, BUILD+BOOT+TEST it in a
container, repair from the real failure output, and deliver only a service that actually runs and
passes the blind Adversary's integration tests (or a clearly-labeled floor).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Optional

from ..agents.product import (
    product_adversary, product_arbiter, product_architect, product_architect_revise,
    product_implementer, product_surgeon, render_files,
)
from ..agents.runtime import AgentContext
from ..oracle.product_runtime import ProductRunResult, build_and_test
from ..shared.product_schemas import ProductCandidate, ProductOracle, ProductSpec
from .budget import Budget
from .events import Sink


@dataclass
class ProductResult:
    status: str                       # "verified" | "floor" | "error"
    candidate: Optional[ProductCandidate]
    spec: Optional[ProductSpec] = None
    oracle: Optional[ProductOracle] = None
    last_result: Optional[ProductRunResult] = None
    budget: Optional[dict] = None
    error: Optional[str] = None


def _parse_check(candidate: ProductCandidate) -> Optional[str]:
    for f in candidate.files:
        if f.path.endswith(".py"):
            try:
                ast.parse(f.content)
            except SyntaxError as e:
                return f"SyntaxError in {f.path}: {e.msg} at line {e.lineno}"
    return None


def _score(r: ProductRunResult) -> int:
    return 2 if r.passed else (1 if r.booted else 0)


def product_run(
    prompt: str,
    *,
    sink: Optional[Sink] = None,
    budget: Optional[Budget] = None,
    timeout: float = 75.0,
) -> ProductResult:
    ctx = AgentContext.create(
        sink=sink, budget=budget or Budget(max_tokens=200_000, max_iters=8, max_seconds=360)
    )
    emitter = ctx.emitter
    emitter.run_start(prompt)
    spec = oracle = None
    try:
        spec = product_architect(prompt, ctx)
        oracle = product_adversary(spec, ctx)          # blind: spec only
        try:
            ast.parse(oracle.integration_test)
        except SyntaxError:
            emitter.note("integration test didn't compile — regenerating it")
            oracle = product_adversary(spec, ctx)
        emitter.note(f"adversary integration test: attacks {', '.join(oracle.boundary_notes[:4])}"
                     + (" …" if len(oracle.boundary_notes) > 4 else ""))
        candidate = product_implementer(spec, ctx)     # blind: no tests

        best: Optional[tuple[ProductCandidate, ProductRunResult]] = None
        fails = 0
        while not ctx.budget.exhausted():
            ctx.budget.tick()
            emitter.iteration(ctx.budget.iters)

            syn = _parse_check(candidate)
            if syn:
                emitter.emit({"type": "stage_result",
                              "result": {"stage": "parse", "status": "fail", "detail": syn}})
                candidate = product_surgeon(candidate, syn, ctx)
                continue

            emitter.stage_start("build+boot+test")
            result = build_and_test(candidate.files, oracle.integration_test, timeout=timeout)
            boot = "booted" if result.booted else "FAILED TO BOOT"
            emitter.emit({"type": "stage_result", "result": {
                "stage": "build+boot+test",
                "status": "pass" if result.passed else "fail",
                "detail": f"{boot}; integration test "
                          f"{'passed' if result.passed else 'failed'} ({result.duration:.1f}s)"}})
            if best is None or _score(result) > _score(best[1]):
                best = (candidate, result)

            if result.passed:
                emitter.candidate_delivered(render_files(candidate))
                emitter.run_done("verified", render_files(candidate), "service boots and passes integration tests")
                return ProductResult("verified", candidate, spec, oracle, result, ctx.budget.snapshot())

            fails += 1
            # stuck on the same failing service twice → Arbiter rules whose fault it is
            if fails >= 2:
                verdict = product_arbiter(spec, candidate, result.output, oracle.integration_test, ctx)
                if verdict.verdict == "bad_test":
                    g = f"{verdict.reasoning} Do NOT assert: {verdict.offending_test or verdict.recommended_action}"
                    oracle = product_adversary(spec, ctx, guidance=g)
                    try:
                        ast.parse(oracle.integration_test)
                    except SyntaxError:
                        oracle = product_adversary(spec, ctx, guidance=g)
                    fails = 0
                    continue
                if verdict.verdict == "underspecified":
                    spec = product_architect_revise(spec, verdict, ctx)
                    oracle = product_adversary(spec, ctx)
                    fails = 0
                    continue
                # code_bug → repair with the arbiter's guidance appended
                candidate = product_surgeon(
                    candidate, result.output + "\n\nARBITER RULING (code_bug): " + verdict.recommended_action, ctx)
                continue

            candidate = product_surgeon(candidate, result.output, ctx)

        # graceful floor
        bc, br = best if best else (candidate, None)
        emitter.floor_reached(render_files(bc),
                              "integration test (best partial: " +
                              ("booted but failing" if br and br.booted else "did not boot") + ")")
        emitter.run_done("floor", render_files(bc), f"budget exhausted: {ctx.budget.reason()}")
        return ProductResult("floor", bc, spec, oracle, br, ctx.budget.snapshot())

    except Exception as e:
        emitter.run_error(f"{type(e).__name__}: {e}")
        return ProductResult("error", None, spec, oracle, None, ctx.budget.snapshot(), str(e))
