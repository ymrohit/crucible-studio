"""Product-mode CLI — Crucible builds a real, runnable FastAPI service and verifies it by
booting it in a container and running the blind Adversary's integration tests.

    python -m crucible.product "a URL-shortener REST service"
    python -m crucible.product -v "an in-memory todo list API with CRUD"
"""

from __future__ import annotations

import sys

from .oracle.product_runtime import docker_product_available
from .orchestrator.console import make_console_sink
from .orchestrator.product_loop import product_run


def main(argv: list[str]) -> int:
    verbose = False
    args = list(argv)
    if args and args[0] in ("-v", "--verbose"):
        verbose = True
        args = args[1:]
    if not args:
        print('usage: python -m crucible.product [-v] "<product request>"', file=sys.stderr)
        return 2
    if not docker_product_available():
        print("Product mode needs the Docker image 'crucible-product:latest'. Build it with:\n"
              "  docker build -f docker/product.Dockerfile -t crucible-product:latest docker/",
              file=sys.stderr)
        return 3

    prompt = " ".join(args)
    result = product_run(prompt, sink=make_console_sink(verbose=verbose))

    print("\n" + "=" * 72)
    if result.status == "verified":
        print("STATUS: VERIFIED ✅  (service boots and passes the integration tests)")
    elif result.status == "floor":
        print("STATUS: FLOOR ⚠  (best partial — did not fully pass)")
    else:
        print(f"STATUS: ERROR ✗  ({result.error})")
        return 1
    print("=" * 72)
    if result.candidate:
        for f in result.candidate.files:
            print(f"\n----- {f.path} -----\n{f.content}")
    if result.budget:
        b = result.budget
        print(f"\n[tokens: {b['tokens_used']}/{b['max_tokens']} · iters: {b['iters']}/{b['max_iters']} · {b['elapsed']}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
