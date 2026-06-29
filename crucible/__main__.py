"""CLI entry point — runs the full Crucible loop and prints only verified (or floor) output.

    python -m crucible "merge overlapping booking intervals"
    python -m crucible -v "paginate a list into pages of size k"   # verbose metrics
"""

from __future__ import annotations

import sys

from .orchestrator.console import make_console_sink
from .orchestrator.state_machine import run


def main(argv: list[str]) -> int:
    verbose = False
    args = list(argv)
    if args and args[0] in ("-v", "--verbose"):
        verbose = True
        args = args[1:]
    if not args:
        print('usage: python -m crucible [-v] "<coding request>"', file=sys.stderr)
        return 2

    prompt = " ".join(args)
    result = run(prompt, sink=make_console_sink(verbose=verbose))

    print("\n" + "=" * 70)
    if result.status == "verified":
        print("STATUS: VERIFIED ✅  (survived the full gauntlet)")
    elif result.status == "floor":
        print(f"STATUS: FLOOR ⚠  (best partial; unverified stage: {result.unverified_stage})")
    else:
        print(f"STATUS: ERROR ✗  ({result.error})")
        return 1
    print("=" * 70)
    print(result.code)
    if result.budget:
        b = result.budget
        print(f"\n[tokens: {b['tokens_used']}/{b['max_tokens']} · "
              f"iters: {b['iters']}/{b['max_iters']} · {b['elapsed']}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
