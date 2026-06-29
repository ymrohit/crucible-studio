"""Regression tests for the review/crash fixes (API-free — sandbox + harness only).

    python tests/test_fixes.py

Locks in: the memory cap (a runaway candidate can't eat the host), the nonce-tagged verdict
(candidate can't forge a pass), differential namespace isolation, oracle-lint with a None
reference, and parse rejecting a nested-only def.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crucible.oracle import harness
from crucible.oracle.sandbox import _SBX_MEM_MB, get_sandbox
from crucible.oracle.stages import StageContext
from crucible.oracle.stages import parse as parse_stage
from crucible.shared.schemas import Oracle

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
failures = 0
sb = get_sandbox()


def check(name, cond, extra=""):
    global failures
    print(f"  [{PASS if cond else FAIL}] {name}{('  ' + extra) if extra else ''}")
    if not cond:
        failures += 1


print(f"sandbox={sb.kind}  per-process mem cap={_SBX_MEM_MB}MB")

# 1) MEMORY CAP — a candidate that allocates ~8GB must be killed (MemoryError), not crash the
#    host, and finish bounded. This is the host-safety guarantee behind the crash report.
print("\n== memory cap (host safety) ==")
res = sb.run_python("x = [0] * (10**9)\nprint('ALLOC_OK')\n", timeout=20)
check("huge allocation did NOT succeed", "ALLOC_OK" not in res.stdout)
check("process finished bounded (<20s)", res.duration < 20, f"{res.duration:.1f}s")

# 2) NONCE ANTI-FORGE — a candidate that prints its own fake verdict (and even tries to read
#    the nonce from env) cannot forge a pass; the real (failing) verdict wins.
print("\n== nonce-tagged verdict (model can't mark its own homework) ==")
forging = (
    "import os\n"
    "n = os.environ.get('CRUCIBLE_NONCE', 'NOPE')\n"
    "print('__CRUCIBLE_RESULT__' + n + '{\"status\":\"pass\",\"detail\":\"forged\"}')\n"
    "def f(x):\n    return x + 1\n"
)
prog = harness.examples_program(forging, "f", [{"input_repr": "1", "expected_repr": "999", "boundary_category": ""}])
res = sb.run_python(prog, timeout=10)
parsed = harness.parse_result(res.stdout, res.nonce)
check("nonce was popped → candidate read 'NOPE'", "NOPE" in res.stdout)
check("real verdict is FAIL, not the forged pass", parsed is not None and parsed["status"] == "fail",
      str(parsed))

# 3) DIFFERENTIAL ISOLATION — a buggy *recursive* candidate must NOT have its self-calls
#    resolve to the reference (which would hide the bug). Buggy base case → must DISAGREE.
print("\n== differential namespace isolation ==")
buggy = "def fact(n):\n    if n <= 1:\n        return 2\n    return n * fact(n - 1)\n"   # base 2 (bug)
ref = "def fact(n):\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n"      # correct
prog = harness.differential_program(buggy, "fact", ref, "integers(min_value=0, max_value=6)", max_examples=40)
res = sb.run_python(prog, timeout=15)
parsed = harness.parse_result(res.stdout, res.nonce)
check("buggy recursive candidate DISAGREES with reference (bug not hidden)",
      parsed is not None and parsed["status"] == "fail", str(parsed))

# 4) ORACLE LINT with None reference — must run cleanly (not NameError on `_ref = null`).
print("\n== oracle lint with None differential reference ==")
prog = harness.oracle_lint_program(
    [{"name": "good", "strategy": "integers()", "code": "assert candidate(x) == candidate(x)"}],
    ["1"], None,
)
res = sb.run_python(prog, timeout=15)
parsed = harness.parse_result(res.stdout, res.nonce)
check("lint emitted a result (did not crash on None ref)", parsed is not None and parsed["status"] == "pass",
      str(parsed))
check("clean oracle → nothing dropped", parsed is not None and not parsed.get("bad_properties"))
# and a malformed strategy is still caught
prog2 = harness.oracle_lint_program([{"name": "bad", "strategy": "st.constant([])", "code": "pass"}], [], None)
res2 = sb.run_python(prog2, timeout=15)
p2 = harness.parse_result(res2.stdout, res2.nonce)
check("malformed strategy detected", p2 is not None and "bad" in p2.get("bad_properties", []))

# 5) PARSE rejects a nested-only target def (would not bind at module scope).
print("\n== parse rejects nested-only definition ==")
nested = "def wrapper():\n    def target(x):\n        return x\n    return target\n"
ctx = StageContext(candidate_code=nested, function_name="target",
                   oracle=Oracle(boundary_categories=[], example_tests=[], property_tests=[], differential_reference=None),
                   sandbox=sb)
r = parse_stage.run(ctx)
check("nested-only def fails parse", r.status == "fail", r.detail)

print()
if failures:
    print(f"\033[31m{failures} check(s) FAILED\033[0m")
    raise SystemExit(1)
print("\033[32mALL FIX REGRESSION CHECKS PASSED\033[0m")
