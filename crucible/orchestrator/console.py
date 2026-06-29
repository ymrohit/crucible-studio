"""A console sink for the event stream — used by the CLI (`python -m crucible ...`).

Renders the same events the UI consumes, as compact terminal lines. Pure stdlib ANSI;
falls back to plain text when stdout is not a TTY.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


_ROLE_COLOR = {
    "architect": "36",
    "adversary": "35",
    "implementer": "34",
    "surgeon": "33",
    "arbiter": "31",
    "vanilla": "90",
    "controller": "96",
}

_STATUS_MARK = {"pass": _c("32", "PASS"), "fail": _c("31", "FAIL"), "error": _c("31", "ERR ")}


def make_console_sink(verbose: bool = False) -> Callable[[dict[str, Any]], None]:
    def sink(ev: dict[str, Any]) -> None:
        t = ev.get("type")
        if t == "run_start":
            print(_c("1", f"\n▶ Crucible: {ev['prompt']}\n"))
        elif t == "agent_start":
            role = ev["role"]
            print(_c(_ROLE_COLOR.get(role, "37"), f"  ● {role} …"))
        elif t == "agent_done":
            print(_c("90", f"    ↳ {ev['summary']}"))
        elif t == "spec_ready" and verbose:
            decs = ev["spec"].get("explicit_decisions", [])
            for d in decs:
                print(_c("90", f"      decision: {d['ambiguity']} → {d['decision']}"))
        elif t == "oracle_ready":
            print(
                _c(
                    "90",
                    f"    ↳ oracle: {len(ev['boundary_categories'])} boundary cats, "
                    f"{ev['example_count']} examples, {len(ev['property_names'])} properties, "
                    f"differential={'yes' if ev['has_reference'] else 'no'}",
                )
            )
        elif t == "iteration":
            print(_c("1", f"\n── iteration {ev['n']} ──"))
        elif t == "stage_start":
            print(f"    [{ev['stage']:<11}] running…", end="\r")
        elif t == "stage_result":
            r = ev["result"]
            mark = _STATUS_MARK.get(r["status"], r["status"])
            print(f"    [{r['stage']:<11}] {mark}  {r['detail'][:80]}")
            ce = r.get("counterexample")
            if ce:
                print(_c("31", f"        counterexample @ {ce['failing_stage']}:"))
                print(_c("31", f"          input    = {ce['input_repr'][:120]}"))
                print(_c("31", f"          actual   = {ce['actual_repr'][:120]}"))
                print(_c("31", f"          expected = {ce['expected_repr'][:120]}"))
        elif t == "arbiter_verdict":
            v = ev["verdict"]
            print(_c("31", f"    ⚖ arbiter: {v['verdict']} — {v['recommended_action'][:90]}"))
        elif t == "surgeon_patch":
            print(_c("33", f"    ✎ surgeon: {ev['diff_explanation'][:100]}"))
        elif t == "candidate_delivered":
            print(_c("1;32", "\n✅ DELIVERED — verified by the gauntlet\n"))
        elif t == "floor_reached":
            print(_c("1;33", f"\n⚠ FLOOR — best partial; unverified: {ev['unverified_property']}\n"))
        elif t == "run_error":
            print(_c("1;31", f"\n✗ ERROR: {ev['message']}\n"))
        elif t == "metrics" and verbose:
            print(_c("90", f"      {ev['tokens_per_sec']:.0f} tok/s · {ev['tokens_used']} tok total"))

    return sink
