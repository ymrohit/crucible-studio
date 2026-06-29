"""Architect — turns the informal request into a FROZEN spec (§8 architect.txt).

Sees the user prompt only. Uses ``reasoning_effort="medium"`` because resolving every
ambiguity is judgment-heavy. Also exposes ``architect_revise`` for the ``underspecified``
branch of the state machine: it adds exactly the decision the Arbiter says is missing.
"""

from __future__ import annotations

from ..shared.schemas import ArbiterVerdict, Spec
from . import load_prompt
from .format import render_spec
from .runtime import AgentContext, invoke

_PROMPT = load_prompt("architect")


def architect(prompt: str, ctx: AgentContext) -> Spec:
    user = (
        "Convert this informal coding request into a frozen Spec. Resolve EVERY edge-case "
        "ambiguity explicitly in explicit_decisions.\n\n"
        f"REQUEST:\n{prompt}"
    )
    res = invoke(
        ctx,
        "architect",
        _PROMPT,
        user,
        Spec,
        reasoning_effort="medium",
        temperature=0.4,
        max_completion_tokens=6000,
    )
    spec: Spec = res.parsed  # type: ignore[assignment]
    ctx.emitter.spec_ready(spec.model_dump())
    ctx.emitter.agent_done(
        "architect",
        f"{spec.function_name}() — {len(spec.explicit_decisions)} explicit decision(s)",
    )
    return spec


def architect_revise(spec: Spec, verdict: ArbiterVerdict, ctx: AgentContext) -> Spec:
    """Revise the spec to close the gap the Arbiter identified as underspecified."""
    user = (
        "The current spec was ruled UNDERSPECIFIED for a failing input. Revise it so the "
        "answer is fully determined — add the missing decision to explicit_decisions and "
        "adjust constraints/criteria as needed. Keep the same function_name and signature "
        "unless the gap requires changing them.\n\n"
        f"CURRENT SPEC:\n{render_spec(spec)}\n\n"
        f"ARBITER REASONING:\n{verdict.reasoning}\n\n"
        f"REQUIRED ADDITION:\n{verdict.recommended_action}"
    )
    res = invoke(
        ctx,
        "architect",
        _PROMPT,
        user,
        Spec,
        reasoning_effort="medium",
        temperature=0.4,
        max_completion_tokens=6000,
    )
    revised: Spec = res.parsed  # type: ignore[assignment]
    ctx.emitter.spec_ready(revised.model_dump())
    ctx.emitter.agent_done(
        "architect",
        f"revised spec — {len(revised.explicit_decisions)} explicit decision(s)",
    )
    return revised
