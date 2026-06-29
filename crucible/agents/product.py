"""Product-mode agents — the same five-role, non-colluding design scaled to a runnable service.

Anti-collusion holds at the signature level: the Adversary sees the ProductSpec only (never the
files), the Implementer sees the spec only (never the integration test).
"""

from __future__ import annotations

from ..shared.product_schemas import ProductCandidate, ProductOracle, ProductSpec
from ..shared.schemas import ArbiterVerdict
from . import load_prompt
from .runtime import AgentContext, invoke

_ARCHITECT = load_prompt("product_architect")
_IMPLEMENTER = load_prompt("product_implementer")
_ADVERSARY = load_prompt("product_adversary")
_SURGEON = load_prompt("product_surgeon")
_ARBITER = load_prompt("product_arbiter")


def render_product_spec(spec: ProductSpec) -> str:
    lines = [f"name: {spec.name}", f"description: {spec.description}", "endpoints:"]
    for e in spec.endpoints:
        lines.append(f"  - {e.method} {e.path} — {e.behavior}")
    if spec.explicit_decisions:
        lines.append("explicit_decisions (binding):")
        for d in spec.explicit_decisions:
            lines.append(f"  - {d.ambiguity} → {d.decision}")
    if spec.acceptance_criteria:
        lines.append("acceptance_criteria:")
        lines += [f"  - {c}" for c in spec.acceptance_criteria]
    return "\n".join(lines)


def render_files(candidate: ProductCandidate) -> str:
    out = []
    for f in candidate.files:
        out.append(f"### FILE: {f.path}\n```python\n{f.content}\n```")
    return "\n\n".join(out)


def product_architect(prompt: str, ctx: AgentContext) -> ProductSpec:
    user = (
        "Design the frozen API spec for this product. Resolve every ambiguity in "
        "explicit_decisions.\n\nPRODUCT REQUEST:\n" + prompt
    )
    res = invoke(ctx, "architect", _ARCHITECT, user, ProductSpec,
                 reasoning_effort="medium", temperature=0.4, max_completion_tokens=6000)
    spec: ProductSpec = res.parsed  # type: ignore[assignment]
    ctx.emitter.spec_ready(spec.model_dump())
    ctx.emitter.agent_done("architect", f"{spec.name}: {len(spec.endpoints)} endpoints, "
                                         f"{len(spec.explicit_decisions)} decision(s)")
    return spec


def product_adversary(spec: ProductSpec, ctx: AgentContext, guidance: str = "") -> ProductOracle:
    user = (
        "Write an integration test that exposes bugs in a service you will never see. Attack the "
        "spec's dangerous regions and every explicit_decision.\n\nSPEC:\n" + render_product_spec(spec)
    )
    if guidance:
        user += f"\n\nIMPORTANT — a previous test was ruled invalid. {guidance}"
    res = invoke(ctx, "adversary", _ADVERSARY, user, ProductOracle,
                 reasoning_effort="low", temperature=0.6, max_completion_tokens=6000)
    oracle: ProductOracle = res.parsed  # type: ignore[assignment]
    ctx.emitter.agent_done("adversary", f"integration test ({len(oracle.boundary_notes)} attack notes)")
    return oracle


def product_architect_revise(spec: ProductSpec, verdict: ArbiterVerdict, ctx: AgentContext) -> ProductSpec:
    user = (
        "The spec was ruled UNDERSPECIFIED. Revise it so the behavior is fully determined — add the "
        "missing decision (status code, response body shape, etc.) and keep everything else.\n\n"
        f"CURRENT SPEC:\n{render_product_spec(spec)}\n\n"
        f"ARBITER REASONING:\n{verdict.reasoning}\n\nREQUIRED ADDITION:\n{verdict.recommended_action}"
    )
    res = invoke(ctx, "architect", _ARCHITECT, user, ProductSpec,
                 reasoning_effort="medium", temperature=0.4, max_completion_tokens=6000)
    revised: ProductSpec = res.parsed  # type: ignore[assignment]
    ctx.emitter.spec_ready(revised.model_dump())
    ctx.emitter.agent_done("architect", "revised spec")
    return revised


def product_arbiter(
    spec: ProductSpec, candidate: ProductCandidate, failure_output: str,
    integration_test: str, ctx: AgentContext,
) -> ArbiterVerdict:
    user = (
        "An integration check keeps failing. Rule: code_bug, bad_test, or underspecified.\n\n"
        f"SPEC:\n{render_product_spec(spec)}\n\n"
        f"FILES:\n{render_files(candidate)}\n\n"
        f"INTEGRATION TEST:\n{integration_test[:2500]}\n\n"
        f"FAILURE OUTPUT:\n{failure_output[:2000]}"
    )
    res = invoke(ctx, "arbiter", _ARBITER, user, ArbiterVerdict,
                 reasoning_effort="medium", temperature=0.3, max_completion_tokens=4000)
    verdict: ArbiterVerdict = res.parsed  # type: ignore[assignment]
    ctx.emitter.arbiter_verdict(verdict)
    ctx.emitter.agent_done("arbiter", f"verdict: {verdict.verdict}")
    return verdict


def product_implementer(spec: ProductSpec, ctx: AgentContext) -> ProductCandidate:
    user = (
        "Implement this FastAPI service. App must import as main:app. Use only stdlib + fastapi/"
        "pydantic/uvicorn; in-memory state. Honor every explicit_decision and status code.\n\n"
        "SPEC:\n" + render_product_spec(spec)
    )
    res = invoke(ctx, "implementer", _IMPLEMENTER, user, ProductCandidate,
                 reasoning_effort=None, temperature=0.5, max_completion_tokens=6000)
    cand: ProductCandidate = res.parsed  # type: ignore[assignment]
    ctx.emitter.candidate_proposed(render_files(cand), cand.reasoning)
    ctx.emitter.agent_done("implementer", f"{len(cand.files)} file(s) written")
    return cand


def product_surgeon(candidate: ProductCandidate, failure_output: str, ctx: AgentContext) -> ProductCandidate:
    user = (
        "The service failed its integration test. Make the smallest fix across the files.\n\n"
        f"CURRENT FILES:\n{render_files(candidate)}\n\n"
        f"FAILURE OUTPUT (test assertion / server log):\n{failure_output[:2500]}\n\n"
        "Return the FULL corrected set of files."
    )
    res = invoke(ctx, "surgeon", _SURGEON, user, ProductCandidate,
                 reasoning_effort=None, temperature=0.3, max_completion_tokens=6000)
    fixed: ProductCandidate = res.parsed  # type: ignore[assignment]
    ctx.emitter.surgeon_patch(render_files(fixed), fixed.reasoning)
    ctx.emitter.agent_done("surgeon", "applied targeted fix")
    return fixed
