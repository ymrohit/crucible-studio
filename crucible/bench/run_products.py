"""Product-build A/B: for each product request, freeze one spec, then compare
one-shot (vanilla) vs the full Crucible loop — BOTH built to the same spec and BOOT-TESTED
in Docker against the same blind integration test. Isolates the value of the test+repair loop
on real product-building (a running FastAPI service), not algorithm puzzles.

    python -m crucible.bench.run_products
"""

from __future__ import annotations

import sys
import time

from ..agents.base import get_client
from ..agents.product import render_product_spec
from ..bench.vanilla_baseline import extract_code
from ..oracle.product_runtime import ProductRunResult, build_and_test, docker_product_available
from ..orchestrator.product_loop import product_run
from ..shared.product_schemas import ProductFile, ProductSpec

PRODUCTS = [
    "a URL-shortener REST service",
    "an in-memory todo-list REST API with create, list, get, update, and delete",
    "an in-memory key-value store REST API with set, get, delete, and per-key TTL expiry",
    "a paginated notes REST API (create a note, list notes with ?page= and ?size=)",
]

_VANILLA_SYS = (
    "You build a small FastAPI web service from a precise API spec. Output ONE self-contained "
    "Python file (the contents of main.py) defining `app = FastAPI()` implementing every endpoint "
    "and status code exactly. Use only stdlib + fastapi/pydantic/uvicorn; in-memory state. "
    "Respond with only the code in a single ```python block."
)


def vanilla_product(spec: ProductSpec) -> list[ProductFile]:
    client = get_client()
    content, *_ = client.text(_VANILLA_SYS, render_product_spec(spec),
                              temperature=0.6, max_completion_tokens=4000)
    return [ProductFile(path="main.py", content=extract_code(content))]


def _mark(r: ProductRunResult) -> str:
    if r.passed:
        return "✅ pass"
    return "◻ boots, fails" if r.booted else "❌ no boot"


def main(argv: list[str]) -> int:
    if not docker_product_available():
        print("need crucible-product:latest (see docker/product.Dockerfile)", file=sys.stderr)
        return 3
    rows = []
    for i, prompt in enumerate(PRODUCTS, 1):
        print(f"[{i}/{len(PRODUCTS)}] {prompt}", file=sys.stderr, flush=True)
        t0 = time.perf_counter()
        result = product_run(prompt)  # silent
        tB = time.perf_counter() - t0
        spec, oracle = result.spec, result.oracle
        # vanilla one-shot from the SAME frozen spec, boot-tested against the same blind test
        vstatus = "n/a"
        if spec is not None and oracle is not None:
            try:
                vfiles = vanilla_product(spec)
                vres = build_and_test(vfiles, oracle.integration_test, timeout=75)
                vstatus = _mark(vres)
            except Exception as e:
                vstatus = f"err:{type(e).__name__}"
        rows.append((prompt, vstatus, result.status, result.budget["iters"] if result.budget else 0, tB))
        print(f"    vanilla={vstatus}   crucible={result.status} "
              f"(iters={rows[-1][3]}, {tB:.0f}s)", file=sys.stderr)

    print("\n" + "=" * 92)
    print(f"{'product':<52}{'vanilla(1-shot)':<18}{'crucible(loop)':<16}{'iters':<6}")
    print("-" * 92)
    for prompt, v, c, it, tB in rows:
        cm = "✅ verified" if c == "verified" else ("⚠ floor" if c == "floor" else "✗ " + c)
        print(f"{prompt[:50]:<52}{v:<18}{cm:<16}{it:<6}")
    print("=" * 92)
    vpass = sum(1 for r in rows if r[1].startswith("✅"))
    cpass = sum(1 for r in rows if r[2] == "verified")
    n = len(rows)
    print(f"shipped a working, boot-verified service:  vanilla(1-shot) {vpass}/{n}   →   crucible {cpass}/{n}")
    print("(both built to the SAME frozen spec; tested against the SAME blind integration test, in Docker)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
