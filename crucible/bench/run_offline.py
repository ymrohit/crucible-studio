"""Offline delta runner: vanilla single-shot (Condition A) vs the full Crucible loop
(Condition B), scored pass@1 on each problem's HIDDEN tests (§12).

    python -m crucible.bench.run_offline                 # built-in illustrative set
    python -m crucible.bench.run_offline --limit 3       # quick gate
    python -m crucible.bench.run_offline --only paginate
    python -m crucible.bench.run_offline --problems lcb_post_cutoff.jsonl   # real LCB slice

CRITICAL: the loop NEVER sees the hidden scoring tests. `state_machine.run(prompt)` receives
the prompt only; `hidden_tests` are read solely by the scorer below. Same scaffold for A and
B; they differ only in the loop.
"""

from __future__ import annotations

import argparse
import ast
import json
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Optional

from ..bench.vanilla_baseline import vanilla
from ..oracle import harness
from ..oracle.sandbox import Sandbox, get_sandbox
from ..orchestrator.state_machine import run as crucible_run
from .problems import Problem, get_builtin


def _resolve_fname(code: str, preferred: str) -> Optional[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if preferred in names:
        return preferred
    return harness.first_def_name(code)


def score(code: str, problem: "Problem", sandbox: Sandbox) -> tuple[bool, str]:
    """pass@1: True iff the code passes ALL hidden tests / the hidden checker."""
    if not code.strip():
        return False, "no code produced"
    used = _resolve_fname(code, problem.function_name)
    if not used:
        return False, "no function defined"
    if problem.hidden_checker:
        # Benchmark-provided checker; give it the std-lib preamble the benchmark assumes.
        program = harness.check_program(code, used, problem.hidden_checker, harness.BENCH_PREAMBLE)
    else:
        examples = [
            {"input_repr": i, "expected_repr": e, "boundary_category": ""}
            for i, e in problem.hidden_tests
        ]
        program = harness.examples_program(code, used, examples)
    res = sandbox.run_python(program, timeout=15.0)
    parsed = harness.parse_result(res.stdout, res.nonce)
    if res.timed_out:
        return False, "timed out"
    if not parsed:
        tail = (res.stderr or "").strip().splitlines()
        return False, f"crash: {tail[-1] if tail else 'no result'}"[:80]
    return parsed["status"] == "pass", parsed.get("detail", "")[:80]


@dataclass
class Row:
    id: str
    passA: bool
    passB: bool
    tA: float
    tB: float
    detA: str
    detB: str
    statusB: str


def load_problems(args) -> list[Problem]:
    if args.problems:
        probs = []
        with open(args.problems, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                probs.append(
                    Problem(
                        id=d["id"],
                        prompt=d["prompt"],
                        function_name=d["function_name"],
                        hidden_tests=[tuple(t) for t in d.get("hidden_tests", [])],
                        hidden_checker=d.get("hidden_checker", ""),
                        note=d.get("note", ""),
                        difficulty=d.get("difficulty", ""),
                    )
                )
    else:
        probs = get_builtin()
    if args.only:
        probs = [p for p in probs if p.id == args.only]
    if args.limit:
        probs = probs[: args.limit]
    return probs


def run_pass(problems: list[Problem], sandbox: Sandbox, seed_label: str) -> list[Row]:
    rows: list[Row] = []
    for i, p in enumerate(problems, 1):
        print(f"  {seed_label}[{i}/{len(problems)}] {p.id} …", file=sys.stderr, flush=True)

        # --- Condition A: vanilla single-shot ---
        t0 = time.perf_counter()
        try:
            codeA = vanilla(p.prompt)["code"]
        except Exception as e:
            codeA = ""
            print(f"    vanilla error: {e}", file=sys.stderr)
        tA = time.perf_counter() - t0
        passA, detA = score(codeA, p, sandbox)

        # --- Condition B: full Crucible loop (NEVER sees hidden tests) ---
        t0 = time.perf_counter()
        err_msgs: list[str] = []
        try:
            result = crucible_run(p.prompt, sink=lambda ev: err_msgs.append(ev["message"])
                                  if ev.get("type") == "run_error" else None)
            codeB, statusB = result.code, result.status
            if err_msgs:
                statusB = f"error: {err_msgs[-1][:120]}"
        except Exception as e:
            codeB, statusB = "", f"error: {e}"
        tB = time.perf_counter() - t0
        passB, detB = score(codeB, p, sandbox)

        rows.append(Row(p.id, passA, passB, tA, tB, detA, detB, statusB))
        print(
            f"    A={'PASS' if passA else 'FAIL'} ({tA:.1f}s)  "
            f"B={'PASS' if passB else 'FAIL'} ({tB:.1f}s, {statusB})",
            file=sys.stderr,
        )
    return rows


def _report_single(rows: list[Row], note: bool) -> None:
    print("\n" + "=" * 86)
    print(f"{'problem':<34}{'vanilla(A)':<12}{'crucible(B)':<13}{'A t':<7}{'B t':<8}{'Δ':<10}")
    print("-" * 86)
    for r in rows:
        a = "✅ pass" if r.passA else "❌ fail"
        b = "✅ pass" if r.passB else "❌ fail"
        delta = "↑ recovered" if (not r.passA and r.passB) else ("↓ regressed" if (r.passA and not r.passB) else "")
        print(f"{r.id[:33]:<34}{a:<12}{b:<13}{r.tA:<7.1f}{r.tB:<8.1f}{delta:<10}")
    print("=" * 86)
    n = len(rows)
    pa = sum(r.passA for r in rows)
    pb = sum(r.passB for r in rows)
    rec = sum(1 for r in rows if not r.passA and r.passB)
    reg = sum(1 for r in rows if r.passA and not r.passB)
    print(f"pass@1   vanilla(A): {pa}/{n} ({100*pa/n:.0f}%)   →   crucible(B): {pb}/{n} ({100*pb/n:.0f}%)")
    print(f"recovered (A✗→B✓): {rec}   regressed (A✓→B✗): {reg}   net: {rec - reg:+d}")
    print(f"median wall-clock   A: {statistics.median(r.tA for r in rows):.1f}s   "
          f"B: {statistics.median(r.tB for r in rows):.1f}s")
    print(f"delta: {pb - pa:+d} problem(s) ({100*(pb-pa)/n:+.0f} pts) for Crucible over vanilla")
    if note:
        print("\n(illustrative curated set — see module docstring)")


def _report_multiseed(passes: list[list[Row]]) -> None:
    k = len(passes)
    n = len(passes[0])
    ids = [r.id for r in passes[0]]
    a_rates = {pid: 0 for pid in ids}
    b_rates = {pid: 0 for pid in ids}
    pa_per_seed, pb_per_seed = [], []
    for rows in passes:
        pa_per_seed.append(100 * sum(r.passA for r in rows) / n)
        pb_per_seed.append(100 * sum(r.passB for r in rows) / n)
        for r in rows:
            a_rates[r.id] += int(r.passA)
            b_rates[r.id] += int(r.passB)

    print("\n" + "=" * 78)
    print(f"per-problem solve rate over {k} seeds   (vanilla → crucible)")
    print("-" * 78)
    for pid in sorted(ids, key=lambda p: (b_rates[p] - a_rates[p]), reverse=True):
        arrow = "↑" if b_rates[pid] > a_rates[pid] else ("↓" if b_rates[pid] < a_rates[pid] else " ")
        print(f"  {pid[:46]:<48} {a_rates[pid]}/{k} → {b_rates[pid]}/{k}  {arrow}")
    print("=" * 78)

    def ms(xs):
        return statistics.mean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0)

    ma, sa = ms(pa_per_seed)
    mb, sb = ms(pb_per_seed)
    consistently_recovered = sum(1 for p in ids if b_rates[p] > a_rates[p])
    consistently_regressed = sum(1 for p in ids if b_rates[p] < a_rates[p])
    print(f"seeds: {k}   problems: {n}")
    print(f"pass@1  vanilla(A): {ma:.1f}% ± {sa:.1f}   (per-seed: {[round(x) for x in pa_per_seed]})")
    print(f"pass@1  crucible(B): {mb:.1f}% ± {sb:.1f}   (per-seed: {[round(x) for x in pb_per_seed]})")
    print(f"delta: {mb - ma:+.1f} pts   |   problems improved by B: {consistently_recovered}, "
          f"worsened: {consistently_regressed}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Crucible offline delta: vanilla vs loop")
    ap.add_argument("--limit", type=int, default=0, help="run only the first N problems")
    ap.add_argument("--only", type=str, default="", help="run only the problem with this id")
    ap.add_argument("--problems", type=str, default="", help="path to a JSONL problem set")
    ap.add_argument("--seeds", type=int, default=1, help="run the whole set N times and report mean±std")
    args = ap.parse_args(argv)

    problems = load_problems(args)
    if not problems:
        print("no problems to run", file=sys.stderr)
        return 1

    sandbox = get_sandbox()
    print(f"Crucible offline delta — {len(problems)} problem(s) × {args.seeds} seed(s), "
          f"sandbox={sandbox.kind}\n")

    if args.seeds <= 1:
        rows = run_pass(problems, sandbox, "")
        _report_single(rows, note=not args.problems)
    else:
        passes = []
        for s in range(1, args.seeds + 1):
            print(f"\n──── seed {s}/{args.seeds} ────", file=sys.stderr)
            passes.append(run_pass(problems, sandbox, f"s{s} "))
        _report_multiseed(passes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
