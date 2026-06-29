"""The seam: pydantic models shared by every agent, the oracle, and the orchestrator.

These models are the contract between the two halves of the system (the loop and the
oracle). They match §6 of CRUCIBLE_SPEC.md exactly — do not add fields here without
changing the spec, because every agent's strict json_schema response_format is generated
straight from these classes.
"""

from pydantic import BaseModel
from typing import Literal, Optional


class ExplicitDecision(BaseModel):
    ambiguity: str
    decision: str


class Spec(BaseModel):
    function_name: str
    signature: str                       # full def line with type hints
    description: str
    input_constraints: list[str]
    output_constraints: list[str]
    explicit_decisions: list[ExplicitDecision]
    acceptance_criteria: list[str]
    illustrative_examples: list[dict]    # {"input":..,"output":..} — NOT the test suite


class ExampleTest(BaseModel):
    input_repr: str                      # python literal as string
    expected_repr: str
    boundary_category: str


class PropertyTest(BaseModel):
    name: str
    strategy: str                        # Hypothesis strategy source, e.g. "lists(tuples(integers(),integers()))"
    code: str                            # runnable test body referencing `candidate`


class Oracle(BaseModel):
    boundary_categories: list[str]
    example_tests: list[ExampleTest]
    property_tests: list[PropertyTest]
    differential_reference: Optional[str]  # runnable slow-correct impl, or None


class Candidate(BaseModel):
    code: str
    reasoning: str


class Counterexample(BaseModel):
    input_repr: str
    actual_repr: str
    expected_repr: str
    failing_stage: str


class StageResult(BaseModel):
    stage: Literal["parse", "typecheck", "smoke", "examples", "properties", "differential"]
    status: Literal["pass", "fail", "error"]
    detail: str
    counterexample: Optional[Counterexample] = None


class ArbiterVerdict(BaseModel):
    verdict: Literal["code_bug", "bad_test", "underspecified"]
    reasoning: str
    recommended_action: str
    offending_test: Optional[str] = None
