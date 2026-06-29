"""Web-app builder agents: turn a prompt into ONE self-contained, runnable web app file
(vanilla JS or a CDN framework like React, no build step) that previews live in an iframe.

The blind Adversary describes how to drive it (a click sequence by visible label) and what the
result should look like; the oracle renders it in a real browser, performs those clicks, and the
vision model reads the screenshot to confirm it actually works. The Surgeon repairs from the
visual verdict. Same non-colluding split as the function loop, applied to a real UI.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from .runtime import AgentContext, invoke


class WebAppPlan(BaseModel):
    title: str = Field(description="short app title")
    framework: str = Field(description="'vanilla' or a CDN framework e.g. 'react'")
    features: list[str] = Field(description="3-6 concrete user-facing features")


class WebAppCheck(BaseModel):
    visual_requirements: list[str] = Field(description="things that MUST be visibly present/working")
    click_sequence: list[str] = Field(
        description="visible button/labels to click in order to exercise the core flow, e.g. ['7','+','8','=']")
    expected_outcome: str = Field(description="what the screen should show after the clicks, e.g. 'the display shows 15'")


_ARCH = (
    "You are a product architect. Given a request for a web app, output a tight plan: a title, the "
    "framework to use ('vanilla' for simple apps, 'react' via CDN for richer interactive ones), and "
    "3-6 concrete user-facing features. Keep it buildable as a SINGLE self-contained file."
)
_ADV = (
    "You are a blind QA adversary. You have NOT seen the implementation. Given the app plan, define "
    "how to prove the app actually works: the visible buttons/labels a user would click in order to "
    "exercise the MAIN flow, and exactly what the screen should show afterward. Click labels must be "
    "the literal visible text a user would tap (e.g. '7', '+', '=', 'Add', 'Submit'). Be concrete."
)
_IMPL = (
    "You are an expert front-end engineer. Build the requested app as ONE COMPLETE, SELF-CONTAINED "
    "HTML file that runs with NO build step by simply opening it. Rules:\n"
    "- Everything inline in one file. You MAY load a framework from a CDN (e.g. React + ReactDOM + "
    "Babel standalone from unpkg) when it genuinely helps; otherwise use clean vanilla JS. Do not use "
    "anything that needs npm/bundling.\n"
    "- It must be a real, working, GOOD-LOOKING app: sensible layout, readable, modern styling, fully "
    "interactive. No placeholder TODOs.\n"
    "- Buttons must have clear visible text labels. The core actions must work client-side.\n"
    "- No backend required. If the request mentions an API, implement the logic client-side (or call a "
    "same-origin path only if one is provided).\n"
    "Respond with ONLY the HTML inside a single ```html code block."
)
_SURG = (
    "You are a surgeon fixing a web app that FAILED visual QA in a real browser. You are given the "
    "current single-file HTML and the exact problems a vision model saw in the rendered screenshot. "
    "Return the COMPLETE corrected single-file HTML (same self-contained rules), fixing those problems "
    "without regressing what worked. Respond with ONLY the HTML inside a single ```html code block."
)


def _extract_html(text: str) -> str:
    m = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.DOTALL)
    html = m.group(1).strip() if m else text.strip()
    if "<html" not in html.lower() and "<!doctype" not in html.lower():
        # wrap a bare fragment so it still renders
        html = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>{html}</body></html>"
    return html


def webapp_architect(prompt: str, ctx: AgentContext) -> WebAppPlan:
    res = invoke(ctx, "architect", _ARCH, f"App request:\n{prompt}", WebAppPlan,
                 reasoning_effort="low", temperature=0.4, max_completion_tokens=1200)
    plan: WebAppPlan = res.parsed  # type: ignore[assignment]
    ctx.emitter.agent_done("architect", f"{plan.title} ({plan.framework}) — {len(plan.features)} features")
    ctx.emitter.spec_ready({"function_name": plan.title, "signature": f"{plan.framework} web app",
                            "description": ", ".join(plan.features[:6])})
    return plan


def webapp_adversary(prompt: str, plan: WebAppPlan, ctx: AgentContext) -> WebAppCheck:
    user = (f"App request:\n{prompt}\n\nPlan: {plan.title} ({plan.framework}); features: "
            + ", ".join(plan.features))
    res = invoke(ctx, "adversary", _ADV, user, WebAppCheck,
                 reasoning_effort="low", temperature=0.5, max_completion_tokens=1400)
    chk: WebAppCheck = res.parsed  # type: ignore[assignment]
    ctx.emitter.agent_done("adversary", f"will click {chk.click_sequence} → expect: {chk.expected_outcome[:60]}")
    ctx.emitter.oracle_ready(
        boundary_categories=chk.visual_requirements[:6],
        property_names=[f"clicks {' '.join(chk.click_sequence[:8])}"] if chk.click_sequence else [],
        example_count=len(chk.visual_requirements), has_reference=False)
    return chk


def _free_text(ctx: AgentContext, role: str, system: str, user: str, *, reasoning: Optional[str] = None) -> str:
    ctx.emitter.agent_start(role)
    content, usage, time_info, tps, ttft = ctx.client.text(
        system, user, temperature=0.4, max_completion_tokens=16000, reasoning_effort=reasoning)
    ctx.budget.charge(usage)
    ctx.emitter.metrics(ctx.budget.tokens_used, tps, ttft)
    return content


def webapp_implementer(prompt: str, plan: WebAppPlan, ctx: AgentContext) -> str:
    user = (f"Build this app:\n{prompt}\n\nTitle: {plan.title}\nFramework: {plan.framework}\n"
            f"Features: {', '.join(plan.features)}")
    html = _extract_html(_free_text(ctx, "implementer", _IMPL, user))
    ctx.emitter.agent_done("implementer", f"{len(html)} bytes of self-contained HTML")
    return html


def webapp_surgeon(prompt: str, html: str, problems: str, ctx: AgentContext) -> str:
    user = (f"Original request:\n{prompt}\n\nProblems seen in the rendered screenshot:\n{problems}\n\n"
            f"Current HTML:\n```html\n{html}\n```")
    out = _extract_html(_free_text(ctx, "surgeon", _SURG, user))
    ctx.emitter.agent_done("surgeon", "revised the app from the visual verdict")
    return out
