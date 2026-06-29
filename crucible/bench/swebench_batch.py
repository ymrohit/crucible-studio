"""Batch SWE-bench Lite: build each instance image (if needed), run the Crucible solver, write
predictions. Score afterwards with the official harness.

    python -m crucible.bench.swebench_batch                 # default 8-instance batch
    python -m crucible.bench.swebench_batch <id> <id> ...
"""

from __future__ import annotations

import json
import os
import sys
import traceback

import docker
from swebench.harness.docker_build import build_instance_images

from ..orchestrator.console import make_console_sink
from .swebench_solve import ROWS, image_for, solve


def ensure_image(iid: str) -> bool:
    try:
        image_for(iid)
        return True
    except RuntimeError:
        pass
    try:
        client = docker.from_env()
        build_instance_images(client, [ROWS[iid]], force_rebuild=False, max_workers=2)
        image_for(iid)
        return True
    except Exception as e:
        print(f"  [{iid}] image build failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def main(argv: list[str]) -> int:
    ids = argv or json.load(open("/tmp/claude-1000/batch_ids.json"))
    sink = make_console_sink(verbose=False)
    preds = []
    for i, iid in enumerate(ids, 1):
        print(f"\n#### [{i}/{len(ids)}] {iid} ({ROWS[iid]['repo']}) ####", file=sys.stderr, flush=True)
        patch = ""
        try:
            if ensure_image(iid):
                patch = solve(iid, sink)
        except Exception:
            traceback.print_exc()
        touched = [l[6:] for l in patch.splitlines() if l.startswith("+++ b/")]
        print(f"  -> patch touches {touched} ({len(patch)} chars)", file=sys.stderr)
        preds.append({"instance_id": iid, "model_name_or_path": "crucible", "model_patch": patch})
        # write incrementally so partial progress survives
        with open("crucible_batch_preds.jsonl", "w") as f:
            for p in preds:
                f.write(json.dumps(p) + "\n")
    print(f"\nwrote {len(preds)} predictions -> crucible_batch_preds.jsonl", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
