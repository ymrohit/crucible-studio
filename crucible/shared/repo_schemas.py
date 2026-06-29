"""Schemas for 'repo mode' — point Crucible at an existing repository plus a task ("build X" or
"fix Y") and get back verified, multi-file changes (a diff). Same verify-first seam: the Architect
plans against the real repo, the blind Adversary writes the check, the Implementer edits the files,
and the oracle actually runs the verification in a container.
"""

from pydantic import BaseModel
from typing import Literal


class ChangeItem(BaseModel):
    path: str            # repo-relative path to create or modify
    intent: str          # what changes in this file and why


class RepoPlan(BaseModel):
    summary: str
    runtime: Literal["python", "node", "static"]
    verify_command: str          # shell command run at repo root; exit 0 == success
    files_to_change: list[ChangeItem]
    generate_test: bool          # True when the repo lacks a check for this task → Adversary writes one
    test_path: str               # where the generated test goes (empty if generate_test is False)
    test_intent: str             # what the generated test must verify (empty if not used)
    notes: list[str]


class RepoFile(BaseModel):
    path: str
    content: str                 # FULL new content of the file


class RepoChange(BaseModel):
    files: list[RepoFile]        # every created/modified source file (full content)
    reasoning: str


class RepoTest(BaseModel):
    path: str                    # the test/check file path
    content: str                 # full content; run by the plan's verify_command


class RepoEdit(BaseModel):
    path: str            # file to edit (must already exist)
    old_string: str      # EXACT, UNIQUE snippet currently in the file (with enough context)
    new_string: str      # replacement for old_string


class RepoEditSet(BaseModel):
    edits: list[RepoEdit]   # minimal targeted edits — NOT whole-file rewrites
    reasoning: str


class VisualVerdict(BaseModel):
    observed: str                # what the vision model actually sees in the screenshot
    looks_correct: bool          # does the rendered UI satisfy the task / have everything in place
    issues: list[str]            # concrete visual problems (missing/invisible/broken/overlapping)
