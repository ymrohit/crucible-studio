"""Repo-mode CLI — point Crucible at a real repository and a task; it makes verified changes.

    python -m crucible.repo <path-to-repo> "fix the failing rounding in invoice totals"
    python -m crucible.repo <path-to-repo> "add a GET /health endpoint"
    python -m crucible.repo -v <path-to-repo> "add a dark-mode toggle to the page"

It plans against the repo, has a blind QA agent write the check, implements the change, and verifies
by RUNNING the repo's tests / the check in a container — repairing until green. Prints the diff.
"""

from __future__ import annotations

import os
import sys

from .orchestrator.console import make_console_sink
from .orchestrator.repo_loop import repo_run


def main(argv: list[str]) -> int:
    verbose = False
    args = list(argv)
    if args and args[0] in ("-v", "--verbose"):
        verbose = True
        args = args[1:]
    if len(args) < 2:
        print('usage: python -m crucible.repo [-v] <repo-path> "<task>"', file=sys.stderr)
        return 2
    repo_path, task = args[0], " ".join(args[1:])
    if not os.path.isdir(repo_path):
        print(f"not a directory: {repo_path}", file=sys.stderr)
        return 2

    result = repo_run(os.path.abspath(repo_path), task, sink=make_console_sink(verbose=verbose))

    print("\n" + "=" * 72)
    if result.status == "verified":
        print("STATUS: VERIFIED ✅  (change passes the repo's verification)")
    elif result.status == "floor":
        print("STATUS: FLOOR ⚠  (best partial — verification not green)")
    else:
        print(f"STATUS: ERROR ✗  ({result.error})")
        return 1
    print("=" * 72)
    print("\n--- proposed diff ---")
    print(result.diff or "(no diff)")
    if result.budget:
        b = result.budget
        print(f"\n[tokens: {b['tokens_used']}/{b['max_tokens']} · iters: {b['iters']}/{b['max_iters']} · {b['elapsed']}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
