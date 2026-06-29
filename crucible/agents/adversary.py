"""Adversary — the blind, hostile QA engineer (§8 adversary.txt).

Anti-collusion, enforced by signature: ``adversary(spec, ctx)`` takes a Spec and nothing
else. It can never see the candidate code, so it cannot weaken a test to bless a bug.

The verbatim system prompt is kept intact; the *execution contract* (how the oracle's tests
are actually run by the gauntlet — see oracle/harness.py) is supplied in the user message so
the tests it writes are runnable.
"""

from __future__ import annotations

from ..shared.schemas import Oracle, Spec
from . import load_prompt
from .format import render_spec
from .runtime import AgentContext, invoke

_PROMPT = load_prompt("adversary")

_CONTRACT = """
HOW YOUR TESTS WILL BE EXECUTED (write them to fit this exactly):

* example_tests: input_repr is the SOURCE TEXT placed inside the call parentheses — the
  harness runs `candidate(<input_repr>)`. For a single-argument function pass the literal of
  that argument (e.g. "[(1,3),(2,6)]"); for multiple arguments separate them with commas
  (e.g. "5, [1,2,3]"). expected_repr is a Python literal evaluated as the expected return.

* property_tests: each runs as
      @given(x=<your strategy>)
      def test(x):
          <your code>
  So your `code` MUST reference the single generated input as `x` and call the function as
  `candidate`. `strategy` is Hypothesis source; bare names work (lists, integers, tuples,
  text, ...) and `st.` is also available. Make the strategy generate VALID inputs per the
  spec's input_constraints. Assert the invariant; raise AssertionError on violation.

* differential_reference: a COMPLETE function definition (slow but obviously correct). It is
  called the same way as the candidate over inputs drawn from your first property strategy
  (single argument `x`), and outputs are compared with float-tolerant equality. Provide it
  ONLY when a structurally-different, trivially-correct reference exists; otherwise null.
"""


def adversary(spec: Spec, ctx: AgentContext) -> Oracle:
    user = (
        "Write a hostile oracle that exposes bugs in an implementation you will never see. "
        "Attack the spec's dangerous regions and EVERY explicit_decision.\n\n"
        f"SPEC:\n{render_spec(spec)}\n{_CONTRACT}"
    )
    res = invoke(
        ctx,
        "adversary",
        _PROMPT,
        user,
        Oracle,
        reasoning_effort="low",  # a little judgment helps it find the catching tests
        temperature=0.7,
        max_completion_tokens=8000,  # oracle JSON is the largest output; avoid truncation
    )
    oracle: Oracle = res.parsed  # type: ignore[assignment]
    ctx.emitter.oracle_ready(
        boundary_categories=oracle.boundary_categories,
        property_names=[p.name for p in oracle.property_tests],
        example_count=len(oracle.example_tests),
        has_reference=bool(oracle.differential_reference and oracle.differential_reference.strip()),
        example_tests=[t.model_dump() for t in oracle.example_tests],
        property_tests=[p.model_dump() for p in oracle.property_tests],
        differential_reference=oracle.differential_reference or "",
    )
    ctx.emitter.agent_done(
        "adversary",
        f"{len(oracle.example_tests)} examples, {len(oracle.property_tests)} properties, "
        f"differential={'yes' if oracle.differential_reference else 'no'}",
    )
    return oracle
