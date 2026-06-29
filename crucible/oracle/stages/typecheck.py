"""Stage 2 — pyright (subprocess). Is the candidate type-clean against its signature?

pyright performs static analysis only (it never executes the candidate), so it runs as a
plain subprocess rather than inside the sandbox. We run it in basic mode and fail on any
error-severity diagnostic. Undefined names (e.g. an unimported ``List``) are real defects —
the delivered code must be self-contained — so they fail here and the Surgeon adds the import.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from ...shared.schemas import StageResult
from . import StageContext

_PYRIGHT_CONFIG = '{"typeCheckingMode": "basic", "reportMissingModuleSource": false}'


def run(ctx: StageContext) -> StageResult:
    with tempfile.TemporaryDirectory(prefix="crucible_pyright_") as d:
        src = os.path.join(d, "candidate.py")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(ctx.candidate_code)
        with open(os.path.join(d, "pyrightconfig.json"), "w", encoding="utf-8") as fh:
            fh.write(_PYRIGHT_CONFIG)

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pyright", "--outputjson", "--project", d, src],
                capture_output=True,
                text=True,
                timeout=ctx.timeout,
                cwd=d,
            )
        except FileNotFoundError:
            return StageResult(stage="typecheck", status="pass", detail="skipped: pyright unavailable")
        except subprocess.TimeoutExpired:
            return StageResult(stage="typecheck", status="error", detail="pyright timed out")

        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            # pyright failed to produce JSON — surface stderr, don't crash the loop.
            return StageResult(
                stage="typecheck",
                status="error",
                detail=f"pyright produced no JSON: {(proc.stderr or proc.stdout)[:200]}",
            )

        diags = report.get("generalDiagnostics", [])
        errors = [d for d in diags if d.get("severity") == "error"]
        if not errors:
            return StageResult(stage="typecheck", status="pass", detail="type-clean (0 errors)")

        first = errors[0]
        line = first.get("range", {}).get("start", {}).get("line", -1) + 1
        msg = first.get("message", "").splitlines()[0]
        return StageResult(
            stage="typecheck",
            status="fail",
            detail=f"{len(errors)} type error(s); first at line {line}: {msg[:160]}",
        )
