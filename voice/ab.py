"""Voice arm of the measurement protocol (SPEC.md section 6 item 9).

The same utterances are transcribed twice, with and without the roster as Gladia custom
vocabulary. For each arm we run the rule-based structurer on each item's transcript and compare
the assigned student with truth.csv. Outcomes per item:

- `correct`: exactly one candidate, the true student
- `abstained`: several candidates including the true student (the UI would ask)
- `wrong`: no candidate, or candidates without the true student
- `missing`: no transcript row for this item

`name_in_transcript` counts items whose transcript contains one of the true student's name forms
(display name, first name, last name, alias) after accent and case normalization: the raw effect
of the vocabulary, independent of the structurer.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from voice.roster import DEFAULT_ROSTER, Student, load_roster, normalize
from voice.structurer import RuleBasedStructurer

OUTCOMES = ("correct", "abstained", "wrong", "missing")


@dataclass
class ArmResult:
    arm: str
    n: int = 0
    correct: int = 0
    abstained: int = 0
    wrong: int = 0
    missing: int = 0
    name_in_transcript: int = 0
    per_item: list[dict] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


def read_truth(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def read_transcript(path: Path) -> dict[str, str]:
    """item_id -> transcript text (several final utterances of one item are joined in order)."""
    rows: dict[str, list[tuple[float, str]]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            item_id = (row.get("item_id") or "").strip()
            if not item_id:
                continue
            start = float(row.get("start") or 0.0)
            rows.setdefault(item_id, []).append((start, (row.get("text") or "").strip()))
    return {k: " ".join(t for _, t in sorted(v, key=lambda r: r[0])) for k, v in rows.items()}


def _name_in(text: str, student: Student) -> bool:
    hay = f" {normalize(text)} "
    return any(re.search(rf" {re.escape(normalize(f))} ", hay) for f in student.name_forms())


def score_arm(arm: str, truth: list[dict[str, str]], transcript: dict[str, str], students: list[Student]) -> ArmResult:
    structurer = RuleBasedStructurer(students)
    by_id = {s.student_id: s for s in students}
    res = ArmResult(arm)
    for row in truth:
        item_id, expected = row["item_id"], row["student_id"]
        text = transcript.get(item_id)
        res.n += 1
        candidates: list[str] = []
        if text is None:
            outcome = "missing"
        else:
            comments = [c for c in structurer.structure(text) if c.kind == "comment"]
            candidates = comments[0].student_candidates if comments else []
            if candidates == [expected]:
                outcome = "correct"
            elif expected in candidates:
                outcome = "abstained"
            else:
                outcome = "wrong"
            if expected in by_id and _name_in(text, by_id[expected]):
                res.name_in_transcript += 1
        setattr(res, outcome, getattr(res, outcome) + 1)
        res.per_item.append({"item_id": item_id, "expected": expected, "candidates": candidates,
                             "outcome": outcome, "transcript": text})
    return res


def markdown(results: list[ArmResult]) -> str:
    lines = ["| arm | n | correct | abstained | wrong | missing | name accuracy | name in transcript |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.arm} | {r.n} | {r.correct} | {r.abstained} | {r.wrong} | {r.missing} "
                     f"| {r.correct}/{r.n} ({r.accuracy:.0%}) | {r.name_in_transcript}/{r.n} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Name-assignment accuracy with and without Gladia custom vocabulary.")
    p.add_argument("--truth", required=True, help="truth.csv: item_id, student_id, text")
    p.add_argument("--with-vocab", required=True, help="transcript CSV from `voice.gladia_live --out` (vocabulary on)")
    p.add_argument("--without-vocab", required=True, help="transcript CSV from `voice.gladia_live --no-vocab --out`")
    p.add_argument("--roster", default=str(DEFAULT_ROSTER))
    p.add_argument("--json", help="also write per-item results to this JSON file")
    args = p.parse_args(argv)

    students = load_roster(Path(args.roster))
    truth = read_truth(Path(args.truth))
    results = [score_arm("with vocabulary", truth, read_transcript(Path(args.with_vocab)), students),
               score_arm("without vocabulary", truth, read_transcript(Path(args.without_vocab)), students)]
    print(markdown(results))
    if args.json:
        payload = [{**asdict(r), "accuracy": r.accuracy} for r in results]
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0
