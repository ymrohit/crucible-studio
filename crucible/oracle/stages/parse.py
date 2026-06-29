"""Stage 1 — AST parse. Is the candidate syntactically valid and does it define the
target function? Pure static check (no execution), safe to run in-process.
"""

from __future__ import annotations

import ast

from ...shared.schemas import StageResult
from . import StageContext


def run(ctx: StageContext) -> StageResult:
    try:
        tree = ast.parse(ctx.candidate_code)
    except SyntaxError as e:
        return StageResult(
            stage="parse",
            status="fail",
            detail=f"SyntaxError: {e.msg} at line {e.lineno}",
        )

    # Only TOP-LEVEL definitions count: the harness binds `candidate = <function_name>` at
    # module scope. The target may be a function OR a class (a stateful product like LRUCache
    # is bound as the class and driven by the Adversary's property tests).
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    if ctx.function_name not in defined:
        found = ", ".join(sorted(defined)) or "none"
        return StageResult(
            stage="parse",
            status="fail",
            detail=f"'{ctx.function_name}' is not defined at top level (found: {found})",
        )
    return StageResult(stage="parse", status="pass", detail="syntax valid; target function defined")
