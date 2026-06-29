"""The budget governor: a hard cap on tokens, iterations, and wall-clock (§7).

The loop must be physically unable to run away and brick the Cerebras rate limit, so the
governor is charged from *every* response's usage and consulted before every iteration.
On exhaustion the state machine returns the graceful floor rather than continuing.
"""

from __future__ import annotations

import time
from typing import Any, Union


class Budget:
    def __init__(
        self,
        max_tokens: int = 60_000,
        max_iters: int = 8,
        max_seconds: float = 90.0,
    ) -> None:
        self.max_tokens = max_tokens
        self.max_iters = max_iters
        self.max_seconds = max_seconds
        self.tokens_used = 0
        self.iters = 0
        self._t0 = time.monotonic()

    def charge(self, usage: Union[dict[str, Any], int, None]) -> int:
        """Add a response's token cost. Accepts a usage dict or a raw int."""
        if usage is None:
            return self.tokens_used
        if isinstance(usage, int):
            self.tokens_used += usage
        else:
            self.tokens_used += int(usage.get("total_tokens", 0) or 0)
        return self.tokens_used

    def tick(self) -> int:
        """Count one loop iteration (one gauntlet run + repair)."""
        self.iters += 1
        return self.iters

    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.tokens_used)

    def remaining_seconds(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed())

    def exhausted(self) -> bool:
        return (
            self.tokens_used >= self.max_tokens
            or self.iters >= self.max_iters
            or self.elapsed() >= self.max_seconds
        )

    def reason(self) -> str:
        if self.tokens_used >= self.max_tokens:
            return f"token budget exhausted ({self.tokens_used}/{self.max_tokens})"
        if self.iters >= self.max_iters:
            return f"iteration budget exhausted ({self.iters}/{self.max_iters})"
        if self.elapsed() >= self.max_seconds:
            return f"wall-clock budget exhausted ({self.elapsed():.1f}s/{self.max_seconds}s)"
        return "within budget"

    def snapshot(self) -> dict[str, Any]:
        return {
            "tokens_used": self.tokens_used,
            "max_tokens": self.max_tokens,
            "iters": self.iters,
            "max_iters": self.max_iters,
            "elapsed": round(self.elapsed(), 2),
            "max_seconds": self.max_seconds,
        }
