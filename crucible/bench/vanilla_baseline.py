"""Single-shot vanilla Gemma — the control condition.

This is what the LEFT pane shows and what Condition A of the offline runner scores: one
plain call, no spec, no oracle, no repair. Fast, confident, and silently wrong on the edges
Crucible catches.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from ..agents.base import CerebrasClient, get_client

VANILLA_SYSTEM = (
    "You are a fast, helpful coding assistant. Given a request, write ONE correct, "
    "self-contained Python function that satisfies it. Include any imports the function "
    "needs. Respond with the code only, inside a single ```python code block."
)


def extract_code(text: str) -> str:
    """Pull the code out of a ```python fence; fall back to the raw text."""
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def vanilla(prompt: str, *, client: Optional[CerebrasClient] = None) -> dict[str, Any]:
    client = client or get_client()
    content, usage, time_info, tps, ttft = client.text(
        VANILLA_SYSTEM, prompt, temperature=0.7, max_completion_tokens=8192
    )
    return {
        "code": extract_code(content),
        "raw": content,
        "usage": usage,
        "time_info": time_info,
        "tokens_per_sec": tps,
        "elapsed": float(time_info.get("total_time", 0) or 0),
    }


def vanilla_stream(
    prompt: str,
    on_token: Callable[[str], None],
    *,
    client: Optional[CerebrasClient] = None,
) -> dict[str, Any]:
    """Stream the vanilla answer token-by-token (the fast left-pane typewriter)."""
    client = client or get_client()
    content, usage, time_info = client.stream_text(
        VANILLA_SYSTEM, prompt, on_token, temperature=0.7, max_completion_tokens=8192
    )
    completion = float(usage.get("completion_tokens", 0) or 0)
    ctime = float(time_info.get("completion_time", 0) or 0)
    return {
        "code": extract_code(content),
        "raw": content,
        "usage": usage,
        "time_info": time_info,
        "tokens_per_sec": completion / ctime if ctime > 0 else 0.0,
        "elapsed": float(time_info.get("total_time", 0) or 0),
    }


if __name__ == "__main__":  # quick manual check
    import sys

    p = " ".join(sys.argv[1:]) or "merge overlapping booking intervals"
    out = vanilla(p)
    print(out["code"])
    print(f"\n[{out['tokens_per_sec']:.0f} tok/s · {out['elapsed']:.2f}s]")
