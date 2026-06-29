"""Build a 'product-build' benchmark: real multi-component modules, not algorithm puzzles.

Each task asks the system to BUILD a working software component (an expression evaluator, a
templating engine, an LRU cache, a sliding-window rate limiter, a URL router, a CSV parser) —
genuine SWE: state, multiple internal parts, and the nasty edge cases (operator precedence,
nested lookups, eviction order, window boundaries, quoted commas) where one-shot code looks
right but breaks.

Each product ships a reference implementation AND a `def check(candidate)` harness; this script
VALIDATES that the reference passes its own checker (so the hidden tests aren't buggy) before
writing crucible/bench/data/products.jsonl. The loop never sees the checker.

    python -m crucible.bench.make_products
    python -m crucible.bench.run_offline --problems crucible/bench/data/products.jsonl
"""

from __future__ import annotations

import json
import os

from ..oracle import harness
from ..oracle.sandbox import get_sandbox

PRODUCTS: list[dict] = []


def product(id, function_name, prompt, reference, checker):
    PRODUCTS.append(
        {"id": id, "function_name": function_name, "prompt": prompt.strip(),
         "reference": reference, "checker": checker, "difficulty": "Product"}
    )


# ── 1. expression evaluator ───────────────────────────────────────────────────
product(
    "calculator", "calculate",
    """
Build an arithmetic expression evaluator: `def calculate(expr: str) -> float`.
Support +, -, *, / with correct precedence (*/ before +-), parentheses for grouping, unary
plus/minus (e.g. -5, 2*-3, -(3+4)), integers and decimals, and arbitrary spaces. Division is
floating-point. Return the numeric result as a float. Inputs are always syntactically valid.
""",
    '''
def calculate(expr: str) -> float:
    s = expr.replace(" ", ""); pos = 0
    def peek(): return s[pos] if pos < len(s) else ""
    def num():
        nonlocal pos; st = pos
        while pos < len(s) and (s[pos].isdigit() or s[pos] == "."): pos += 1
        return float(s[st:pos])
    def factor():
        nonlocal pos
        if peek() == "+": pos += 1; return factor()
        if peek() == "-": pos += 1; return -factor()
        if peek() == "(":
            pos += 1; v = expr_(); pos += 1; return v
        return num()
    def term():
        nonlocal pos; v = factor()
        while peek() in ("*", "/"):
            op = peek(); pos += 1; r = factor(); v = v * r if op == "*" else v / r
        return v
    def expr_():
        nonlocal pos; v = term()
        while peek() in ("+", "-"):
            op = peek(); pos += 1; r = term(); v = v + r if op == "+" else v - r
        return v
    return expr_()
''',
    '''
def check(candidate):
    eq = lambda a, b: abs(a - b) < 1e-9
    assert eq(candidate("2+3*4"), 14.0)
    assert eq(candidate("(2+3)*4"), 20.0)
    assert eq(candidate("-5+3"), -2.0)
    assert eq(candidate("2*-3"), -6.0)
    assert eq(candidate("-(3+4)"), -7.0)
    assert eq(candidate("10/4"), 2.5)
    assert eq(candidate("2 + 3 * 4 - 1"), 13.0)
    assert eq(candidate("((1+2)*(3+4))"), 21.0)
    assert eq(candidate("100/5/2"), 10.0)
    assert eq(candidate("3.5*2"), 7.0)
    assert eq(candidate("2*3+4*5"), 26.0)
    assert eq(candidate("1-2-3"), -4.0)
''',
)

# ── 2. templating engine ──────────────────────────────────────────────────────
product(
    "templating_engine", "render",
    """
Build a tiny templating engine: `def render(template: str, context: dict) -> str`.
Replace every `{{ key }}` placeholder (any surrounding spaces allowed) with `str(context[key])`.
Support dotted paths for nested dicts: `{{a.b}}` resolves `context["a"]["b"]`. If a key (or any
part of a dotted path) is missing, replace the placeholder with the empty string. Text outside
placeholders is returned unchanged; multiple placeholders are all replaced.
""",
    '''
import re
def render(template: str, context: dict) -> str:
    def look(key):
        cur = context
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur: cur = cur[part]
            else: return ""
        return str(cur)
    return re.sub(r"\\{\\{\\s*([\\w.]+)\\s*\\}\\}", lambda m: look(m.group(1)), template)
''',
    '''
def check(candidate):
    assert candidate("Hi {{name}}", {"name": "Al"}) == "Hi Al"
    assert candidate("{{a.b}}", {"a": {"b": 1}}) == "1"
    assert candidate("{{ x }}", {"x": "y"}) == "y"
    assert candidate("{{missing}}", {}) == ""
    assert candidate("{{a.z}}", {"a": {"b": 1}}) == ""
    assert candidate("{{y}} {{y}}", {"y": "z"}) == "z z"
    assert candidate("no vars here", {"x": 1}) == "no vars here"
    assert candidate("[{{a}}][{{b}}]", {"a": 1, "b": 2}) == "[1][2]"
    assert candidate("{{u.name}}!", {"u": {"name": "Sam"}}) == "Sam!"
''',
)

