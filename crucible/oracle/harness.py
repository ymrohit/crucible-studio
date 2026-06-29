"""Builds the Python programs each runtime stage executes inside the sandbox.

Conventions (pinned here and echoed to the Adversary in agents/adversary.py so tests it
writes are runnable):

  * **example_tests** — ``input_repr`` is the *source of the argument list*: the call is
    literally ``candidate(<input_repr>)``. So a single-list arg is ``"[(1,3),(2,6)]"`` and a
    two-arg call is ``"5, [1,2,3]"``. ``expected_repr`` is evaluated as a literal.
  * **property_tests** — the generated input is bound to ``x``; the test runs
    ``@given(x=<strategy>) def t(x): <code>``. The ``code`` references ``x`` and ``candidate``.
  * **differential_reference** — a full function definition; it is called the same way as the
    candidate over strategy-fuzzed inputs and outputs compared with float-tolerant equality.

Every program prints exactly one result line: ``SENTINEL + json.dumps(result)``. If that line
is absent (crash / timeout / OOM) the stage treats it as an error.
"""

from __future__ import annotations

import json
from typing import Any, Optional

SENTINEL = "__CRUCIBLE_RESULT__"

# Helpers injected into every runtime program. The verdict line is tagged with a secret
# per-run nonce (passed via env, popped here BEFORE any candidate code runs) so candidate
# code cannot forge a passing verdict — it can never learn the nonce. (§3: the model never
# marks its own homework.)
_COMMON = f'''
import json, math, traceback, os as _os
SENTINEL = {SENTINEL!r} + _os.environ.pop("CRUCIBLE_NONCE", "")

def _emit(d):
    print(SENTINEL + json.dumps(d))

def _equalish(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
        except Exception:
            return a == b
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        # list vs tuple is almost always an irrelevant container difference for these
        # problems; compare structurally so it doesn't bury real (value/logic) bugs.
        return len(a) == len(b) and all(_equalish(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_equalish(a[k], b[k]) for k in a)
    return a == b

def _call(f, x):
    """Call f with x; if x is a tuple meant as multiple args, fall back to f(*x)."""
    try:
        return f(x)
    except TypeError as e:
        if isinstance(x, tuple) and ("argument" in str(e) or "positional" in str(e)):
            return f(*x)
        raise
'''


def _bind(function_name: str) -> str:
    return f"candidate = {function_name}\n"


def smoke_program(candidate_code: str, function_name: str, input_repr: str) -> str:
    return f'''{_COMMON}
# === candidate ===
{candidate_code}
{_bind(function_name)}
# === smoke ===
try:
    _out = candidate({input_repr})
    _emit({{"status": "pass", "detail": "ran without crashing; returned " + type(_out).__name__}})
except Exception as e:
    _emit({{"status": "fail", "detail": "crashed on trivial input: " + repr(e),
            "input": {input_repr!r}, "actual": "<raised " + type(e).__name__ + ": " + str(e) + ">"}})
'''


def examples_program(candidate_code: str, function_name: str, examples: list[dict[str, str]]) -> str:
    cases = json.dumps(examples)
    return f'''{_COMMON}
# === candidate ===
{candidate_code}
{_bind(function_name)}
# === examples ===
_cases = {cases}
_fail = None
_passed = 0
for _c in _cases:
    _inp = _c["input_repr"]; _exp_src = _c["expected_repr"]; _cat = _c.get("boundary_category","")
    try:
        _expected = eval(_exp_src)
    except Exception as e:
        # An unparseable expected value is a bad test, surfaced as an error.
        _fail = {{"status": "error", "detail": "could not eval expected " + repr(_exp_src) + ": " + repr(e)}}
        break
    try:
        _actual = eval("candidate(" + _inp + ")")
    except Exception as e:
        _fail = {{"status": "fail", "detail": "[" + _cat + "] candidate raised on " + _inp,
                  "input": _inp, "actual": "<raised " + type(e).__name__ + ": " + str(e) + ">",
                  "expected": _exp_src}}
        break
    if not _equalish(_actual, _expected):
        _fail = {{"status": "fail", "detail": "[" + _cat + "] mismatch",
                  "input": _inp, "actual": repr(_actual), "expected": _exp_src}}
        break
    _passed += 1
if _fail is None:
    _emit({{"status": "pass", "detail": str(_passed) + "/" + str(len(_cases)) + " example tests passed"}})
else:
    _emit(_fail)
'''


