"""Self-optimizing reasoning control: an agent decides how much reasoning effort to spend, and the
loop escalates it when stuck — so the system spends little on easy tasks and cranks reasoning to the
max on hard ones, automatically.

Cerebras gemma-4-31b accepts reasoning_effort in {none, low, medium, high}; `high` is the max.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

from . import load_prompt
from .runtime import AgentContext, invoke

LADDER = ["none", "low", "medium", "high"]   # increasing reasoning effort; high == max


class ReasoningPlan(BaseModel):
    difficulty: int                                       # 1 (trivial) .. 5 (very hard)
    effort: Literal["none", "low", "medium", "high"]
    rationale: str


_PROMPT = load_prompt("effort_controller")


def decide_effort(task: str, ctx: AgentContext) -> ReasoningPlan:
    """A cheap classification call that picks the starting reasoning effort for a task."""
    res = invoke(ctx, "controller", _PROMPT, "TASK:\n" + task[:3500], ReasoningPlan,
                 reasoning_effort=None, temperature=0.2, max_completion_tokens=2000)
    plan: ReasoningPlan = res.parsed  # type: ignore[assignment]
    ctx.emitter.agent_done("controller", f"difficulty {plan.difficulty}/5 → reasoning={plan.effort}")
    return plan


def escalate(effort: Optional[str]) -> str:
    """Next rung up the reasoning ladder (capped at the max, 'high')."""
    i = LADDER.index(effort) if effort in LADDER else LADDER.index("medium")
    return LADDER[min(i + 1, len(LADDER) - 1)]


def at_max(effort: Optional[str]) -> bool:
    return effort == LADDER[-1]