# ── 3. URL router ─────────────────────────────────────────────────────────────
product(
    "url_router", "match_route",
    """
Build a URL router matcher: `def match_route(routes: list[str], path: str) -> dict | None`.
Each route is a pattern like `/users/:id/posts/:pid`; a segment starting with `:` is a named
parameter, others are static. Match `path` against the routes IN ORDER and return a dict of
{param_name: value} for the first route whose segments all match (static segments must be equal,
params capture the path segment). The number of segments must match. A purely-static match
returns an empty dict {}. Return None if no route matches. Leading/trailing slashes and empty
segments are ignored (split on '/').
""",
    '''
def match_route(routes, path):
    pseg = [p for p in path.split("/") if p != ""]
    for route in routes:
        rseg = [r for r in route.split("/") if r != ""]
        if len(rseg) != len(pseg): continue
        params, ok = {}, True
        for r, p in zip(rseg, pseg):
            if r.startswith(":"): params[r[1:]] = p
            elif r != p: ok = False; break
        if ok: return params
    return None
''',
    '''
def check(candidate):
    R = ["/users/:id/posts/:pid", "/users/:id", "/about", "/"]
    assert candidate(R, "/users/5/posts/9") == {"id": "5", "pid": "9"}
    assert candidate(R, "/users/42") == {"id": "42"}
    assert candidate(R, "/about") == {}
    assert candidate(R, "/nope") is None
    assert candidate(R, "/users/1/posts") is None
    assert candidate(["/a/:x", "/a/b"], "/a/b") == {"x": "b"}   # first match wins
    assert candidate(["/files/:name"], "/files/report.pdf") == {"name": "report.pdf"}
    assert candidate(R, "/users/7/") == {"id": "7"}
''',
)

# ── 4. LRU cache (stateful, via an op-log) ────────────────────────────────────
product(
    "lru_cache", "lru_cache_ops",
    """
Build an LRU (least-recently-used) cache, exercised through an operation log:
`def lru_cache_ops(capacity: int, ops: list) -> list`.
`ops` is a list where each item is either `["put", key, value]` or `["get", key]`. Apply them in
order to an LRU cache holding at most `capacity` items. `get` returns the value or -1 if absent.
Both `get` and `put` mark a key as most-recently-used. When a `put` exceeds capacity, evict the
least-recently-used key. Return the list of results of the `get` operations, in order.
""",
    '''
from collections import OrderedDict
def lru_cache_ops(capacity, ops):
    cache = OrderedDict(); out = []
    for op in ops:
        if op[0] == "put":
            k, v = op[1], op[2]
            if k in cache: cache.move_to_end(k)
            cache[k] = v
            if len(cache) > capacity: cache.popitem(last=False)
        else:
            k = op[1]
            if k in cache: cache.move_to_end(k); out.append(cache[k])
            else: out.append(-1)
    return out
''',
    '''
def check(candidate):
    # classic LeetCode LRU trace
    ops = [["put",1,1],["put",2,2],["get",1],["put",3,3],["get",2],["put",4,4],["get",1],["get",3],["get",4]]
    assert candidate(2, ops) == [1, -1, -1, 3, 4]
    assert candidate(1, [["put",1,1],["put",2,2],["get",1],["get",2]]) == [-1, 2]
    assert candidate(2, [["get",9]]) == [-1]
    # get refreshes recency: 1 should survive the eviction
    assert candidate(2, [["put",1,1],["put",2,2],["get",1],["put",3,3],["get",2],["get",1]]) == [1, -1, 1]
    # overwrite existing key updates value, not size
    assert candidate(2, [["put",1,1],["put",1,10],["get",1]]) == [10]
''',
)