def properties_program(
    candidate_code: str,
    function_name: str,
    strategy: str,
    code: str,
    max_examples: int = 100,
) -> str:
    # Indent the user's property body into the test function.
    body = "\n".join("        " + line for line in code.splitlines()) or "        pass"
    return f'''{_COMMON}
from hypothesis import given, settings, HealthCheck, strategies as st
from hypothesis.strategies import *
# === candidate ===
{candidate_code}
{_bind(function_name)}
# === property ===
FAIL = {{}}
try:
    _strat = eval({strategy!r})
except Exception as e:
    _emit({{"status": "error", "detail": "bad strategy " + {strategy!r} + ": " + repr(e)}})
    raise SystemExit(0)

@settings(max_examples={max_examples}, derandomize=True, deadline=None, database=None,
          suppress_health_check=list(HealthCheck))
@given(x=_strat)
def _t(x):
    try:
{body}
    except Exception:
        FAIL["input"] = repr(x)
        try:
            FAIL["actual"] = repr(_call(candidate, x))
        except Exception as _e:
            FAIL["actual"] = "<raised " + type(_e).__name__ + ": " + str(_e) + ">"
        raise

try:
    _t()
    _emit({{"status": "pass", "detail": "property held over {max_examples} examples"}})
except SystemExit:
    raise
except Exception as e:
    _emit({{"status": "fail",
            "detail": "property violated: " + type(e).__name__ + ": " + str(e)[:200],
            "input": FAIL.get("input"), "actual": FAIL.get("actual"),
            "expected": "<invariant to hold>"}})
'''


def differential_program(
    candidate_code: str,
    function_name: str,
    reference_code: str,
    strategy: str,
    max_examples: int = 200,
) -> str:
    return f'''{_COMMON}
from hypothesis import given, settings, HealthCheck, strategies as st
from hypothesis.strategies import *
# === candidate ===
{candidate_code}
{_bind(function_name)}
# === reference (ISOLATED namespace — candidate self-recursion and shared helper names must
# NOT resolve to the reference, and vice-versa, or the differential compares a hybrid) ===
_ref_src = {reference_code!r}
_ref_ns = {{}}
try:
    exec(compile(_ref_src, "<reference>", "exec"), _ref_ns)
except Exception as e:
    _emit({{"status": "error", "detail": "differential reference failed to load: " + repr(e)}})
    raise SystemExit(0)
_ref_fns = [v for k, v in _ref_ns.items() if callable(v) and not k.startswith("__")]
reference = None
for _f in _ref_fns:
    if getattr(_f, "__name__", "") == "{function_name}":
        reference = _f
        break
if reference is None and _ref_fns:
    reference = _ref_fns[-1]
if reference is None:
    _emit({{"status": "error", "detail": "no reference function found in differential_reference"}})
    raise SystemExit(0)

try:
    _strat = eval({strategy!r})
except Exception as e:
    _emit({{"status": "error", "detail": "bad differential strategy: " + repr(e)}})
    raise SystemExit(0)

FAIL = {{}}

@settings(max_examples={max_examples}, derandomize=True, deadline=None, database=None,
          suppress_health_check=list(HealthCheck))
@given(x=_strat)
def _t(x):
    _a = _call(candidate, x)
    _b = _call(reference, x)
    if not _equalish(_a, _b):
        FAIL["input"] = repr(x); FAIL["actual"] = repr(_a); FAIL["expected"] = repr(_b)
        raise AssertionError("candidate disagrees with reference")

try:
    _t()
    _emit({{"status": "pass", "detail": "agreed with reference over {max_examples} fuzzed inputs"}})
except SystemExit:
    raise
except Exception as e:
    _emit({{"status": "fail", "detail": "differential mismatch vs reference",
            "input": FAIL.get("input"), "actual": FAIL.get("actual"),
            "expected": FAIL.get("expected")}})
'''


