"""Repo-mode agents: plan a change against a real repo, blind-test it, implement it, repair it.

Anti-collusion holds: the Adversary sees the plan + repo interfaces but NOT the implementer's new
code; the Implementer sees the plan + repo but NOT the test.
"""

from __future__ import annotations

import os
from typing import Optional

from ..shared.repo_schemas import RepoChange, RepoEditSet, RepoPlan, RepoTest
from . import load_prompt
from .runtime import AgentContext, invoke

_ARCHITECT = load_prompt("repo_architect")
_ADVERSARY = load_prompt("repo_adversary")
_IMPLEMENTER = load_prompt("repo_implementer")
_SURGEON = load_prompt("repo_surgeon")
_EDITOR = load_prompt("repo_editor")

_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
              ".pytest_cache", ".mypy_cache", ".next", ".cache", ".idea"}
_ALWAYS = ("readme", "package.json", "pyproject.toml", "setup.py", "requirements.txt", "index.html")


def _iter_files(root: str):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            full = os.path.join(dp, fn)
            yield os.path.relpath(full, root), full


def build_context(repo_path: str, task: str, max_files: int = 14, per_file_bytes: int = 4000) -> str:
    """File tree + the contents of the files most relevant to the task (capped)."""
    all_files = list(_iter_files(repo_path))
    tree = "\n".join(sorted(rel for rel, _ in all_files)[:200])

    words = {w.lower() for w in task.replace("/", " ").split() if len(w) > 2}

    def score(rel: str, full: str) -> int:
        low = rel.lower()
        s = sum(3 for w in words if w in low)
        if any(a in low for a in _ALWAYS):
            s += 5
        if "test" in low:
            s += 2
        try:
            if os.path.getsize(full) < 40_000:
                head = open(full, encoding="utf-8", errors="ignore").read(4000).lower()
                s += sum(1 for w in words if w in head)
        except OSError:
            pass
        return s

    ranked = sorted(all_files, key=lambda rf: score(rf[0], rf[1]), reverse=True)
    blobs = []
    for rel, full in ranked[:max_files]:
        try:
            content = open(full, encoding="utf-8", errors="ignore").read(per_file_bytes)
        except OSError:
            continue
        blobs.append(f"### FILE: {rel}\n```\n{content}\n```")
    return f"REPO FILE TREE:\n{tree}\n\nRELEVANT FILES:\n" + "\n\n".join(blobs)


def read_files(repo_path: str, paths: list[str], per_file_bytes: int = 8000) -> str:
    out = []
    for p in paths:
        full = os.path.join(repo_path, p)
        if os.path.isfile(full):
            out.append(f"### FILE: {p}\n```\n{open(full, encoding='utf-8', errors='ignore').read(per_file_bytes)}\n```")
        else:
            out.append(f"### FILE: {p}\n(does not exist yet — create it)")
    return "\n\n".join(out)


def read_files_full(repo_path: str, paths: list[str], total_cap: int = 48000) -> str:
    """Full content of the listed files (for exact search/replace editing), capped overall."""
    out, used = [], 0
    for p in paths:
        full = os.path.join(repo_path, p)
        if not os.path.isfile(full):
            out.append(f"### FILE: {p}\n(does not exist yet)")
            continue
        c = open(full, encoding="utf-8", errors="ignore").read()
        if used + len(c) > total_cap:
            c = c[: max(0, total_cap - used)]
        used += len(c)
        out.append(f"### FILE: {p}\n```\n{c}\n```")
    return "\n\n".join(out)


def render_change(change: RepoChange) -> str:
    return "\n\n".join(f"### FILE: {f.path}\n```\n{f.content}\n```" for f in change.files)


