"""Build a HARD, recent, low-contamination benchmark slice for run_offline.

Pulls `newfacade/LeetCodeDataset` (LeetCode Medium/Hard with `def check(candidate)` harnesses
and 2024-2025 dates) via the HuggingFace datasets-server REST API, reframes each as a
self-contained FREE function (strips the `class Solution`/`self` wrapper), and writes a JSONL
that run_offline consumes with `--problems`.

    python -m crucible.bench.fetch_leetcode --hard 24 --medium 16 -o crucible/bench/data/leetcode_hard.jsonl
    python -m crucible.bench.run_offline --problems crucible/bench/data/leetcode_hard.jsonl

Each line: {id, prompt, function_name, hidden_checker, difficulty, date}. The loop never sees
hidden_checker — it is read only by the scorer. (§11: curating the demo problem is fine;
curating the benchmark slice is fraud — this takes a recent, difficulty-filtered slice, not a
hand-picked easy one. Prefer the held-out `test` split + most recent dates for least contamination.)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request

DATASET = "newfacade/LeetCodeDataset"
BASE = "https://datasets-server.huggingface.co/rows"
# Skip problems whose interface uses linked/tree structures (their checkers need helper
# constructors we don't reproduce). Pure array/string/number problems score cleanly.
BANNED = ("ListNode", "TreeNode", "list_node", "tree_node")


def _fetch(split: str, offset: int, length: int = 100) -> list[dict]:
    url = (
        f"{BASE}?dataset={urllib.parse.quote(DATASET)}&config=default"
        f"&split={split}&offset={offset}&length={length}"
    )
    last = ""
    for _ in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "crucible/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)["rows"]
        except Exception as e:  # transient HF rate limits
            last = str(e)
            time.sleep(3)
    print(f"  fetch failed {split}@{offset}: {last[:120]}")
    return []


def _pull_all(cache: str) -> list[dict]:
    if os.path.exists(cache) and os.path.getsize(cache) > 1000:
        return [json.loads(l) for l in open(cache)]
    rows: list[dict] = []
    for split in ("test", "train"):
        off = 0
        while True:
            batch = _fetch(split, off)
            if not batch:
                break
            for r in batch:
                rows.append({"split": split, **r["row"]})
            off += len(batch)
            if len(batch) < 100:
                break
            time.sleep(0.4)
    if rows:
        with open(cache, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return rows


def _free_signature(starter: str) -> tuple[str | None, str | None]:
    m = re.search(r"def\s+(\w+)\s*\((.*?)\)\s*(->[^:]+)?:", starter, re.DOTALL)
    if not m:
        return None, None
    name, params, ret = m.group(1), m.group(2), (m.group(3) or "").strip()
    params = re.sub(r"^\s*self\s*,?\s*", "", params.strip())
    return name, f"def {name}({params})" + (f" {ret}" if ret else "") + ":"


def build(hard: int, medium: int, out_path: str, cache: str = "/tmp/lc_raw.jsonl") -> int:
    rows = _pull_all(cache)
    print(f"raw rows: {len(rows)}")
    eligible: list[dict] = []
    for r in rows:
        diff = r.get("difficulty", "")
        if diff not in ("Medium", "Hard"):
            continue
        starter = r.get("starter_code", "") or ""
        test = r.get("test", "") or ""
        desc = r.get("problem_description", "") or ""
        if any(b in (starter + "\n" + test) for b in BANNED):
            continue
        if "def check(candidate)" not in test or not starter.strip().startswith("class Solution"):
            continue
        name, sig = _free_signature(starter)
        if not name:
            continue
        eligible.append(
            {
                "split": r.get("split"),
                "id": (r.get("task_id") or name)[:40],
                "prompt": (
                    f"{desc.strip()}\n\nImplement this as a single self-contained free Python "
                    f"function (NOT a class/method) with EXACTLY this signature, including all "
                    f"imports it needs:\n\n{sig}\n"
                ),
                "function_name": name,
                "hidden_checker": test,
                "difficulty": diff,
                "date": r.get("estimated_date", "") or "",
            }
        )
    eligible.sort(key=lambda d: d["date"], reverse=True)
    eligible.sort(key=lambda d: (d.get("split") != "test",))  # held-out split first
    h = [d for d in eligible if d["difficulty"] == "Hard"][:hard]
    m = [d for d in eligible if d["difficulty"] == "Medium"][:medium]
    sel = h + m
    for d in sel:
        d.pop("split", None)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        for d in sel:
            f.write(json.dumps(d) + "\n")
    print(f"eligible {len(eligible)} (Hard={sum(d['difficulty']=='Hard' for d in eligible)}); "
          f"wrote {len(sel)} → {out_path}")
    if sel:
        print(f"date range: {sel[-1]['date'][:10]} .. {sel[0]['date'][:10]}")
    return len(sel)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a hard LeetCode benchmark slice")
    ap.add_argument("--hard", type=int, default=24)
    ap.add_argument("--medium", type=int, default=16)
    ap.add_argument("-o", "--out", default="crucible/bench/data/leetcode_hard.jsonl")
    args = ap.parse_args()
    build(args.hard, args.medium, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
