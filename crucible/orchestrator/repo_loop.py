"""Repo-mode orchestrator: plan → (blind) test → implement → verify-in-container → repair, against
a real repository. Delivers a verified git diff (or a clearly-labeled floor). The loop verifies
only against the repo's own tests / the blind Adversary's check — never a hidden judge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import os

from ..agents.repo import (
    build_context, read_files, render_change, repo_adversary, repo_architect,
    repo_implementer, repo_surgeon,
)
from ..agents.control import decide_effort
from ..agents.runtime import AgentContext
from ..agents.visual import visual_qa
from ..oracle import repo_runtime as RT
from ..oracle.visual_runtime import render_screenshot, web_image_available
from ..shared.repo_schemas import RepoChange, RepoFile, RepoPlan
from .budget import Budget
from .events import Sink


def _find_html(repo_dir: str) -> str:
    """Relative path to the main HTML file (prefer index.html), or '' if none."""
    best = ""
    for dp, dns, fns in os.walk(repo_dir):
        dns[:] = [d for d in dns if d not in (".git", "node_modules", "dist", "build")]
        for fn in fns:
            if fn.endswith(".html"):
                rel = os.path.relpath(os.path.join(dp, fn), repo_dir)
                if fn == "index.html" and os.sep not in rel:
                    return rel
                best = best or rel
    return best


@dataclass
class RepoResult:
    status: str                         # "verified" | "floor" | "error"
    plan: Optional[RepoPlan] = None
    change: Optional[RepoChange] = None
    diff: str = ""
    output: str = ""
    budget: Optional[dict] = None
    error: Optional[str] = None


def repo_run(
    repo_path: str,
    task: str,
    *,
    sink: Optional[Sink] = None,
    budget: Optional[Budget] = None,
    timeout: float = 240.0,
    network: bool = True,
    visual: bool = True,
) -> RepoResult:
    ctx = AgentContext.create(
        sink=sink, budget=budget or Budget(max_tokens=2_000_000, max_iters=8, max_seconds=1200)
    )
    emitter = ctx.emitter
    emitter.run_start(f"[repo] {task}")
    plan = None
    repo_dir = None
    try:
        # self-optimizing reasoning: a controller agent sets the effort from task difficulty
        effort = decide_effort(task, ctx).effort
        context = build_context(repo_path, task)
        plan = repo_architect(task, context, ctx, reasoning=effort)
        # investigation: show what the loop decided to touch + how it will verify
        emitter.spec_ready({
            "function_name": task[:80],
            "signature": f"{plan.runtime} · verify: {plan.verify_command}",
            "description": "files to change: " + ", ".join(c.path for c in plan.files_to_change[:8]),
        })

        repo_dir = RT.prepare(repo_path)
        current = read_files(repo_path, [c.path for c in plan.files_to_change])

        test_files: list[RepoFile] = []
        if plan.generate_test and plan.test_path.strip():
            t = repo_adversary(task, plan, context, ctx, reasoning=effort)
            test_files = [RepoFile(path=t.path, content=t.content)]
            emitter.emit({"type": "test_ready", "path": t.path, "content": t.content})

        change = repo_implementer(task, plan, current, ctx)

        best_diff = ""
        while not ctx.budget.exhausted():
            ctx.budget.tick()
            emitter.iteration(ctx.budget.iters)

            RT.reset(repo_dir)
            RT.apply_changes(repo_dir, test_files + change.files)
            emitter.emit({"type": "diff_ready", "diff": RT.git_diff(repo_dir)})

            emitter.stage_start("verify")
            result = RT.verify(repo_dir, plan.runtime, plan.verify_command,
                               timeout=timeout, network=network)
            emitter.emit({"type": "stage_result", "result": {
                "stage": "verify",
                "status": "pass" if result.passed else "fail",
                "detail": f"`{plan.verify_command}` "
                          f"{'passed' if result.passed else 'failed'} ({result.duration:.1f}s)"}})
            emitter.emit({"type": "test_output", "text": (result.output or "")[-3000:], "passed": result.passed})

            if result.passed:
                # Web UI? Add VISUAL QA: render in a real headless browser and let the vision
                # model confirm the UI is actually in place (catches what DOM/logic tests can't).
                html = _find_html(repo_dir) if plan.runtime in ("static", "node") else ""
                if html and visual and web_image_available():
                    emitter.stage_start("visual-qa")
                    png = render_screenshot(repo_dir, html)
                    if png is None:
                        emitter.emit({"type": "stage_result", "result": {
                            "stage": "visual-qa", "status": "pass",
                            "detail": "skipped: could not render a screenshot"}})
                    else:
                        vv = visual_qa(png, task, ctx)
                        emitter.emit({"type": "stage_result", "result": {
                            "stage": "visual-qa",
                            "status": "pass" if vv.looks_correct else "fail",
                            "detail": vv.observed[:80] + (
                                " | issues: " + "; ".join(vv.issues[:3]) if vv.issues else "")}})
                        if not vv.looks_correct:
                            best_diff = RT.git_diff(repo_dir)
                            change = repo_surgeon(
                                change,
                                "Functional tests PASS but VISUAL QA FAILED (a real browser screenshot "
                                "was reviewed).\nObserved: " + vv.observed +
                                "\nVisual issues to fix: " + "; ".join(vv.issues), ctx)
                            continue

                diff = RT.git_diff(repo_dir)
                emitter.candidate_delivered(diff)
                emitter.run_done("verified", diff, "change verified (functional + visual)")
                RT.cleanup(repo_dir)
                return RepoResult("verified", plan, change, diff, result.output, ctx.budget.snapshot())

            best_diff = RT.git_diff(repo_dir)
            change = repo_surgeon(change, result.output, ctx)

        emitter.floor_reached(best_diff, f"verify: {plan.verify_command}")
        emitter.run_done("floor", best_diff, f"budget exhausted: {ctx.budget.reason()}")
        RT.cleanup(repo_dir)
        return RepoResult("floor", plan, change, best_diff, "", ctx.budget.snapshot())

    except Exception as e:
        if repo_dir:
            RT.cleanup(repo_dir)
        emitter.run_error(f"{type(e).__name__}: {e}")
        return RepoResult("error", plan, None, "", "", ctx.budget.snapshot(), str(e))