# ── 5. sliding-window rate limiter (stateful, via timestamps) ─────────────────
product(
    "rate_limiter", "rate_limiter",
    """
Build a sliding-window rate limiter: `def rate_limiter(limit: int, window: int, events: list) -> list[bool]`.
`events` is a list of integer timestamps in non-decreasing order. Process them in order; for each,
decide whether it is ALLOWED. An event at time t is allowed if, counting only previously-ALLOWED
events whose timestamp is strictly greater than t - window (i.e. still inside the window), there
are fewer than `limit` of them — then this event is allowed and itself counts. Otherwise it is
rejected and does NOT count toward future windows. Return the list of booleans (allowed?) per event.
""",
    '''
def rate_limiter(limit, window, events):
    allowed = []; res = []
    for t in events:
        allowed = [ts for ts in allowed if ts > t - window]
        if len(allowed) < limit:
            allowed.append(t); res.append(True)
        else:
            res.append(False)
    return res
''',
    '''
def check(candidate):
    # limit 2 per window 10
    assert candidate(2, 10, [0, 1, 2]) == [True, True, False]
    # window-edge OFF-BY-ONE: at t=9 the event at 0 is still inside (0 > 9-10=-1) → 2 present → reject
    assert candidate(2, 10, [0, 5, 9]) == [True, True, False]
    # at t=10 the event at 0 exits exactly (0 > 10-10=0 is False) → only 1 present → allow
    assert candidate(2, 10, [0, 5, 10]) == [True, True, True]
    assert candidate(1, 5, [0, 4, 5, 10]) == [True, False, True, True]
    assert candidate(3, 100, [0, 0, 0, 0]) == [True, True, True, False]
    # rejected events don't consume the window
    assert candidate(1, 10, [0, 1, 2, 100]) == [True, False, False, True]
''',
)

# ── 6. CSV parser (quoting) ───────────────────────────────────────────────────
product(
    "csv_parser", "parse_csv",
    r"""
Build a CSV parser: `def parse_csv(text: str) -> list[list[str]]`.
Split into rows on newlines and fields on commas, BUT a field may be wrapped in double quotes,
in which case it may contain commas and newlines literally, and a doubled quote ("") inside a
quoted field means a single literal quote. Return a list of rows, each a list of field strings.
The empty string returns []. A trailing field/row counts (e.g. "a," → [["a", ""]]).
""",
    '''
def parse_csv(text):
    if text == "": return []
    rows, row, field = [], [], ""
    i, n, q = 0, len(text), False
    while i < n:
        c = text[i]
        if q:
            if c == '"':
                if i + 1 < n and text[i+1] == '"': field += '"'; i += 2; continue
                q = False; i += 1; continue
            field += c; i += 1; continue
        if c == '"': q = True; i += 1; continue
        if c == ',': row.append(field); field = ""; i += 1; continue
        if c == '\\n': row.append(field); rows.append(row); row = []; field = ""; i += 1; continue
        if c == '\\r': i += 1; continue
        field += c; i += 1
    row.append(field); rows.append(row)
    return rows
''',
    r'''
def check(candidate):
    assert candidate("a,b,c") == [["a", "b", "c"]]
    assert candidate('a,"b,c",d') == [["a", "b,c", "d"]]
    assert candidate('"he said ""hi"""') == [['he said "hi"']]
    assert candidate("x,y\n1,2") == [["x", "y"], ["1", "2"]]
    assert candidate("a,") == [["a", ""]]
    assert candidate("") == []
    assert candidate('"line1\nline2",b') == [["line1\nline2", "b"]]
    assert candidate("p,q,r\ns,t,u") == [["p", "q", "r"], ["s", "t", "u"]]
''',
)


def main() -> int:
    sandbox = get_sandbox()
    print(f"validating {len(PRODUCTS)} product checkers against their reference impls…\n")
    ok = True
    out = []
    for p in PRODUCTS:
        program = harness.check_program(p["reference"], p["function_name"], p["checker"], harness.BENCH_PREAMBLE)
        res = sandbox.run_python(program, timeout=15.0)
        parsed = harness.parse_result(res.stdout, res.nonce)
        status = parsed["status"] if parsed else "crash"
        detail = (parsed or {}).get("detail", (res.stderr or "")[-160:])
        mark = "OK " if status == "pass" else "BAD"
        print(f"  [{mark}] {p['id']:<20} {('' if status=='pass' else detail)}")
        if status != "pass":
            ok = False
        out.append({"id": p["id"], "prompt": p["prompt"], "function_name": p["function_name"],
                    "hidden_checker": p["checker"], "difficulty": p["difficulty"]})

    if not ok:
        print("\nABORT: a reference failed its own checker — fix the checker before emitting.")
        return 1

    os.makedirs("crucible/bench/data", exist_ok=True)
    path = "crucible/bench/data/products.jsonl"
    with open(path, "w") as f:
        for d in out:
            f.write(json.dumps(d) + "\n")
    print(f"\nall references pass their checkers → wrote {len(out)} products to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
