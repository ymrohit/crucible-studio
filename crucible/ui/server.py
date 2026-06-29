"""FastAPI server for the Crucible Studio demo.

    python -m crucible.ui.server         # serves http://127.0.0.1:8000

One SSE stream per run. Three modes:
  - code : LEFT pane = a GPU baseline (Gemma 4 31B on Google AI Studio, or vanilla Cerebras),
           RIGHT pane = the live Crucible function loop. A follow-up /compare feeds the captured
           counterexample to both.
  - app  : Crucible builds + boots + tests a real multi-file service (product loop).
  - repo : Crucible fixes a real bundled repository (repo loop) + vision visual-QA.

Producers run in real OS threads (sandbox subprocess + sync httpx are blocking) and push events
into an asyncio queue the SSE endpoint drains.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..bench.vanilla_baseline import vanilla_stream
from ..oracle import harness
from ..oracle.sandbox import get_sandbox
from ..orchestrator import state_machine
from ..shared.schemas import Candidate

_STATIC = Path(__file__).parent / "static"
_REPO_ROOT = Path(__file__).resolve().parents[2]   # /home/tihor/crucible

app = FastAPI(title="Crucible Studio")

_MAX_CONCURRENT_RUNS = max(1, int(os.getenv("CRUCIBLE_MAX_CONCURRENT_RUNS", "1")))
_CRUCIBLE_SEM = threading.BoundedSemaphore(_MAX_CONCURRENT_RUNS)
_MAX_RUNS = 24

# Repos exposed to repo-mode, by short key (allowlist — never accept arbitrary paths from clients).
_REPOS = {
    "pyrepo": _REPO_ROOT / "examples" / "pyrepo",
    "webrepo": _REPO_ROOT / "examples" / "webrepo",
}


class _Cancelled(Exception):
    """Internal signal to abort a worker when the client has disconnected."""


class Run:
    """Per-request fan-in of baseline + Crucible events into one asyncio queue."""

    def __init__(self, prompt: str, mode: str, loop: asyncio.AbstractEventLoop) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.prompt = prompt
        self.mode = mode
        self.loop = loop
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.remaining = 2 if mode == "code" else 1
        self.stopped = threading.Event()
        self.vanilla_code: Optional[str] = None
        self.crucible_code: Optional[str] = None
        self.counterexample: Optional[dict[str, Any]] = None

    def push(self, ev: dict[str, Any]) -> None:
        if self.stopped.is_set():
            return
        self.loop.call_soon_threadsafe(self.queue.put_nowait, ev)

    def finish_one(self) -> None:
        def _dec() -> None:
            self.remaining -= 1
            if self.remaining <= 0:
                self.queue.put_nowait({"type": "all_done"})

        self.loop.call_soon_threadsafe(_dec)


RUNS: "OrderedDict[str, Run]" = OrderedDict()


def _register(run: Run) -> None:
    RUNS[run.id] = run
    while len(RUNS) > _MAX_RUNS:
        _, old = RUNS.popitem(last=False)
        old.stopped.set()


def _baseline_worker(run: Run, baseline: str) -> None:
    """Left pane: a single-shot answer from a GPU provider (Gemini/AI Studio) or vanilla Cerebras."""
    provider, model = "Cerebras", "gemma-4-31b"
    stream = vanilla_stream
    if baseline == "gemini":
        try:
            from ..bench.gemini_baseline import gemini_stream  # built alongside; lazy import
            stream = gemini_stream
            provider, model = "Google AI Studio (GPU)", "gemma-4-31b-it"
        except Exception:
            baseline = "vanilla"  # fall back gracefully if the module/key isn't available
    try:
        run.push({"type": "vanilla_start", "provider": provider, "model": model})

        def on_tok(t: str) -> None:
            if run.stopped.is_set():
                raise _Cancelled()
            run.push({"type": "vanilla_token", "text": t})

        out = stream(run.prompt, on_tok)
        run.vanilla_code = out["code"]
        run.push({
            "type": "vanilla_done",
            "code": out["code"],
            "tokens_per_sec": round(out.get("tokens_per_sec", 0) or 0, 1),
            "elapsed": round(out.get("elapsed", 0) or 0, 3),
            "provider": provider,
            "model": model,
        })
    except _Cancelled:
        pass
    except Exception as e:  # pragma: no cover - network/runtime
        run.push({"type": "vanilla_error", "message": f"{type(e).__name__}: {e}"})
    finally:
        run.finish_one()


def _sink_for(run: Run):
    def sink(ev: dict[str, Any]) -> None:
        if ev.get("type") == "stage_result":
            ce = ev["result"].get("counterexample")
            if ce and run.counterexample is None:
                run.counterexample = ce
        if ev.get("type") in ("candidate_proposed", "surgeon_patch", "candidate_delivered", "floor_reached"):
            run.crucible_code = ev.get("code")
        run.push(ev)
    return sink


def _crucible_worker(run: Run) -> None:
    sink = _sink_for(run)
    acquired = _CRUCIBLE_SEM.acquire(timeout=180)
    try:
        if run.stopped.is_set():
            return
        if not acquired:
            run.push({"type": "run_error", "message": "server busy; another run is in progress"})
            return
        result = state_machine.run(run.prompt, sink=sink, should_stop=run.stopped.is_set)
        if run.crucible_code is None:
            run.crucible_code = result.code
    except Exception as e:  # pragma: no cover
        run.push({"type": "run_error", "message": f"{type(e).__name__}: {e}"})
    finally:
        if acquired:
            _CRUCIBLE_SEM.release()
        run.finish_one()


def _repair_worker(run: Run, source_code: str) -> None:
    sink = _sink_for(run)
    acquired = _CRUCIBLE_SEM.acquire(timeout=180)
    try:
        if run.stopped.is_set():
            return
        if not acquired:
            run.push({"type": "run_error", "message": "server busy; another run is in progress"})
            return
        if not source_code.strip():
            run.push({"type": "run_error", "message": "paste the broken code before running repair"})
            return
        initial = Candidate(code=source_code, reasoning="pasted code under repair")
        result = state_machine.run(
            run.prompt,
            sink=sink,
            inject_candidate=initial,
            should_stop=run.stopped.is_set,
        )
        if run.crucible_code is None:
            run.crucible_code = result.code
    except Exception as e:  # pragma: no cover
        run.push({"type": "run_error", "message": f"{type(e).__name__}: {e}"})
    finally:
        if acquired:
            _CRUCIBLE_SEM.release()
        run.finish_one()


def _product_worker(run: Run) -> None:
    from ..orchestrator.webapp_loop import webapp_run
    from ..orchestrator.budget import Budget
    sink = _sink_for(run)
    acquired = _CRUCIBLE_SEM.acquire(timeout=180)
    try:
        if run.stopped.is_set() or not acquired:
            if not acquired:
                run.push({"type": "run_error", "message": "server busy; another run is in progress"})
            return
        webapp_run(run.prompt, sink=sink,
                   budget=Budget(max_tokens=1_500_000, max_iters=4, max_seconds=420))
    except Exception as e:  # pragma: no cover
        run.push({"type": "run_error", "message": f"{type(e).__name__}: {e}"})
    finally:
        if acquired:
            _CRUCIBLE_SEM.release()
        run.finish_one()


def _resolve_repo(repo: str) -> Optional[Path]:
    """A short allowlist key (e.g. 'webrepo') OR any local path the user points us at."""
    if repo in _REPOS:
        return _REPOS[repo]
    if not repo:
        return None
    p = Path(repo).expanduser()
    if not p.is_absolute():
        p = _REPO_ROOT / repo
    p = p.resolve()
    return p if p.is_dir() else None


def _repo_worker(run: Run, repo_key: str) -> None:
    from ..orchestrator.repo_loop import repo_run
    from ..orchestrator.budget import Budget
    sink = _sink_for(run)
    repo_path = _resolve_repo(repo_key)
    acquired = _CRUCIBLE_SEM.acquire(timeout=180)
    try:
        if run.stopped.is_set() or not acquired:
            if not acquired:
                run.push({"type": "run_error", "message": "server busy; another run is in progress"})
            return
        if not repo_path or not repo_path.is_dir():
            run.push({"type": "run_error", "message": f"repo not found: '{repo_key}' (give a path to a local folder)"})
            return
        repo_run(str(repo_path), run.prompt, sink=sink,
                 budget=Budget(max_tokens=600_000, max_iters=6, max_seconds=480))
    except Exception as e:  # pragma: no cover
        run.push({"type": "run_error", "message": f"{type(e).__name__}: {e}"})
    finally:
        if acquired:
            _CRUCIBLE_SEM.release()
        run.finish_one()


@app.get("/run_stream")
async def run_stream(prompt: str, mode: str = "code", baseline: str = "gemini",
                     repo: str = "pyrepo", source_code: str = "") -> StreamingResponse:
    prompt = (prompt or "").strip()
    mode = mode if mode in ("code", "app", "repo", "repair") else "code"
    loop = asyncio.get_running_loop()
    run = Run(prompt, mode, loop)
    _register(run)

    if mode == "app":
        threading.Thread(target=_product_worker, args=(run,), daemon=True).start()
    elif mode == "repo":
        threading.Thread(target=_repo_worker, args=(run, repo), daemon=True).start()
    elif mode == "repair":
        threading.Thread(target=_repair_worker, args=(run, source_code), daemon=True).start()
    else:
        threading.Thread(target=_baseline_worker, args=(run, baseline), daemon=True).start()
        threading.Thread(target=_crucible_worker, args=(run,), daemon=True).start()

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'run_id', 'id': run.id, 'mode': mode})}\n\n"
            while True:
                ev = await run.queue.get()
                yield f"data: {json.dumps(ev)}\n\n"
                if ev.get("type") == "all_done":
                    break
        finally:
            run.stopped.set()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _run_on_input(code: Optional[str], input_repr: str) -> dict[str, Any]:
    if not code:
        return {"ok": False, "output": "(no code)"}
    fn = harness.first_def_name(code)
    if not fn:
        return {"ok": False, "output": "(no function found)"}
    program = harness.call_program(code, fn, input_repr)
    res = get_sandbox().run_python(program, timeout=8.0)
    parsed = harness.parse_result(res.stdout, res.nonce)
    return parsed or {"ok": False, "output": "<crashed / no result>"}


@app.post("/compare/{run_id}")
async def compare(run_id: str) -> JSONResponse:
    run = RUNS.get(run_id)
    if run is None:
        return JSONResponse({"error": "unknown run"}, status_code=404)
    ce = run.counterexample
    if not ce:
        return JSONResponse({"available": False, "reason": "no counterexample was found this run"})

    inp = ce["input_repr"]
    expected = ce["expected_repr"]

    def _both() -> dict[str, Any]:
        return {
            "available": True,
            "input": inp,
            "expected": expected,
            "vanilla": _run_on_input(run.vanilla_code, inp),
            "crucible": _run_on_input(run.crucible_code, inp),
        }

    return JSONResponse(await asyncio.to_thread(_both))


_FRONTEND_DIST = _REPO_ROOT / "frontend" / "dist"   # built Svelte app (npm run build)


@app.get("/")
async def index() -> FileResponse:
    # Prefer the built Svelte app (same-origin: SSE needs no dev proxy); fall back to the
    # bundled static UI if the frontend hasn't been built.
    if (_FRONTEND_DIST / "index.html").is_file():
        return FileResponse(_FRONTEND_DIST / "index.html")
    return FileResponse(_STATIC / "index.html")


if (_FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


def main() -> None:
    import uvicorn

    try:
        get_sandbox()
    except Exception:
        pass
    print("Crucible Studio -> http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
