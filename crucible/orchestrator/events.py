"""Structured event stream emitted by the orchestrator and rendered by the UI.

The canonical event set is defined in §6 of CRUCIBLE_SPEC.md:

    agent_start{role}, agent_token{role,text}, agent_done{role,summary},
    stage_start{stage}, stage_result{StageResult}, arbiter_verdict{ArbiterVerdict},
    candidate_delivered{code}, floor_reached{code,unverified_property},
    metrics{tokens_used,tokens_per_sec,ttft}

A handful of additive events (run_start, spec_ready, oracle_ready, candidate_proposed,
surgeon_patch, iteration, note, run_error) carry the structured payloads the split-screen
UI needs to draw spec/oracle/diff cards. They never replace a canonical event.

Every event is a plain JSON-serializable dict so it can be pushed straight down an SSE
channel. The :class:`EventEmitter` stamps each one with a monotonic ``seq`` and a relative
``t`` (seconds since the run started) for the live tok/s readout.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from ..shared.schemas import ArbiterVerdict, StageResult

# --- canonical event type names (§6) ---
AGENT_START = "agent_start"
AGENT_TOKEN = "agent_token"
AGENT_DONE = "agent_done"
STAGE_START = "stage_start"
STAGE_RESULT = "stage_result"
ARBITER_VERDICT = "arbiter_verdict"
CANDIDATE_DELIVERED = "candidate_delivered"
FLOOR_REACHED = "floor_reached"
METRICS = "metrics"

# --- additive events used by the UI ---
RUN_START = "run_start"
RUN_DONE = "run_done"
RUN_ERROR = "run_error"
ITERATION = "iteration"
NOTE = "note"
SPEC_READY = "spec_ready"
ORACLE_READY = "oracle_ready"
CANDIDATE_PROPOSED = "candidate_proposed"
SURGEON_PATCH = "surgeon_patch"


# Roles, for reference / validation.
ROLES = ("architect", "adversary", "implementer", "surgeon", "arbiter", "vanilla")

Sink = Callable[[dict[str, Any]], None]


class EventEmitter:
    """Stamps events with ``seq``/``t`` and forwards them to an optional sink.

    The sink is anything that accepts a dict: an asyncio-queue pusher for the SSE server,
    a console printer for the CLI, or ``None`` to discard. Convenience methods build the
    canonical/additive payloads so the orchestrator never hand-writes a dict.
    """

    def __init__(self, sink: Optional[Sink] = None) -> None:
        self._sink = sink
        self._seq = 0
        self._t0 = time.monotonic()
        self.history: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        stamped = {**event, "seq": self._seq, "t": round(time.monotonic() - self._t0, 4)}
        self.history.append(stamped)
        if self._sink is not None:
            self._sink(stamped)
        return stamped

    # --- canonical (§6) ---
    def agent_start(self, role: str) -> dict[str, Any]:
        return self.emit({"type": AGENT_START, "role": role})

    def agent_token(self, role: str, text: str) -> dict[str, Any]:
        return self.emit({"type": AGENT_TOKEN, "role": role, "text": text})

    def agent_done(self, role: str, summary: str) -> dict[str, Any]:
        return self.emit({"type": AGENT_DONE, "role": role, "summary": summary})

    def stage_start(self, stage: str) -> dict[str, Any]:
        return self.emit({"type": STAGE_START, "stage": stage})

    def stage_result(self, result: StageResult) -> dict[str, Any]:
        return self.emit({"type": STAGE_RESULT, "result": result.model_dump()})

    def arbiter_verdict(self, verdict: ArbiterVerdict) -> dict[str, Any]:
        return self.emit({"type": ARBITER_VERDICT, "verdict": verdict.model_dump()})

    def candidate_delivered(self, code: str) -> dict[str, Any]:
        return self.emit({"type": CANDIDATE_DELIVERED, "code": code})

    def floor_reached(self, code: str, unverified_property: str) -> dict[str, Any]:
        return self.emit(
            {"type": FLOOR_REACHED, "code": code, "unverified_property": unverified_property}
        )

    def metrics(self, tokens_used: int, tokens_per_sec: float, ttft: float) -> dict[str, Any]:
        return self.emit(
            {
                "type": METRICS,
                "tokens_used": tokens_used,
                "tokens_per_sec": round(tokens_per_sec, 1),
                "ttft": round(ttft, 4),
            }
        )

    # --- additive (UI affordances) ---
    def run_start(self, prompt: str) -> dict[str, Any]:
        return self.emit({"type": RUN_START, "prompt": prompt})

    def run_done(self, status: str, code: str, summary: str) -> dict[str, Any]:
        return self.emit({"type": RUN_DONE, "status": status, "code": code, "summary": summary})

    def run_error(self, message: str) -> dict[str, Any]:
        return self.emit({"type": RUN_ERROR, "message": message})

    def iteration(self, n: int) -> dict[str, Any]:
        return self.emit({"type": ITERATION, "n": n})

    def note(self, text: str) -> dict[str, Any]:
        return self.emit({"type": NOTE, "text": text})

    def spec_ready(self, spec: dict[str, Any]) -> dict[str, Any]:
        return self.emit({"type": SPEC_READY, "spec": spec})

    def oracle_ready(
        self,
        boundary_categories: list[str],
        property_names: list[str],
        example_count: int,
        has_reference: bool,
        example_tests: Optional[list[dict[str, Any]]] = None,
        property_tests: Optional[list[dict[str, Any]]] = None,
        differential_reference: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.emit(
            {
                "type": ORACLE_READY,
                "boundary_categories": boundary_categories,
                "property_names": property_names,
                "example_count": example_count,
                "has_reference": has_reference,
                "example_tests": example_tests or [],
                "property_tests": property_tests or [],
                "differential_reference": differential_reference or "",
            }
        )

    def candidate_proposed(self, code: str, reasoning: str) -> dict[str, Any]:
        return self.emit({"type": CANDIDATE_PROPOSED, "code": code, "reasoning": reasoning})

    def surgeon_patch(self, code: str, diff_explanation: str) -> dict[str, Any]:
        return self.emit({"type": SURGEON_PATCH, "code": code, "diff_explanation": diff_explanation})
