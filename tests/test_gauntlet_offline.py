"""API-free verification of the oracle gauntlet and the seam.

Runs with NO Cerebras key — it exercises only the deterministic half (sandbox, stages,
strict-schema generation) with hand-built candidates/oracles. Good for a fast smoke test:

    python tests/test_gauntlet_offline.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crucible.agents.base import build_strict_schema
from crucible.oracle import gauntlet
from crucible.shared.schemas import (
    Candidate, ExampleTest, Oracle, PropertyTest, Spec, StageResult,
)

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
failures = 0


def check(name, cond):
    global failures
    print(f"  [{PASS if cond else FAIL}] {name}")
    if not cond:
        failures += 1


SPEC = Spec(
    function_name="merge_intervals",
    signature="def merge_intervals(intervals: list[tuple[int,int]]) -> list[tuple[int,int]]:",
    description="merge overlapping/touching intervals",
    input_constraints=[], output_constraints=[], explicit_decisions=[],
    acceptance_criteria=[], illustrative_examples=[{"input": "[(1,3),(2,6)]", "output": "[(1,6)]"}],
)
ORACLE = Oracle(
    boundary_categories=["touching", "empty"],
    example_tests=[
        ExampleTest(input_repr="[(1,3),(2,6),(8,10)]", expected_repr="[(1,6),(8,10)]", boundary_category="overlap"),
        ExampleTest(input_repr="[]", expected_repr="[]", boundary_category="empty"),
    ],
    property_tests=[PropertyTest(
        name="disjoint_sorted",
        strategy="lists(tuples(integers(min_value=0,max_value=30), integers(min_value=0,max_value=30)).map(lambda t:(min(t),max(t))))",
        code="r = candidate(x)\nfor i in range(len(r)-1):\n    assert r[i][1] < r[i+1][0]",
    )],
    differential_reference=(
        "def merge_ref(iv):\n    p=sorted((s,e) for s,e in iv if s<=e)\n    o=[]\n"
        "    for s,e in p:\n        if o and s<=o[-1][1]: o[-1]=(o[-1][0],max(o[-1][1],e))\n"
        "        else: o.append((s,e))\n    return o\n"
    ),
)
GOOD = Candidate(code=(
    "def merge_intervals(intervals):\n    p=sorted((s,e) for s,e in intervals if s<=e)\n    o=[]\n"
    "    for s,e in p:\n        if o and s<=o[-1][1]: o[-1]=(o[-1][0],max(o[-1][1],e))\n"
    "        else: o.append((s,e))\n    return o\n"), reasoning="ok")
BROKEN = Candidate(code=(  # off-by-one: strict < instead of <=
    "def merge_intervals(intervals):\n    p=sorted((s,e) for s,e in intervals if s<=e)\n    o=[]\n"
    "    for s,e in p:\n        if o and s<o[-1][1]: o[-1]=(o[-1][0],max(o[-1][1],e))\n"
    "        else: o.append((s,e))\n    return o\n"), reasoning="bug")
SYNTAX = Candidate(code="def merge_intervals(x)\n    return x\n", reasoning="syntax")


def main():
    print("== strict schema generation ==")
    schema = build_strict_schema(Spec)
    check("Spec schema is strict-object", schema.get("additionalProperties") is False)
    check("all properties required", set(schema["required"]) == set(schema["properties"]))
    check("free-form dict expanded to input/output",
          "input" in schema["$defs"]["Spec"]["properties"]["illustrative_examples"]["items"]["properties"]
          if "$defs" in schema and "Spec" in schema.get("$defs", {}) else
          "input" in schema["properties"]["illustrative_examples"]["items"]["properties"])

    print("\n== gauntlet: GOOD candidate (should pass all) ==")
    r = gauntlet.run(GOOD, ORACLE, SPEC, max_property_examples=60, max_differential_examples=120)
    for s in r.results:
        print(f"     {s.stage:<12} {s.status}")
    check("all_pass", r.all_pass)
    check("passed_count == 6", r.passed_count == 6)

    print("\n== gauntlet: BROKEN candidate (property catches off-by-one) ==")
    r = gauntlet.run(BROKEN, ORACLE, SPEC, max_property_examples=120, max_differential_examples=120)
    ff = r.first_failure
    check("not all_pass", not r.all_pass)
    check("failure has a counterexample", ff is not None and ff.counterexample is not None)
    if ff and ff.counterexample:
        print(f"     counterexample: input={ff.counterexample.input_repr} stage={ff.counterexample.failing_stage}")

    print("\n== gauntlet: SYNTAX error (parse catches) ==")
    r = gauntlet.run(SYNTAX, ORACLE, SPEC)
    check("first failure is parse", r.first_unpassed_stage == "parse")

    print("\n== sandbox: timeout is killed, not hung ==")
    from crucible.oracle.sandbox import get_sandbox
    res = get_sandbox().run_python("while True:\n    pass\n", timeout=2.0)
    check("timed_out flagged", res.timed_out)
    check("duration bounded (<6s)", res.duration < 6.0)

    print()
    if failures:
        print(f"\033[31m{failures} check(s) FAILED\033[0m")
        return 1
    print("\033[32mALL OFFLINE CHECKS PASSED\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
