"""Full SWE-bench solver: the Crucible verify-first loop running INSIDE each instance's real
environment (the official `swebench/sweb.eval...` image).

Per instance: localize + plan from the issue, the BLIND Adversary writes a pytest test capturing
the issue's full intended behavior, the Implementer makes MINIMAL search/replace edits, and the
oracle applies the patch + the adversary test in the instance container and runs them — plus a
baseline-diff regression check (only NEW failures count). The Surgeon repairs until the adversary
test passes with no regressions. The loop NEVER sees FAIL_TO_PASS; the final git diff is the patch.

    python -m crucible.bench.swebench_solve pallets__flask-4045
then score the emitted crucible_preds.jsonl with the official swebench harness.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

from ..agents.control import decide_effort, escalate
from ..agents.repo import build_context, read_files_full, repo_adversary, repo_architect, repo_editor
from ..agents.runtime import AgentContext
from ..oracle.repo_runtime import apply_edits
from ..orchestrator.budget import Budget
from ..orchestrator.console import make_console_sink

ROWS = {r["instance_id"]: r for r in json.load(open("/tmp/claude-1000/swb_lite.json"))} \
    if os.path.exists("/tmp/claude-1000/swb_lite.json") else {}

_FAILED_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s|$)", re.M)


def image_for(iid: str) -> str:
    out = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                         capture_output=True, text=True).stdout
    key = iid.split("__")[-1]  # e.g. flask-4045
    for line in out.splitlines():
        if "sweb.eval" in line and key in line:
            return line
    raise RuntimeError(f"no cached instance image for {iid} (run the harness once to build it)")


def env_python(image: str) -> str:
    r = subprocess.run(["docker", "run", "--rm", image, "bash", "-lc", "ls /opt/miniconda3/envs"],
                       capture_output=True, text=True)
    envs = [e for e in r.stdout.split() if e]
    if "testbed" in envs:
        return "/opt/miniconda3/envs/testbed/bin/python"
    if envs:
        return f"/opt/miniconda3/envs/{envs[0]}/bin/python"
    return "python"


def extract_testbed(image: str) -> str:
    d = tempfile.mkdtemp(prefix="swbsolve_")
    cid = subprocess.run(["docker", "create", image], capture_output=True, text=True).stdout.strip()
    try:
        subprocess.run(["docker", "cp", f"{cid}:/testbed/.", d], capture_output=True)
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
    return d


def run_in_image(image: str, py: str, patch: str, add_files: dict[str, str], pytest_args: str,
                 timeout: float = 240.0) -> tuple[int, str]:
    """Fresh container from the pristine image: apply `patch`, drop `add_files`, run pytest."""
    with tempfile.TemporaryDirectory(prefix="cru_") as cru:
        with open(os.path.join(cru, "patch.diff"), "w") as f:
            f.write(patch or "")
        manifest = []
        for i, (path, content) in enumerate(add_files.items()):
            fn = f"add_{i}.py"
            with open(os.path.join(cru, fn), "w") as f:
                f.write(content)
            manifest.append((fn, path))
        copy_cmds = " && ".join(f"mkdir -p $(dirname {p}) && cp /cru/{fn} {p}" for fn, p in manifest)
        script = (
            "cd /testbed && "
            "(test -s /cru/patch.diff && (git apply /cru/patch.diff || patch -p1 < /cru/patch.diff) || true) && "
            + (copy_cmds + " && " if copy_cmds else "")
            + f"{py} -m pytest {pytest_args} -p no:cacheprovider -o addopts='' -W ignore --no-header -q -rfE 2>&1 || true"
        )
        r = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{cru}:/cru", image, "bash", "-lc", script],
            capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")


def failing_ids(output: str) -> set[str]:
    return set(_FAILED_RE.findall(output))


def regression_targets(changed_paths: list[str]) -> list[str]:
    """Map changed source files to their existing test files (best-effort)."""
    targets = []
    for p in changed_paths:
        base = os.path.basename(p)[:-3] if p.endswith(".py") else ""
        for cand in (f"tests/test_{base}.py", f"test_{base}.py", f"tests/test_{base}s.py"):
            targets.append(cand)
    return targets


def solve(iid: str, sink) -> str:
    inst = ROWS[iid]
    image = image_for(iid)
    py = env_python(image)
    testbed = extract_testbed(image)
    ctx = AgentContext.create(sink=sink, budget=Budget(max_tokens=5_000_000, max_iters=10, max_seconds=3000))
    em = ctx.emitter
    em.run_start(f"[swebench] {iid}")
    try:
        issue = inst["problem_statement"].strip()
        task = (issue + "\n\nFix the SOURCE only (never tests). Reason about the FULL behavior the "
                "issue implies, including edge cases it mentions, not just the literal example.")
        # self-optimizing reasoning: a controller agent picks the starting effort from difficulty
        effort = decide_effort(task, ctx).effort
        context = build_context(testbed, task, max_files=16)
        plan = repo_architect(task, context, ctx, reasoning=effort)
        changed = [c.path for c in plan.files_to_change if "test" not in c.path.lower()]
        if not changed:
            changed = [c.path for c in plan.files_to_change]

        existing_targets = [t for t in regression_targets(changed)
                            if os.path.isfile(os.path.join(testbed, t))]

        # blind Adversary: give it the FULL source + the existing tests so it matches the repo's
        # conventions (exact exception types) and covers EVERY case the issue implies.
        adv_ctx = read_files_full(testbed, changed + existing_targets, total_cap=60000)
        adv_task = (task + "\n\nWrite a RIGOROUS pytest test matching this repo's existing test "
                    "conventions and the EXACT exception types it uses. Cover EVERY behavior the issue "
                    "implies — including any related case it mentions — not just the literal example.")
        adv_path = "tests/test_crucible_swe.py"
        # the test is the crux — give it at least medium reasoning
        adv_effort = effort if effort in ("medium", "high") else "medium"
        atest = repo_adversary(adv_task, plan, adv_ctx, ctx, reasoning=adv_effort, test_path=adv_path)

        # baseline failures for the regression targets (on the pristine repo)
        baseline = set()
        if existing_targets:
            _, base_out = run_in_image(image, py, "", {}, " ".join(existing_targets))
            baseline = failing_ids(base_out)

        feedback = ""
        last_patch = ""
        edit_effort = effort
        while not ctx.budget.exhausted():
            ctx.budget.tick()
            em.iteration(ctx.budget.iters)

            cur = read_files_full(testbed, changed)
            etask = task + (f"\n\nThe previous attempt FAILED verification:\n{feedback[:2500]}" if feedback else "")
            editset = repo_editor(etask, plan, cur, ctx, reasoning=edit_effort)
            edits = [e for e in editset.edits if "test" not in e.path.lower()]
            apply_res = apply_edits(testbed, edits)
            not_applied = [(e.path, e.old_string) for e, (_, ok, _) in zip(edits, apply_res) if not ok]
            patch = subprocess.run(["git", "diff"], cwd=testbed, capture_output=True, text=True).stdout
            last_patch = patch
            if not patch.strip():
                # nothing applied → tell the editor its snippets didn't match, escalate, retry
                feedback = ("NONE of your edits applied — your old_string snippets were not found. "
                            "Copy old_string VERBATIM from the file (exact indentation). Not applied: "
                            + "; ".join(p for p, _ in not_applied)[:600])
                em.emit({"type": "stage_result", "result": {
                    "stage": "apply", "status": "fail", "detail": "no edits applied (old_string mismatch)"}})
                edit_effort = escalate(edit_effort)
                continue

            em.stage_start("verify-in-env")
            # adversary test must pass
            rc_adv, out_adv = run_in_image(image, py, patch, {adv_path: atest.content}, adv_path)
            adv_fail = failing_ids(out_adv)
            adv_ok = (rc_adv == 0) and not adv_fail and ("passed" in out_adv or "error" not in out_adv.lower())
            # regression: no NEW failures vs baseline
            new_reg = set()
            if existing_targets:
                _, out_reg = run_in_image(image, py, patch, {}, " ".join(existing_targets))
                new_reg = failing_ids(out_reg) - baseline
            ok = adv_ok and not new_reg
            em.emit({"type": "stage_result", "result": {
                "stage": "verify-in-env", "status": "pass" if ok else "fail",
                "detail": f"adversary test {'PASS' if adv_ok else 'FAIL'}; "
                          f"new regressions: {len(new_reg)}"}})

            if ok:
                em.candidate_delivered(patch)
                em.run_done("verified", patch, "patch passes the blind adversary test in the real env, no regressions")
                return patch

            feedback = (f"Adversary test result (must pass):\n{out_adv[-1800:]}\n"
                        + (f"\nNEW regressions introduced: {sorted(new_reg)[:6]}" if new_reg else "")
                        + (f"\nNOTE: these edits did not apply (fix old_string): "
                           + "; ".join(p for p, _ in not_applied) if not_applied else ""))
            edit_effort = escalate(edit_effort)   # self-optimize: crank reasoning when stuck
            em.note(f"escalating editor reasoning → {edit_effort}")
        em.floor_reached(last_patch, "verify-in-env")
        return last_patch
    finally:
        subprocess.run(["rm", "-rf", testbed])


def main(argv: list[str]) -> int:
    if not ROWS:
        print("missing /tmp/claude-1000/swb_lite.json", file=sys.stderr)
        return 2
    ids = argv or ["pallets__flask-4045"]
    sink = make_console_sink(verbose=False)
    preds = []
    for iid in ids:
        print(f"\n#### SOLVE {iid} ####", file=sys.stderr)
        try:
            patch = solve(iid, sink)
        except Exception as e:
            import traceback; traceback.print_exc()
            patch = ""
        touched = [l[6:] for l in patch.splitlines() if l.startswith("+++ b/")]
        print(f"  -> patch touches {touched} ({len(patch)} chars)", file=sys.stderr)
        preds.append({"instance_id": iid, "model_name_or_path": "crucible", "model_patch": patch})
    with open("crucible_preds.jsonl", "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    print(f"\nwrote {len(preds)} predictions -> crucible_preds.jsonl", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
