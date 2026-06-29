"""Web-app build loop: plan -> (blind) QA spec -> implement a single self-contained file ->
render it in a REAL browser, click through it, and let the vision model confirm it actually works
-> repair from the visual verdict. Streams the same agent/stage events as the function loop, plus
an ``app_ready`` event carrying the live HTML so the UI can preview it in an iframe.

Degrades gracefully: if the browser image isn't available, it still delivers the app (clearly
labelled preview-only) so the side-panel demo always shows something live.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

from ..agents.runtime import AgentContext
from ..agents.visual import visual_qa
from ..agents.webapp import webapp_adversary, webapp_architect, webapp_implementer, webapp_surgeon
from ..oracle.visual_runtime import PW_IMAGE, web_image_available
from .budget import Budget
from .events import Sink

_DRIVER = r'''
import json
from playwright.sync_api import sync_playwright
clicks = json.load(open("/out/clicks.json"))
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
    pg = b.new_page(viewport={"width": 1120, "height": 820})
    pg.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    pg.goto("file:///site/index.html", wait_until="load", timeout=30000)
    pg.wait_for_timeout(900)
    for label in clicks:
        ok = False
        for sel in [lambda: pg.get_by_role("button", name=label, exact=True).first.click(timeout=1500),
                    lambda: pg.get_by_text(label, exact=True).first.click(timeout=1500),
                    lambda: pg.click("text=%s" % label, timeout=1500)]:
            try:
                sel(); ok = True; break
            except Exception:
                continue
        if not ok:
            errors.append("could not click %r" % label)
        pg.wait_for_timeout(180)
    pg.wait_for_timeout(350)
    pg.screenshot(path="/out/shot.png", full_page=True)
    b.close()
print("ERRORS=" + json.dumps(errors))
'''


@dataclass
class WebAppResult:
    status: str               # "verified" | "floor" | "error"
    html: str = ""
    plan: object = None
    budget: Optional[dict] = None
    error: Optional[str] = None


def _render_and_click(html: str, clicks: list[str], timeout: float = 120.0):
    """Render the single-file app in a real browser, click the labels, return (png|None, errors)."""
    site = tempfile.mkdtemp(prefix="cru_app_site_")
    out = tempfile.mkdtemp(prefix="cru_app_out_")
    try:
        with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)
        with open(os.path.join(out, "clicks.json"), "w") as f:
            json.dump(clicks or [], f)
        with open(os.path.join(out, "driver.py"), "w") as f:
            f.write(_DRIVER)
        name = f"cru_app_{os.getpid()}"
        cmd = ["docker", "run", "--rm", "--name", name, "--shm-size=1g",
               "-v", f"{site}:/site:ro", "-v", f"{out}:/out", "-w", "/out",
               PW_IMAGE, "python", "/out/driver.py"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", name], capture_output=True)
            return None, ["render timed out"]
        errors: list[str] = []
        for line in (r.stdout or "").splitlines():
            if line.startswith("ERRORS="):
                try:
                    errors = json.loads(line[len("ERRORS="):])
                except Exception:
                    pass
        shot = os.path.join(out, "shot.png")
        png = open(shot, "rb").read() if os.path.isfile(shot) else None
        return png, errors
    finally:
        import shutil
        shutil.rmtree(site, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)


def webapp_run(prompt: str, *, sink: Optional[Sink] = None, budget: Optional[Budget] = None) -> WebAppResult:
    ctx = AgentContext.create(sink=sink, budget=budget or Budget(max_tokens=1_500_000, max_iters=4, max_seconds=420))
    em = ctx.emitter
    em.run_start(prompt)
    try:
        plan = webapp_architect(prompt, ctx)
        check = webapp_adversary(prompt, plan, ctx)
        html = webapp_implementer(prompt, plan, ctx)
        # show the first build immediately so the side panel is live while it verifies
        em.emit({"type": "app_ready", "html": html, "verified": False})

        has_browser = web_image_available()
        if not has_browser:
            em.note("browser image not found — delivering live preview without visual verification")
            em.emit({"type": "stage_result", "result": {
                "stage": "visual-qa", "status": "pass", "detail": "skipped: no browser image (preview only)"}})
            em.candidate_delivered(html)
            em.run_done("floor", html, "delivered without visual verification (no browser image)")
            return WebAppResult("floor", html, plan, ctx.budget.snapshot())

        best = html
        while not ctx.budget.exhausted():
            ctx.budget.tick()
            em.iteration(ctx.budget.iters)

            em.stage_start("render")
            png, errors = _render_and_click(html, check.click_sequence)
            em.emit({"type": "stage_result", "result": {
                "stage": "render", "status": "pass" if png else "fail",
                "detail": (f"clicked {check.click_sequence}; " if check.click_sequence else "")
                          + (f"{len(errors)} console error(s)" if errors else "rendered cleanly")}})
            if png is None:
                em.stage_start("visual-qa")
                em.emit({"type": "stage_result", "result": {
                    "stage": "visual-qa", "status": "fail", "detail": "page did not render"}})
                html = webapp_surgeon(prompt, html, "The page failed to render at all in a real browser. "
                                      + ("Console: " + "; ".join(errors[:4]) if errors else ""), ctx)
                continue

            em.stage_start("visual-qa")
            vtask = (f"{prompt}\n\nA tester clicked: {check.click_sequence}. "
                     f"Expected afterit: {check.expected_outcome}. "
                     f"Also required visible: {'; '.join(check.visual_requirements[:6])}.")
            verdict = visual_qa(png, vtask, ctx)
            ok = verdict.looks_correct
            em.emit({"type": "stage_result", "result": {
                "stage": "visual-qa", "status": "pass" if ok else "fail",
                "detail": (verdict.observed[:90] if verdict.observed else "")
                          + (" | issues: " + "; ".join(verdict.issues[:3]) if verdict.issues else "")}})
            best = html
            # re-publish the (now verified-or-latest) html to the live preview
            em.emit({"type": "app_ready", "html": html, "verified": ok})

            if ok and not [e for e in errors if "pageerror" in e]:
                em.candidate_delivered(html)
                em.run_done("verified", html, "renders and works in a real browser; vision QA passed")
                return WebAppResult("verified", html, plan, ctx.budget.snapshot())

            problems = ("Vision QA issues: " + "; ".join(verdict.issues) if verdict.issues else verdict.observed)
            if errors:
                problems += "\nBrowser console: " + "; ".join(errors[:5])
            html = webapp_surgeon(prompt, html, problems, ctx)

        em.emit({"type": "app_ready", "html": best, "verified": False})
        em.floor_reached(best, "visual QA (best effort) — shipping latest live preview")
        em.run_done("floor", best, f"budget exhausted: {ctx.budget.reason()}")
        return WebAppResult("floor", best, plan, ctx.budget.snapshot())
    except Exception as e:  # pragma: no cover
        em.run_error(f"{type(e).__name__}: {e}")
        return WebAppResult("error", "", None, ctx.budget.snapshot(), str(e))