def oracle_lint_program(
    properties: list[dict[str, str]],
    expecteds: list[str],
    reference: Optional[str],
) -> str:
    """Program that checks whether each oracle test is *itself* well-formed (independent of any
    candidate): strategies build, property bodies compile, expected literals eval, and the
    differential reference compiles to a callable. Emits the names/indices of broken tests so
    the orchestrator can drop them before the loop wastes iterations on a bad oracle."""
    props = json.dumps(properties)
    exps = json.dumps(expecteds)
    ref = repr(reference)  # valid Python literal for both None and a code string (NOT json: None→null crashes)
    return f'''{_COMMON}
from hypothesis import strategies as st
from hypothesis.strategies import *
_props = {props}
_exps = {exps}
_ref = {ref}
bad_properties = []
for _p in _props:
    try:
        eval(_p["strategy"])
        _body = "\\n".join("    " + ln for ln in _p["code"].splitlines()) or "    pass"
        compile("def _t(x, candidate=None):\\n" + _body, "<prop>", "exec")
    except Exception:
        bad_properties.append(_p["name"])
bad_examples = []
for _i, _e in enumerate(_exps):
    try:
        eval(_e)
    except Exception:
        bad_examples.append(_i)
bad_reference = False
if _ref:
    try:
        _ns = {{}}
        exec(compile(_ref, "<ref>", "exec"), _ns)
        if not any(callable(v) for k, v in _ns.items() if not k.startswith("__")):
            bad_reference = True
    except Exception:
        bad_reference = True
_emit({{"status": "pass", "bad_properties": bad_properties,
        "bad_examples": bad_examples, "bad_reference": bad_reference}})
'''


def first_def_name(code: str) -> Optional[str]:
    """Name of the first top-level function in ``code`` (best-effort, for ad-hoc execution)."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    # fall back to any nested def
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return None


def call_program(code: str, function_name: str, input_repr: str) -> str:
    """Program that calls ``function_name(<input_repr>)`` and emits its repr — used by the
    UI 'feed both the counterexample' comparison."""
    return f'''{_COMMON}
{code}
candidate = {function_name}
try:
    _out = candidate({input_repr})
    _emit({{"ok": True, "output": repr(_out)}})
except Exception as e:
    _emit({{"ok": False, "output": "<raised " + type(e).__name__ + ": " + str(e) + ">"}})
'''


# Standard library context benchmark harnesses (LeetCode/HumanEval) assume is present.
# Used ONLY for hidden-test scoring (so vanilla isn't penalized for import hygiene the
# benchmark itself provides) — never for the gauntlet, where candidates must be self-contained.
BENCH_PREAMBLE = (
    "from typing import *\n"
    "from collections import *\n"
    "from math import *\n"
    "from functools import *\n"
    "from itertools import *\n"
    "from heapq import *\n"
    "from bisect import *\n"
    "import re, string, random, operator\n"
    "inf = float('inf')\n"
)


def check_program(
    code: str, function_name: str, checker_code: str, preamble: str = ""
) -> str:
    """Program that runs a benchmark's own ``def check(candidate)`` harness against the
    candidate (HumanEval / LeetCode style). Pass iff check() raises nothing."""
    return f'''{_COMMON}
{preamble}
# === candidate ===
{code}
candidate = {function_name}
# === hidden checker ===
{checker_code}
try:
    check(candidate)
    _emit({{"status": "pass", "detail": "all hidden checks passed"}})
except AssertionError as e:
    _emit({{"status": "fail", "detail": "assertion failed: " + str(e)[:180]}})
except Exception as e:
    _emit({{"status": "fail", "detail": type(e).__name__ + ": " + str(e)[:180]}})
'''


def parse_result(stdout: str, nonce: str = "") -> Optional[dict[str, Any]]:
    """Extract the last verdict line tagged with SENTINEL+nonce from program stdout.

    The nonce (from the sandbox) means a line the candidate printed itself — which cannot
    contain the nonce — is never accepted as the verdict.
    """
    marker = SENTINEL + nonce
    result: Optional[dict[str, Any]] = None
    for line in stdout.splitlines():
        if line.startswith(marker):
            try:
                result = json.loads(line[len(marker):])
            except json.JSONDecodeError:
                continue
    return result
