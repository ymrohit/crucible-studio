"""The oracle gauntlet: runs stages in cheap-first order, short-circuits at the first red,
and emits a StageResult per stage. The model never marks its own homework — every verdict
here comes from executing code or static analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..shared.schemas import Candidate, Counterexample, Oracle, Spec, StageResult
from .sandbox import Sandbox, get_sandbox
from .stages import StageContext
from .stages import differential as differential_stage
from .stages import examples as examples_stage
from .stages import parse as parse_stage
from .stages import properties as properties_stage
from .stages import smoke as smoke_stage
from .stages import typecheck as typecheck_stage

# Fail-fast order (§3).
STAGES = [
    ("parse", parse_stage.run),
    ("typecheck", typecheck_stage.run),
    ("smoke", smoke_stage.run),
    ("examples", examples_stage.run),
    ("properties", properties_stage.run),
    ("differential", differential_stage.run),
]


@dataclass
class GauntletResult:
    results: list[StageResult] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return bool(self.results) and all(r.status == "pass" for r in self.results)

    @property
    def first_failure(self) -> Optional[StageResult]:
        for r in self.results:
            if r.status != "pass":
                return r
        return None

    @property
    def counterexample(self) -> Optional[Counterexample]:
        ff = self.first_failure
        return ff.counterexample if ff else None

    @property
    def passed_count(self) -> int:
        """How many stages passed before the first failure — the progress score for
        graceful-floor best-tracking."""
        n = 0
        for r in self.results:
            if r.status == "pass":
                n += 1
            else:
                break
        return n

    @property
    def first_unpassed_stage(self) -> str:
        ff = self.first_failure
        return ff.stage if ff else "none"


def run(
    candidate: Candidate,
    oracle: Oracle,
    spec: Spec,
    *,
    emitter=None,
    sandbox: Optional[Sandbox] = None,
    max_property_examples: int = 100,
    max_differential_examples: int = 200,
    timeout: float = 20.0,
) -> GauntletResult:
    ctx = StageContext(
        candidate_code=candidate.code,
        function_name=spec.function_name,
        oracle=oracle,
        sandbox=sandbox or get_sandbox(),
        spec=spec,
        max_property_examples=max_property_examples,
        max_differential_examples=max_differential_examples,
        timeout=timeout,
    )

    result = GauntletResult()
    for name, fn in STAGES:
        if emitter is not None:
            emitter.stage_start(name)
        stage_result = fn(ctx)
        result.results.append(stage_result)
        if emitter is not None:
            emitter.stage_result(stage_result)
        if stage_result.status != "pass":
            break  # short-circuit at first red
    return result
