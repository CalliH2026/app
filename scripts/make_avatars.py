"""Fetch the illustrated avatars of the fictitious roster once, from the DiceBear HTTP API.

One SVG per student is written to ui/static/avatars/<student_id>.svg and committed: the approval
screen never calls the network. Style: DiceBear "adventurer", a remix of "Adventurer" by Lisa
Wischofsky, CC BY 4.0 (attribution in docs/ui.md). The seed is the student_id, so a rerun gives
the same faces. Girls get long hair, boys short hair, chosen from the first name below; facial
hair is never drawn, so every face reads as a teenager.

Usage: python scripts/make_avatars.py [--roster data/roster.csv ...] [--force]
"""

from __future__ import annotations

import argparse
import csv
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "ui" / "static" / "avatars"
ROSTERS = [ROOT / "data" / "roster.csv", ROOT / "data" / "roster_moodle.csv"]
API = "https://api.dicebear.com/9.x/adventurer/svg"

GIRLS = {"Gaëlle", "Léa", "Chloé", "Inès", "Carolyn", "Joyce", "Heather", "Stephanie", "Laura", "Julie", "Mary",
         "Amy", "Jennifer", "Ann", "Lisa", "Barbara"}
BOYS = {"Lucas", "Gaël", "Maximilien", "Yanis", "Noé", "John", "David", "Jason", "William", "Mark", "Richard",
        "Peter", "Donald", "Charles", "Brian"}
LONG_HAIR = [f"long{i:02d}" for i in range(1, 27)]
SHORT_HAIR = [f"short{i:02d}" for i in range(1, 20)]
NATURAL_HAIR = ["0e0e0e", "562306", "6a4e35", "796a45", "ac6511", "cb6820", "ab2a18", "b9a05f", "e5d7a3"]
# friendly expressions only: no frown, no grimace, no sunglasses
EYES = [f"variant{i:02d}" for i in (1, 2, 3, 9, 10, 11, 12, 19, 24, 25, 26)]
EYEBROWS = [f"variant{i:02d}" for i in (3, 4, 5, 6, 8, 10, 11, 12, 13, 14, 15)]
MOUTHS = [f"variant{i:02d}" for i in (1, 2, 22, 25, 27, 28, 29, 30)]
GLASSES = [f"variant{i:02d}" for i in (2, 3, 4, 5)]
BACKGROUNDS = ["b6e3f4", "c0aede", "d1d4f9", "ffd5dc", "ffdfbf"]


def avatar_url(student_id: str, first_name: str) -> str:
    if first_name in GIRLS:
        hair, earrings = LONG_HAIR, 30
    elif first_name in BOYS:
        hair, earrings = SHORT_HAIR, 0
    else:
        raise SystemExit(f"{first_name!r} ({student_id}) is in neither GIRLS nor BOYS: add it")
    params = {
        "seed": student_id,
        "hair": ",".join(hair),
        "hairColor": ",".join(NATURAL_HAIR),
        "eyes": ",".join(EYES),
        "eyebrows": ",".join(EYEBROWS),
        "mouth": ",".join(MOUTHS),
        "glasses": ",".join(GLASSES),
        "features": "blush,freckles",
        "featuresProbability": 40,
        "earringsProbability": earrings,
        "glassesProbability": 15,
        "backgroundColor": ",".join(BACKGROUNDS),
        "scale": 90,
    }
    return f"{API}?{urlencode(params)}"


def students(rosters: list[Path]) -> list[tuple[str, str]]:
    out = []
    for path in rosters:
        with open(path, newline="", encoding="utf-8") as f:
            out += [(r["student_id"].strip(), r["display_name"].split()[0]) for r in csv.DictReader(f)]
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--roster", action="append", type=Path, help="roster CSV (repeatable; default: both rosters)")
    p.add_argument("--force", action="store_true", help="fetch again even if the file exists")
    args = p.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for student_id, first in students(args.roster or ROSTERS):
        dest = OUT_DIR / f"{student_id}.svg"
        if dest.exists() and not args.force:
            continue
        req = urllib.request.Request(avatar_url(student_id, first), headers={"User-Agent": "calligraphe"})
        with urllib.request.urlopen(req, timeout=30) as r:
            svg = r.read()
        if not svg.lstrip().startswith(b"<svg"):
            raise SystemExit(f"{student_id}: not an SVG")
        dest.write_bytes(svg)
        print(f"{dest.relative_to(ROOT)} {len(svg)} bytes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
