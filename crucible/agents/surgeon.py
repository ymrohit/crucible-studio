"""Surgeon — smallest change that fixes one specific counterexample (§8 surgeon.txt).

Per the spec's role table the Surgeon sees only the failing code + the minimal shrunk
counterexample — focused debugging, not a rewrite. reasoning is off for speed (§9).
"""

from __future__ import annotations

from ..shared.schemas import Candidate, Counterexample
from . import load_prompt
from .format import render_counterexample
from .runtime import AgentContext, invoke

_PROMPT = load_prompt("surgeon")


def surgeon(candidate: Candidate, counterexample: Counterexample, ctx: AgentContext) -> Candidate:
    user = (
        "Make the SMALLEST change that fixes this counterexample without breaking anything "
        "that already passed.\n\n"
        f"CURRENT CODE:\n```python\n{candidate.code}\n```\n\n"
        f"MINIMAL COUNTEREXAMPLE:\n{render_counterexample(counterexample)}\n\n"
        "Return the full corrected function; put what you changed and why in reasoning."
    )
    res = invoke(
        ctx,
        "surgeon",
        _PROMPT,
        user,
        Candidate,
        reasoning_effort=None,  # off for speed (§9)
        temperature=0.3,
        max_completion_tokens=3000,
    )
    fixed: Candidate = res.parsed  # type: ignore[assignment]
    ctx.emitter.surgeon_patch(fixed.code, fixed.reasoning)
    ctx.emitter.agent_done("surgeon", "applied targeted fix")
    return fixed
