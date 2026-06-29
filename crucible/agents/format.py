"""Human-readable renderings of the seam objects for inclusion in agent prompts.

These turn a Spec / Counterexample / failing test into the focused context block an agent
needs — and, crucially, they let us hand the Implementer the spec WITHOUT ever rendering the
oracle, and the Adversary the spec WITHOUT ever rendering the code. Anti-collusion lives in
which renderer a role is allowed to call.
"""

from __future__ import annotations

import json

from ..shared.schemas import Counterexample, Spec


def render_spec(spec: Spec) -> str:
    lines: list[str] = []
    lines.append(f"function_name: {spec.function_name}")
    lines.append(f"signature: {spec.signature}")
    lines.append(f"description: {spec.description}")
    if spec.input_constraints:
        lines.append("input_constraints:")
        lines += [f"  - {c}" for c in spec.input_constraints]
    if spec.output_constraints:
        lines.append("output_constraints:")
        lines += [f"  - {c}" for c in spec.output_constraints]
    if spec.explicit_decisions:
        lines.append("explicit_decisions (every downstream agent is bound to these):")
        for d in spec.explicit_decisions:
            lines.append(f"  - AMBIGUITY: {d.ambiguity}")
            lines.append(f"    DECISION:  {d.decision}")
    if spec.acceptance_criteria:
        lines.append("acceptance_criteria:")
        lines += [f"  - {c}" for c in spec.acceptance_criteria]
    if spec.illustrative_examples:
        lines.append("illustrative_examples (intent only — NOT the test suite):")
        for ex in spec.illustrative_examples:
            lines.append(f"  - {json.dumps(ex)}")
    return "\n".join(lines)


def render_counterexample(ce: Counterexample) -> str:
    return (
        f"failing_stage: {ce.failing_stage}\n"
        f"input:    {ce.input_repr}\n"
        f"actual:   {ce.actual_repr}\n"
        f"expected: {ce.expected_repr}"
    )