def repo_editor(task: str, plan: RepoPlan, full_files: str, ctx: AgentContext,
                reasoning: str | None = None) -> RepoEditSet:
    """Minimal targeted edits (search/replace) — avoids truncating/corrupting large files."""
    items = "\n".join(f"  - {c.path}: {c.intent}" for c in plan.files_to_change)
    user = (
        f"TASK:\n{task}\n\nPLAN: {plan.summary}\nedit these files:\n{items}\n\n"
        f"FULL CURRENT CONTENT:\n{full_files}\n\n"
        "Review the file for EXISTING related validation that the issue's intent should also cover "
        "(e.g. an existing `assert` that should become the same exception). Match the codebase's "
        "exception types. Return minimal search/replace edits (exact old_string snippets)."
    )
    res = invoke(ctx, "implementer", _EDITOR, user, RepoEditSet,
                 reasoning_effort=reasoning, temperature=0.3, max_completion_tokens=32000)
    edits: RepoEditSet = res.parsed  # type: ignore[assignment]
    ctx.emitter.agent_done("implementer", f"{len(edits.edits)} targeted edit(s)")
    return edits


def repo_architect(task: str, context: str, ctx: AgentContext, reasoning: str | None = "medium") -> RepoPlan:
    user = f"TASK:\n{task}\n\n{context}"
    res = invoke(ctx, "architect", _ARCHITECT, user, RepoPlan,
                 reasoning_effort=reasoning, temperature=0.4, max_completion_tokens=32000)
    plan: RepoPlan = res.parsed  # type: ignore[assignment]
    ctx.emitter.spec_ready(plan.model_dump())
    ctx.emitter.agent_done("architect",
                           f"{plan.runtime} · {len(plan.files_to_change)} file(s) · verify: {plan.verify_command}")
    return plan


def repo_adversary(task: str, plan: RepoPlan, context: str, ctx: AgentContext,
                   reasoning: str | None = "low", test_path: str = "") -> RepoTest:
    items = "\n".join(f"  - {c.path}: {c.intent}" for c in plan.files_to_change)
    where = test_path or plan.test_path
    user = (
        f"TASK:\n{task}\n\nPLAN summary: {plan.summary}\nfiles to change:\n{items}\n"
        f"verify_command: {plan.verify_command}\n"
        f"Write the test at {where} that verifies: {plan.test_intent}\n\n{context}"
    )
    res = invoke(ctx, "adversary", _ADVERSARY, user, RepoTest,
                 reasoning_effort=reasoning, temperature=0.5, max_completion_tokens=32000)
    test: RepoTest = res.parsed  # type: ignore[assignment]
    ctx.emitter.agent_done("adversary", f"wrote check {test.path}")
    return test


def repo_implementer(task: str, plan: RepoPlan, current_files: str, ctx: AgentContext) -> RepoChange:
    items = "\n".join(f"  - {c.path}: {c.intent}" for c in plan.files_to_change)
    user = (
        f"TASK:\n{task}\n\nPLAN: {plan.summary}\nchange these files:\n{items}\n\n"
        f"CURRENT CONTENT OF THOSE FILES:\n{current_files}\n\n"
        "Return the full new content of each changed/created file."
    )
    res = invoke(ctx, "implementer", _IMPLEMENTER, user, RepoChange,
                 reasoning_effort=None, temperature=0.4, max_completion_tokens=32000)
    change: RepoChange = res.parsed  # type: ignore[assignment]
    ctx.emitter.candidate_proposed(render_change(change), change.reasoning)
    ctx.emitter.agent_done("implementer", f"edited {len(change.files)} file(s)")
    return change


def repo_surgeon(change: RepoChange, failure_output: str, ctx: AgentContext) -> RepoChange:
    user = (
        f"CURRENT CHANGED FILES:\n{render_change(change)}\n\n"
        f"VERIFICATION FAILURE OUTPUT:\n{failure_output[:3000]}\n\n"
        "Make the smallest fix. Return the full corrected content of every file you change."
    )
    res = invoke(ctx, "surgeon", _SURGEON, user, RepoChange,
                 reasoning_effort=None, temperature=0.3, max_completion_tokens=32000)
    fixed: RepoChange = res.parsed  # type: ignore[assignment]
    ctx.emitter.surgeon_patch(render_change(fixed), fixed.reasoning)
    ctx.emitter.agent_done("surgeon", "applied fix")
    return fixed
