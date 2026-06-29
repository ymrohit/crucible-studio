"""Shared plumbing every agent uses: an :class:`AgentContext` (client + emitter + budget)
and an :func:`invoke` helper that emits ``agent_start``, charges the budget from the
response usage, and emits a ``metrics`` event. Agents add their own ``agent_done`` summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from ..orchestrator.budget import Budget
from ..orchestrator.events import EventEmitter, Sink
from .base import CallResult, CerebrasClient, get_client

T = TypeVar("T", bound=BaseModel)


@dataclass
class AgentContext:
    client: CerebrasClient
    emitter: EventEmitter
    budget: Budget

    @classmethod
    def create(
        cls,
        *,
        sink: Optional[Sink] = None,
        budget: Optional[Budget] = None,
        client: Optional[CerebrasClient] = None,
    ) -> "AgentContext":
        return cls(
            client=client or get_client(),
            emitter=EventEmitter(sink),
            budget=budget or Budget(),
        )


def invoke(
    ctx: AgentContext,
    role: str,
    system_prompt: str,
    user_content: str,
    schema: Type[T],
    *,
    reasoning_effort: Optional[str] = None,
    temperature: float = 0.6,
    max_completion_tokens: int = 4096,
    extra_user_blocks: Optional[list[dict[str, Any]]] = None,
) -> CallResult:
    """Run one structured agent call with bookkeeping. Returns the full CallResult."""
    ctx.emitter.agent_start(role)
    res = ctx.client.structured(
        system_prompt,
        user_content,
        schema,
        reasoning_effort=reasoning_effort,
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
        extra_user_blocks=extra_user_blocks,
    )
    ctx.budget.charge(res.usage)
    ctx.emitter.metrics(ctx.budget.tokens_used, res.tokens_per_sec, res.ttft)
    return res
