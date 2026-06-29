"""Repo oracle: copy a real repository, apply the agent's changes, and actually RUN the
verification command in a container — then produce a git diff of what changed.

Verification runs in a Docker image chosen by runtime (python/node/static). The repo is the user's
own, so the network is left ON for dependency installs; a hard timeout → docker kill (never hang).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

from ..shared.repo_schemas import RepoFile

_IMAGES = {
    "python": "python:3.12-slim",
    "node": "node:20-slim",
    "static": "node:20-slim",
}
# Best-effort dependency install before the verify command (skipped if no manifest present).
_INSTALL = {
    "python": "[ -f requirements.txt ] && pip install -q -r requirements.txt 2>/dev/null; "
              "[ -f pyproject.toml ] && pip install -q -e . 2>/dev/null; pip install -q pytest 2>/dev/null; true",
    "node": "[ -f package.json ] && (npm ci --silent 2>/dev/null || npm install --silent 2>/dev/null); true",
    "static": "true",
}

_IGNORE = shutil.ignore_patterns(
    ".git", "node_modules", ".venv", "venv", "__pycache__", "*.pyc", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".next", ".cache",
)

_counter = 0


@dataclass
class RepoRunResult:
    passed: bool
    exit_code: int
    output: str
    timed_out: bool
    duration: float


def prepare(repo_path: str) -> str:
    """Copy the repo to a temp workdir (minus junk) and git-init a baseline commit for diffing."""
    workdir = tempfile.mkdtemp(prefix="crucible_repo_")
    dst = os.path.join(workdir, "repo")
    shutil.copytree(repo_path, dst, ignore=_IGNORE)
    subprocess.run(["git", "init", "-q"], cwd=dst, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=dst, capture_output=True)
    subprocess.run(["git", "-c", "user.email=c@c", "-c", "user.name=crucible",
                    "commit", "-q", "-m", "baseline", "--allow-empty"], cwd=dst, capture_output=True)
    return dst


def reset(repo_dir: str) -> None:
    """Restore the repo to the baseline commit (drop the previous iteration's edits)."""
    subprocess.run(["git", "reset", "--hard", "-q", "HEAD"], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "clean", "-fdq"], cwd=repo_dir, capture_output=True)


def apply_changes(repo_dir: str, files: list[RepoFile]) -> None:
    for f in files:
        dest = os.path.normpath(os.path.join(repo_dir, f.path))
        root = os.path.abspath(repo_dir)
        if not (dest == root or dest.startswith(root + os.sep)):  # confine to the repo
            dest = os.path.join(repo_dir, os.path.basename(f.path))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(f.content)


def _fuzzy_replace(content: str, old: str, new: str) -> tuple[str, bool]:
    """Replace `old` with `new` tolerating leading/trailing whitespace differences per line
    (LLM search strings often differ only in indentation/trailing spaces)."""
    old_lines = [ln.rstrip() for ln in old.strip("\n").splitlines()]
    old_lines = [ln for ln in old_lines]  # keep blanks within
    if not old_lines:
        return content, False
    stripped_old = [ln.strip() for ln in old_lines]
    flines = content.splitlines(keepends=True)
    bare = [ln.strip() for ln in (l.rstrip("\n") for l in flines)]
    n = len(stripped_old)
    for i in range(0, len(bare) - n + 1):
        if bare[i:i + n] == stripped_old:
            # preserve the indentation of the first matched line for the replacement block
            indent = flines[i][: len(flines[i]) - len(flines[i].lstrip())]
            new_block = "\n".join((indent + ln if ln.strip() else ln) for ln in new.strip("\n").splitlines())
            if not new_block.endswith("\n"):
                new_block += "\n"
            return "".join(flines[:i]) + new_block + "".join(flines[i + n:]), True
    return content, False


def apply_edits(repo_dir: str, edits) -> list[tuple[str, bool, str]]:
    """Apply search/replace edits in place (exact, then whitespace-fuzzy). (path, applied, reason)."""
    results = []
    for e in edits:
        dest = os.path.normpath(os.path.join(repo_dir, e.path))
        root = os.path.abspath(repo_dir)
        if not (dest == root or dest.startswith(root + os.sep)) or not os.path.isfile(dest):
            results.append((e.path, False, "file not found"))
            continue
        content = open(dest, encoding="utf-8", errors="ignore").read()
        if e.old_string and e.old_string in content:
            content = content.replace(e.old_string, e.new_string, 1)
            open(dest, "w", encoding="utf-8").write(content)
            results.append((e.path, True, "replaced (exact)"))
            continue
        fuzzed, ok = _fuzzy_replace(content, e.old_string, e.new_string)
        if ok:
            open(dest, "w", encoding="utf-8").write(fuzzed)
            results.append((e.path, True, "replaced (fuzzy)"))
        else:
            results.append((e.path, False, "old_string not found in file"))
    return results


def verify(repo_dir: str, runtime: str, verify_command: str, *, timeout: float = 180.0,
           network: bool = True) -> RepoRunResult:
    global _counter
    _counter += 1
    name = f"crucible_repo_{os.getpid()}_{_counter}"
    image = _IMAGES.get(runtime, "python:3.12-slim")
    install = _INSTALL.get(runtime, "true")
    user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else None
    script = f"cd /repo\n{install}\n{verify_command}\n"

    cmd = ["docker", "run", "--rm", "--name", name,
           "--memory", "2g", "--pids-limit", "512",
           "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
           *([] if network else ["--network", "none"]),
           *(["--user", user] if user else []),
           "-v", f"{repo_dir}:/repo", "-w", "/repo",
           image, "bash", "-lc", script]
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        dur = time.monotonic() - start
        out = (proc.stdout or "") + (proc.stderr or "")
        return RepoRunResult(proc.returncode == 0, proc.returncode, out, False, dur)
    except subprocess.TimeoutExpired as e:
        subprocess.run(["docker", "kill", name], capture_output=True)
        raw = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "ignore")
        return RepoRunResult(False, -9, (raw or "") + "\n=== TIMED OUT (killed) ===", True,
                             time.monotonic() - start)


def git_diff(repo_dir: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True)
    r = subprocess.run(["git", "diff", "--cached", "--stat"], cwd=repo_dir, capture_output=True, text=True)
    full = subprocess.run(["git", "diff", "--cached"], cwd=repo_dir, capture_output=True, text=True)
    return (r.stdout or "") + "\n" + (full.stdout or "")


def cleanup(repo_dir: str) -> None:
    parent = os.path.dirname(repo_dir)
    shutil.rmtree(parent, ignore_errors=True)
