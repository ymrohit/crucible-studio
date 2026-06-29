"""Arbiter — adjudicates a stuck failure: code_bug / bad_test / underspecified (§8 arbiter.txt).

Fires only when the same stage has failed twice (§7). It is a judge, not a producer, so it
is allowed to see the spec, the code, AND the offending oracle test — that breadth is what
lets it rule a test wrong (bad_test) or the spec incomplete (underspecified), resolving the
gap bidirectionally instead of letting the loop thrash forever on a bad oracle.
"""

from __future__ import annotations

import re

from ..shared.schemas import ArbiterVerdict, Candidate, Oracle, Spec, StageResult
from . import load_prompt
from .format import render_counterexample, render_spec
from .runtime import AgentContext, invoke

_PROMPT = load_prompt("arbiter")


def _offending_test_text(failure: StageResult, oracle: Oracle) -> str:
    """Render the specific oracle test that failed, so the Arbiter can name/quote it."""
    stage = failure.stage
    if stage == "properties":
        m = re.search(r"property '([^']+)'", failure.detail)
        if m:
            name = m.group(1)
            for p in oracle.property_tests:
                if p.name == name:
                    return (
                        f"PROPERTY TEST '{p.name}':\n"
                        f"  strategy: {p.strategy}\n"
                        f"  asserts (with generated input x):\n{p.code}"
                    )
    if stage == "examples" and failure.counterexample:
        ce = failure.counterexample
        for t in oracle.example_tests:
            if t.input_repr == ce.input_repr:
                return (
                    f"EXAMPLE TEST [{t.boundary_category}]:\n"
                    f"  candidate({t.input_repr}) is asserted to equal {t.expected_repr}"
                )
    if stage == "differential" and oracle.differential_reference:
        return f"DIFFERENTIAL REFERENCE (asserted equal to candidate):\n{oracle.differential_reference}"
    return f"(stage '{stage}' failure — detail: {failure.detail})"


def arbiter(
    spec: Spec,
    candidate: Candidate,
    failure: StageResult,
    oracle: Oracle,
    ctx: AgentContext,
) -> ArbiterVerdict:
    ce_text = render_counterexample(failure.counterexample) if failure.counterexample else "(none captured)"
    user = (
        "An implementation keeps failing the SAME oracle stage. Rule on whose fault it is: "
        "code_bug, bad_test, or underspecified.\n\n"
        f"SPEC:\n{render_spec(spec)}\n\n"
        f"CURRENT CODE:\n```python\n{candidate.code}\n```\n\n"
        f"FAILING STAGE: {failure.stage}\nDETAIL: {failure.detail}\n\n"
        f"OFFENDING TEST:\n{_offending_test_text(failure, oracle)}\n\n"
        f"COUNTEREXAMPLE:\n{ce_text}\n\n"
        "Reason about what the spec REQUIRES vs what the test ASSERTS vs what the code DOES."
    )
    res = invoke(
        ctx,
        "arbiter",
        _PROMPT,
        user,
        ArbiterVerdict,
        reasoning_effort="medium",  # judgment-heavy (§9)
        temperature=0.3,
        max_completion_tokens=6000,
    )
    verdict: ArbiterVerdict = res.parsed  # type: ignore[assignment]
    ctx.emitter.arbiter_verdict(verdict)
    ctx.emitter.agent_done("arbiter", f"verdict: {verdict.verdict}")
    return verdict
