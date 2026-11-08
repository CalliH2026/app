"""Build the Moodle measured set from a read-only roster pass and data/truth.csv.

Input: a JSON array produced by a read-only agent pass over the course's assignments,
one object per student row: {assignment, name, feedback_empty, feedback_excerpt, status}.
Output: a CSV for agent/run_writer.py with one approved comment per student whose
feedback field is empty, the course name, and the `set` column: the first 5 rows are
the demo set, the rest the measured set. The injection fixture comment from truth.csv
(column `fixture` = injection) is placed third, so later items can prove it changed nothing.

Usage:
    python scripts/build_moodle_set.py --roster-json runs/roster_pass.json --course "Mindful Course Creation" \
        --out data/moodle_measured.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def build(rows: list[dict], truth_rows: list[dict], course: str, assignment: str | None, max_items: int) -> list[dict]:
    empties = [r for r in rows if r.get("feedback_empty") in (True, "true", "True", 1)
               and (assignment is None or r.get("assignment") == assignment)]
    # one row per student: keep the first assignment where the field is empty
    seen: set[str] = set()
    students: list[dict] = []
    for r in empties:
        name = str(r.get("name", "")).strip()
        if name and name not in seen:
            seen.add(name)
            students.append(r)
    texts = [t for t in truth_rows if t.get("text")]
    fixture = [t for t in texts if (t.get("fixture") or "").strip() == "injection"]
    others = [t for t in texts if t not in fixture]
    ordered = others[:2] + fixture + others[2:]
    out: list[dict] = []
    for i, (stu, t) in enumerate(zip(students, ordered), start=1):
        out.append({
            "item_id": f"m{i:02d}",
            "student": stu["name"],
            "course": course,
            "assignment": stu.get("assignment", ""),
            "text": t["text"],
            "previous_value": "",
            "set": "demo" if i <= 5 else "measured",
            "fixture": t.get("fixture", ""),
        })
        if len(out) >= max_items:
            break
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--roster-json", required=True)
    p.add_argument("--truth", default="data/truth.csv")
    p.add_argument("--course", required=True)
    p.add_argument("--assignment", default=None)
    p.add_argument("--max-items", type=int, default=35)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    rows = json.loads(Path(args.roster_json).read_text(encoding="utf-8"))
    with open(args.truth, newline="", encoding="utf-8") as f:
        truth_rows = list(csv.DictReader(f))
    items = build(rows, truth_rows, args.course, args.assignment, args.max_items)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["item_id", "student", "course", "assignment", "text", "previous_value", "set", "fixture"])
        w.writeheader()
        w.writerows(items)
    print(f"wrote {len(items)} items to {args.out} ({sum(1 for i in items if i['set']=='demo')} demo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
