"""Render a real browser screenshot of a built web UI (headless chromium via Playwright in a
container), so the vision model can do visual QA. Returns PNG bytes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from typing import Optional

PW_IMAGE = "crucible-web:latest"

_DRIVER = '''
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
    pg = b.new_page(viewport={{"width": 1100, "height": 820}})
    pg.goto("file:///repo/{html}", wait_until="load", timeout=30000)
    pg.wait_for_timeout(500)
    try:
{interaction}
    except Exception as _e:
        print("interaction error:", _e)
    pg.screenshot(path="/out/shot.png", full_page=True)
    b.close()
print("OK")
'''

_counter = 0


def web_image_available() -> bool:
    try:
        return subprocess.run(["docker", "image", "inspect", PW_IMAGE],
                              capture_output=True, timeout=10).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def render_screenshot(
    repo_dir: str, html_file: str = "index.html", interaction: str = "", timeout: float = 90.0
) -> Optional[bytes]:
    global _counter
    _counter += 1
    name = f"crucible_web_{os.getpid()}_{_counter}"
    interaction_block = "\n".join("        " + ln for ln in interaction.splitlines()) or "        pass"
    outdir = tempfile.mkdtemp(prefix="crucible_shot_")
    try:
        with open(os.path.join(outdir, "driver.py"), "w", encoding="utf-8") as fh:
            fh.write(_DRIVER.format(html=html_file, interaction=interaction_block))
        cmd = ["docker", "run", "--rm", "--name", name, "--shm-size=1g",
               "-v", f"{repo_dir}:/repo:ro", "-v", f"{outdir}:/out", "-w", "/out",
               PW_IMAGE, "python", "/out/driver.py"]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", name], capture_output=True)
            return None
        shot = os.path.join(outdir, "shot.png")
        if os.path.isfile(shot):
            with open(shot, "rb") as fh:
                return fh.read()
        return None
    finally:
        shutil.rmtree(outdir, ignore_errors=True)
