"""Oracle gauntlet stages. Each exposes ``run(ctx) -> StageResult`` and never marks its own
homework: pass/fail comes only from executing code or static analysis, not from any LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ...shared.schemas import Counterexample, Oracle, Spec, StageResult
from ..sandbox import Sandbox, SandboxResult


@dataclass
class StageContext:
    candidate_code: str
    function_name: str
    oracle: Oracle
    sandbox: Sandbox
    spec: Optional[Spec] = None
    max_property_examples: int = 100
    max_differential_examples: int = 200
    timeout: float = 20.0


def _counterexample(stage: str, parsed: dict[str, Any]) -> Optional[Counterexample]:
    if parsed.get("input") is None:
        return None
    return Counterexample(
        input_repr=str(parsed.get("input", "")),
        actual_repr=str(parsed.get("actual", "")),
        expected_repr=str(parsed.get("expected", "")),
        failing_stage=stage,
    )


def result_from_run(
    stage: str, run: SandboxResult, parsed: Optional[dict[str, Any]]
) -> StageResult:
    """Turn a sandbox run + parsed result envelope into a StageResult."""
    if run.timed_out:
        return StageResult(
            stage=stage,  # type: ignore[arg-type]
            status="fail",
            detail=f"timed out after {run.duration:.1f}s (process killed — likely infinite loop)",
            counterexample=None,
        )
    if parsed is None:
        tail = (run.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else f"no result emitted (returncode={run.returncode})"
        return StageResult(
            stage=stage,  # type: ignore[arg-type]
            status="error",
            detail=f"candidate crashed: {detail[:300]}",
            counterexample=None,
        )
    status = parsed.get("status", "error")
    return StageResult(
        stage=stage,  # type: ignore[arg-type]
        status=status,
        detail=str(parsed.get("detail", "")),
        counterexample=_counterexample(stage, parsed) if status in ("fail", "error") else None,
    )
