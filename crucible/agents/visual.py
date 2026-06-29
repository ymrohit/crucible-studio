"""Visual QA agent — sends a real browser screenshot of the built UI to the vision model
(gemma-4-31b supports image input) and asks whether the UI is actually in place.

This catches what DOM/logic tests can't: missing-from-view elements, broken layout, nothing
rendered, overlap. Used by repo mode for web-UI tasks after the functional check passes.
"""

from __future__ import annotations

import base64

from ..shared.repo_schemas import VisualVerdict
from . import load_prompt
from .runtime import AgentContext, invoke

_PROMPT = load_prompt("visual_qa")


def visual_qa(png_bytes: bytes, task: str, ctx: AgentContext, role: str = "vision") -> VisualVerdict:
    b64 = base64.b64encode(png_bytes).decode()
    image_block = {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
    user = (
        f"TASK the UI was built for:\n{task}\n\n"
        "Here is a screenshot of the rendered page. Verify everything required is visibly in place."
    )
    res = invoke(
        ctx, role, _PROMPT, user, VisualVerdict,   # the 'vision' chip = the multimodal visual judge
        reasoning_effort=None, temperature=0.2, max_completion_tokens=1200,
        extra_user_blocks=[image_block],
    )
    verdict: VisualVerdict = res.parsed  # type: ignore[assignment]
    status = "looks correct" if verdict.looks_correct else f"issues: {'; '.join(verdict.issues[:3])}"
    ctx.emitter.agent_done(role, f"visual QA — {status}")
    return verdict
