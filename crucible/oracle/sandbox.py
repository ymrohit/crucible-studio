"""Sandboxed execution of untrusted candidate code (§10).

The spec's production answer is *persistent container + fresh subprocess per candidate*.
We implement that as :class:`DockerSandbox` AND a hardened :class:`LocalSandbox` for hosts
without Docker (e.g. WSL distros). Both honor the same contract:

    * fresh process per candidate
    * a HARD timeout → kill the whole process group → treat as failure (never hang)
    * deterministic env: PYTHONHASHSEED=0
    * resource caps (memory / CPU / file size) and best-effort network denial

``CRUCIBLE_SANDBOX`` selects the backend: ``auto`` (default) uses Docker iff a working
daemon is reachable, otherwise local; ``docker`` / ``local`` force one.

The single primitive every stage uses is :meth:`Sandbox.run_python(program, timeout)`.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:  # POSIX resource limits (Linux/macOS)
    import resource  # type: ignore
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore

# Host safety: cap how many candidate subprocesses run at once, so concurrent runs (or a
# busy UI) can't multiply memory without bound. The verdict nonce (see below) goes in env.
_SBX_CONCURRENCY = max(1, int(os.getenv("CRUCIBLE_SBX_CONCURRENCY", "2")))
_SBX_SEM = threading.BoundedSemaphore(_SBX_CONCURRENCY)
# Per-subprocess address-space cap (MB). Lowered from 3 GB so one runaway/hypothesis-fuzzed
# candidate can't eat the host; combined with the concurrency cap this hard-bounds total RAM.
_SBX_MEM_MB = max(512, int(os.getenv("CRUCIBLE_SBX_MEM_MB", "2048")))


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration: float
    nonce: str = ""  # secret prefix the verdict line must carry (anti-forge, see harness)

    @property
    def ok(self) -> bool:
        return (not self.timed_out) and self.returncode == 0


# Prepended to every executed program: best-effort network denial so candidate code
# cannot phone home even in the local sandbox. (Docker adds real --network none on top.)
# NB: socket.socket must remain a *class* so stdlib code like `class SSLSocket(socket)`
# (imported transitively by hypothesis) still works — we subclass and block connect only.
_NET_BLOCK = (
    "import socket as _socket\n"
    "_RealSocket = _socket.socket\n"
    "class _BlockedSocket(_RealSocket):\n"
    "    def connect(self, *a, **k):\n"
    "        raise OSError('network access disabled in Crucible sandbox')\n"
    "    def connect_ex(self, *a, **k):\n"
    "        raise OSError('network access disabled in Crucible sandbox')\n"
    "_socket.socket = _BlockedSocket\n"
    "def _no_net(*a, **k):\n"
    "    raise OSError('network access disabled in Crucible sandbox')\n"
    "_socket.create_connection = _no_net\n"
)


class Sandbox:
    """Backend-agnostic interface."""

    def run_python(self, program: str, timeout: float) -> SandboxResult:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover
        pass

    @property
    def kind(self) -> str:  # pragma: no cover
        return "abstract"


# --------------------------------------------------------------------------- local
def _set_limits(mem_bytes: int, cpu_seconds: int, fsize_bytes: int):
    """Return a preexec_fn that isolates the child into its own session and caps it."""

    def _preexec() -> None:  # runs in the child, after fork, before exec
        os.setsid()  # own process group → killpg on timeout
        if resource is not None:
            def _try(res, soft, hard):
                try:
                    resource.setrlimit(res, (soft, hard))
                except (ValueError, OSError):
                    pass

            _try(resource.RLIMIT_AS, mem_bytes, mem_bytes)
            _try(resource.RLIMIT_CPU, cpu_seconds, cpu_seconds + 1)
            _try(resource.RLIMIT_FSIZE, fsize_bytes, fsize_bytes)
            # Disable core dumps.
            _try(resource.RLIMIT_CORE, 0, 0)

    return _preexec


class LocalSandbox(Sandbox):
    def __init__(
        self,
        python: Optional[str] = None,
        mem_bytes: Optional[int] = None,
        fsize_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        # Use the current interpreter so hypothesis/pyright deps are importable.
        self.python = python or sys.executable
        self.mem_bytes = mem_bytes if mem_bytes is not None else _SBX_MEM_MB * 1024 * 1024
        self.fsize_bytes = fsize_bytes

    @property
    def kind(self) -> str:
        return "local"

    def run_python(self, program: str, timeout: float) -> SandboxResult:
        nonce = secrets.token_hex(8)
        full = _NET_BLOCK + "\n" + program
        with _SBX_SEM:  # bound concurrent candidate subprocesses
            with tempfile.TemporaryDirectory(prefix="crucible_sbx_") as workdir:
                return self._run(full, nonce, workdir, timeout)

    def _run(self, full: str, nonce: str, workdir: str, timeout: float) -> SandboxResult:
        script = os.path.join(workdir, "candidate_run.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(full)

        env = {
            "PYTHONHASHSEED": "0",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join(sys.path),  # reach installed deps
            "HOME": workdir,
            "TMPDIR": workdir,
            "PYTHONDONTWRITEBYTECODE": "1",
            "CRUCIBLE_NONCE": nonce,  # the harness reads+pops this to tag its verdict
        }
        preexec = _set_limits(self.mem_bytes, int(timeout) + 2, self.fsize_bytes) if os.name == "posix" else None

        start = time.monotonic()
        proc = subprocess.Popen(
            [self.python, "-B", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workdir,
            env=env,
            text=True,
            preexec_fn=preexec,
            start_new_session=(preexec is None),  # ensure own session even off-POSIX path
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._hard_kill(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                self._hard_kill(proc)  # second sweep for double-fork escapees
                try:
                    proc.wait(timeout=2)  # reap so no zombie / lingering pipe holder
                except subprocess.TimeoutExpired:
                    pass
                stdout, stderr = "", "killed after timeout"
        duration = time.monotonic() - start
        return SandboxResult(
            returncode=proc.returncode if proc.returncode is not None else -9,
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=timed_out,
            duration=duration,
            nonce=nonce,
        )

    @staticmethod
    def _hard_kill(proc: subprocess.Popen) -> None:
        import signal

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass


# -------------------------------------------------------------------------- docker
class DockerSandbox(Sandbox):
    """Persistent python:3.12-slim container; one fresh `docker exec` python per candidate.

    Built per §10: --network none, memory cap, read-only root with a writable /tmp. Used
    only when a Docker daemon is reachable. The local sandbox is the tested default here.
    """

    IMAGE = "crucible-sandbox:latest"

    def __init__(self, mem: str = "1g") -> None:
        self.mem = mem
        # Per-process container name so concurrent Crucible processes don't `docker rm` each
        # other's sandbox (the image is shared; only the running container is per-process).
        self.CONTAINER = f"crucible_sandbox_{os.getpid()}"
        self._started = False
        # Serialize exec into the shared container: the timeout path pkills python, which
        # would otherwise also kill a concurrent run's process in the same container (#7).
        self._lock = threading.Lock()
        self._ensure_container()

    @property
    def kind(self) -> str:
        return "docker"

    def _docker(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout
        )

    def _image_exists(self) -> bool:
        return self._docker("image", "inspect", self.IMAGE).returncode == 0

    def _ensure_container(self) -> None:
        if not self._image_exists():
            # Build from docker/sandbox.Dockerfile relative to repo root.
            from pathlib import Path

            dockerfile = Path(__file__).resolve().parents[2] / "docker" / "sandbox.Dockerfile"
            ctx = dockerfile.parent
            build = self._docker(
                "build", "-f", str(dockerfile), "-t", self.IMAGE, str(ctx), timeout=600
            )
            if build.returncode != 0:
                raise RuntimeError(f"docker build failed: {build.stderr[:400]}")
        # (Re)create the long-lived container.
        self._docker("rm", "-f", self.CONTAINER)
        run = self._docker(
            "run", "-d", "--name", self.CONTAINER,
            "--network", "none",
            "--memory", self.mem, "--memory-swap", self.mem,
            "--read-only", "--tmpfs", "/tmp:exec",
            "--pids-limit", "128",
            self.IMAGE, "sleep", "infinity",
        )
        if run.returncode != 0:
            raise RuntimeError(f"docker run failed: {run.stderr[:400]}")
        self._started = True

    def run_python(self, program: str, timeout: float) -> SandboxResult:
        nonce = secrets.token_hex(8)
        full = _NET_BLOCK + "\n" + program
        start = time.monotonic()
        with self._lock:  # one exec at a time → pkill on timeout can't hit a concurrent run
            try:
                proc = subprocess.run(
                    [
                        "docker", "exec", "-i",
                        "-e", "PYTHONHASHSEED=0",
                        "-e", f"CRUCIBLE_NONCE={nonce}",
                        self.CONTAINER, "python", "-B", "-",
                    ],
                    input=full,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                duration = time.monotonic() - start
                return SandboxResult(proc.returncode, proc.stdout, proc.stderr, False, duration, nonce)
            except subprocess.TimeoutExpired:
                # Safe under the lock: no concurrent run's python to clobber.
                self._docker("exec", self.CONTAINER, "pkill", "-9", "python")
                return SandboxResult(-9, "", "timeout", True, time.monotonic() - start, nonce)

    def close(self) -> None:
        self._docker("rm", "-f", self.CONTAINER)


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10
        ).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def make_sandbox() -> Sandbox:
    choice = os.getenv("CRUCIBLE_SANDBOX", "auto").lower()
    if choice == "local":
        return LocalSandbox()
    if choice == "docker":
        return DockerSandbox()
    # auto
    if _docker_available():
        try:
            return DockerSandbox()
        except Exception:
            pass
    return LocalSandbox()


# A process-wide sandbox so the container/limits are set up once.
_default_sandbox: Optional[Sandbox] = None


def get_sandbox() -> Sandbox:
    global _default_sandbox
    if _default_sandbox is None:
        _default_sandbox = make_sandbox()
    return _default_sandbox
