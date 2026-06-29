"""Frontier probe: run Crucible against SWE-bench Lite instances and emit predictions for the
OFFICIAL swebench harness to score. Diagnostic ("what's lacking"), not a tuned submission.

    python -m crucible.bench.swebench_attempt pallets__flask-4045 psf__requests-2317

Per instance: clone the repo at base_commit, let Crucible localize + patch from the GitHub issue
(problem_statement only — it never sees FAIL_TO_PASS), and write the resulting git diff to
predictions.jsonl. Then score with:

    python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite \\
        --predictions_path crucible_preds.jsonl --run_id crucible --max_workers 1 \\
        --instance_ids <ids...>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from ..agents.repo import build_context, read_files_full, repo_architect, repo_editor
from ..agents.runtime import AgentContext
from ..oracle.repo_runtime import apply_edits
from ..orchestrator.console import make_console_sink

ROWS = {r["instance_id"]: r for r in json.load(open("/tmp/claude-1000/swb_lite.json"))} \
    if os.path.exists("/tmp/claude-1000/swb_lite.json") else {}

TASK_SUFFIX = ("\n\nFix the SOURCE code only (do NOT modify or add test files). Make the minimal "
               "change to resolve the issue, consistent with the codebase.")


def clone_at(repo: str, commit: str) -> str:
    d = tempfile.mkdtemp(prefix="swb_")
    url = f"https://github.com/{repo}.git"
    subprocess.run(["git", "clone", "-q", url, d], check=True, capture_output=True)
    subprocess.run(["git", "-c", "advice.detachedHead=false", "checkout", "-q", commit],
                   cwd=d, check=True, capture_output=True)
    return d


def make_patch(instance: dict, ctx: AgentContext) -> str:
    repo_dir = clone_at(instance["repo"], instance["base_commit"])
    try:
        task = instance["problem_statement"].strip() + TASK_SUFFIX
        context = build_context(repo_dir, task, max_files=16)
        plan = repo_architect(task, context, ctx)
        # MINIMAL targeted edits (search/replace) from the FULL current files — no whole-file rewrite
        paths = [c.path for c in plan.files_to_change if "test" not in c.path.lower()]
        full = read_files_full(repo_dir, paths)
        editset = repo_editor(task, plan, full, ctx)
        edits = [e for e in editset.edits if "test" not in e.path.lower()]
        results = apply_edits(repo_dir, edits)
        print("    edits:", [(p, ok, why) for p, ok, why in results], file=sys.stderr)
        diff = subprocess.run(["git", "diff"], cwd=repo_dir, capture_output=True, text=True).stdout
        return diff
    finally:
        subprocess.run(["rm", "-rf", repo_dir])


def main(argv: list[str]) -> int:
    if not ROWS:
        print("missing /tmp/claude-1000/swb_lite.json (instance metadata)", file=sys.stderr)
        return 2
    ids = argv or ["pallets__flask-4045", "psf__requests-2317"]
    sink = make_console_sink(verbose=False)
    preds = []
    for iid in ids:
        if iid not in ROWS:
            print(f"unknown instance {iid}", file=sys.stderr); continue
        print(f"\n#### {iid} ({ROWS[iid]['repo']}) ####", file=sys.stderr)
        ctx = AgentContext.create(sink=sink)
        try:
            patch = make_patch(ROWS[iid], ctx)
        except Exception as e:
            print(f"  generation error: {e}", file=sys.stderr); patch = ""
        touched = [l[6:] for l in patch.splitlines() if l.startswith("+++ b/")]
        print(f"  patch: {len(patch)} chars, touches {touched}", file=sys.stderr)
        preds.append({"instance_id": iid, "model_name_or_path": "crucible", "model_patch": patch})

    with open("crucible_preds.jsonl", "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    print(f"\nwrote {len(preds)} predictions -> crucible_preds.jsonl", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
