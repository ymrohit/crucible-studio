"""Implementer — writes the initial code from the spec (§8 implementer.txt).

Anti-collusion: the signature accepts a Spec and NOTHING else. It is structurally
impossible for the Implementer to see the Oracle and game the tests.
"""

from __future__ import annotations

from ..shared.schemas import Candidate, Spec
from . import load_prompt
from .format import render_spec
from .runtime import AgentContext, invoke

_PROMPT = load_prompt("implementer")


def implementer(spec: Spec, ctx: AgentContext) -> Candidate:
    user = (
        "Implement this specification exactly. Match the signature; honor every "
        "explicit_decision and acceptance_criterion. Return the full function as code.\n\n"
        f"SPEC:\n{render_spec(spec)}"
    )
    res = invoke(
        ctx,
        "implementer",
        _PROMPT,
        user,
        Candidate,
        reasoning_effort=None,  # off for speed (§9)
        temperature=0.5,
        max_completion_tokens=3000,
    )
    candidate: Candidate = res.parsed  # type: ignore[assignment]
    ctx.emitter.candidate_proposed(candidate.code, candidate.reasoning)
    ctx.emitter.agent_done("implementer", "initial candidate written")
    return candidate
