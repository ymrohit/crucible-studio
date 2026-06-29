"""Product oracle: actually BUILD-and-RUN a generated FastAPI service in a container and run the
blind integration test against it. The verdict is the test's exit code — real execution, the
model never marks its own homework.

A fresh `docker run --rm --network none` container per candidate (loopback works, so the app on
127.0.0.1:8000 and the test in the same container talk; no external network, no host exposure).
Hard timeout → docker kill (never hang).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

from ..shared.product_schemas import ProductFile

IMAGE = "crucible-product:latest"

_RUN_SH = r"""
cd /app
python -m uvicorn main:app --host 127.0.0.1 --port 8000 > /tmp/server.log 2>&1 &
SRV=$!
python - <<'PY'
import time, sys
import httpx
ok = False
for _ in range(120):
    try:
        httpx.get("http://127.0.0.1:8000/openapi.json", timeout=1.0); ok = True; break
    except Exception:
        time.sleep(0.25)
sys.exit(0 if ok else 7)
PY
if [ $? -ne 0 ]; then
  echo "=== SERVICE FAILED TO BOOT ==="; tail -60 /tmp/server.log
  kill $SRV 2>/dev/null || true; exit 7
fi
python /app/test_integration.py
RC=$?
if [ $RC -ne 0 ]; then echo "=== SERVER LOG (tail) ==="; tail -40 /tmp/server.log; fi
kill $SRV 2>/dev/null || true
exit $RC
"""

_counter = 0


@dataclass
class ProductRunResult:
    passed: bool
    exit_code: int
    output: str
    timed_out: bool
    duration: float

    @property
    def booted(self) -> bool:
        return self.exit_code != 7 and "FAILED TO BOOT" not in self.output


def build_and_test(
    files: list[ProductFile], integration_test: str, *, timeout: float = 75.0
) -> ProductRunResult:
    global _counter
    _counter += 1
    name = f"crucible_prod_{os.getpid()}_{_counter}"

    workdir = tempfile.mkdtemp(prefix="crucible_prod_")
    try:
        for f in files:
            # confine writes inside workdir (defend against ../ in a model-supplied path)
            dest = os.path.normpath(os.path.join(workdir, f.path))
            if not dest.startswith(os.path.abspath(workdir) + os.sep) and dest != os.path.abspath(workdir):
                dest = os.path.join(workdir, os.path.basename(f.path))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(f.content)
        with open(os.path.join(workdir, "test_integration.py"), "w", encoding="utf-8") as fh:
            fh.write(integration_test)
        with open(os.path.join(workdir, "run.sh"), "w", encoding="utf-8") as fh:
            fh.write(_RUN_SH)

        # Run as the host user (so files written into the mount stay host-owned and cleanable)
        # and disable bytecode so no root-owned __pycache__ is left behind.
        user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else None
        cmd = [
            "docker", "run", "--rm", "--name", name,
            "--network", "none",
            "--memory", "1g", "--memory-swap", "1g", "--pids-limit", "256",
            "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
            *(["--user", user] if user else []),
            "-v", f"{workdir}:/app", "-w", "/app",
            IMAGE, "bash", "/app/run.sh",
        ]
        start = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            dur = time.monotonic() - start
            out = (proc.stdout or "") + (proc.stderr or "")
            return ProductRunResult(proc.returncode == 0, proc.returncode, out, False, dur)
        except subprocess.TimeoutExpired as e:
            subprocess.run(["docker", "kill", name], capture_output=True)
            dur = time.monotonic() - start
            raw = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "ignore")
            return ProductRunResult(False, -9, (raw or "") + "\n=== TIMED OUT (killed) ===", True, dur)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def docker_product_available() -> bool:
    import shutil

    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", IMAGE],
                              capture_output=True, timeout=10).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False
