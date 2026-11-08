"""Aggregate the runs into the few numbers the pitch deck and the video use.

Reads runs/*/journal.jsonl and summary.json (same rules as scripts/report.py: final status per item,
a corrective retry belongs to its item) and writes one JSON with per-arm and per-target totals.
The deck build script and the Remotion scoreboard read this file, so no number is ever typed by hand.

Usage:
    python scripts/pitch_numbers.py --out docs/pitch-numbers.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.report import base_item, read_journal


def aggregate(runs_dir: Path, exclude_before: str | None = None) -> dict:
    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "runs": 0, "attempted": 0, "verified": 0, "not_found": 0, "mismatch": 0, "false_success": 0,
        "aborted": 0, "abstained": 0, "seconds": [], "steps": 0, "tokens": 0, "cost_usd": 0.0,
        "tokens_known": True, "cost_known": True, "sessions": [],
    })
    for journal in sorted(runs_dir.glob("*/journal.jsonl")):
        name = journal.parent.name
        if exclude_before and name < exclude_before:
            continue
        events = read_journal(journal)
        if not events:
            continue
        sp = journal.parent / "summary.json"
        summary = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        arm = next((e.get("arm") for e in events if e.get("arm")), summary.get("arm") or "calligraphe")
        target = next((e.get("target") for e in events if e.get("target")), summary.get("target") or "?")
        g = groups[(arm, target)]
        g["runs"] += 1
        items: dict[str, list[dict]] = defaultdict(list)
        for e in events:
            items[base_item(e["item_id"])].append(e)
        for evs in items.values():
            final = evs[-1]["status"]
            g["attempted"] += 1
            if final in g:
                g[final] += 1
            secs = sum(e.get("seconds") or 0 for e in evs)
            if secs:
                g["seconds"].append(secs)
        g["steps"] += summary.get("steps") or 0
        if summary.get("tokens") is None:
            g["tokens_known"] = False
        else:
            g["tokens"] += summary["tokens"]
        if summary.get("cost_usd") is None:
            g["cost_known"] = False
        else:
            g["cost_usd"] += summary["cost_usd"]
        if summary.get("session_id"):
            g["sessions"].append(summary["session_id"])
    out = {}
    for (arm, target), g in groups.items():
        v = g["verified"]
        out[f"{arm}/{target}"] = {
            "arm": arm, "target": target, "runs": g["runs"], "attempted": g["attempted"], "verified": v,
            "not_found": g["not_found"], "mismatch": g["mismatch"], "false_success": g["false_success"],
            "aborted": g["aborted"],
            "verified_share": round(v / g["attempted"], 3) if g["attempted"] else None,
            "seconds_median": round(statistics.median(g["seconds"]), 1) if g["seconds"] else None,
            "seconds_worst": round(max(g["seconds"]), 1) if g["seconds"] else None,
            "steps": g["steps"] or None,
            "tokens_per_verified": round(g["tokens"] / v) if g["tokens_known"] and g["tokens"] and v else None,
            "cost_per_verified_usd": round(g["cost_usd"] / v, 3) if g["cost_known"] and v else None,
            "sessions": g["sessions"],
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", default="runs")
    p.add_argument("--out", default="docs/pitch-numbers.json")
    p.add_argument("--exclude-before", default=None, help="skip run directories whose name sorts before this (e.g. the first exploratory runs)")
    args = p.parse_args()
    data = aggregate(Path(args.runs), args.exclude_before)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in data.items():
        print(f"{k}: {v['verified']}/{v['attempted']} verified, not_found {v['not_found']}, mismatch {v['mismatch']}, "
              f"median {v['seconds_median']} s, ${v['cost_per_verified_usd']} per verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
