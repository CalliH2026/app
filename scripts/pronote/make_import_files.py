"""Build the PRONOTE trial import files from the Calligraphe roster.

Reads ``data/roster.csv`` (``student_id, display_name, aliases``, see SPEC.md section 5) when it
exists; otherwise uses the fictitious fallback roster below. Writes tab-separated text files (the
separator PRONOTE's import window expects) and CSV copies into ``scripts/pronote/import-files/``.
Files are UTF-8 with a byte-order mark: PRONOTE 2026.2.8 reads UTF-8 without one as ANSI and
garbles accented names (verified in the trial VM, docs/pronote-vm-notes.md).

Usage: python scripts/pronote/make_import_files.py [--roster data/roster.csv] [--out DIR]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROSTER = REPO / "data" / "roster.csv"
DEFAULT_OUT = Path(__file__).resolve().parent / "import-files"

CLASS_NAME = "3A"
SUBJECT = "FRANCAIS"

# Fictitious students. Constraints kept from the demo set: two students share a first name (Léa),
# two surnames sound alike (Lefèvre / Lefebvre), and one student goes by a nickname (Max).
FALLBACK_ROSTER: list[dict[str, str]] = [
    {"student_id": "S01", "display_name": "Léa Martin", "aliases": "Léa M."},
    {"student_id": "S02", "display_name": "Léa Dubois", "aliases": "Léa D."},
    {"student_id": "S03", "display_name": "Camille Lefèvre", "aliases": ""},
    {"student_id": "S04", "display_name": "Hugo Lefebvre", "aliases": ""},
    {"student_id": "S05", "display_name": "Maximilien Roux", "aliases": "Max"},
    {"student_id": "S06", "display_name": "Inès Moreau", "aliases": ""},
    {"student_id": "S07", "display_name": "Nathan Girard", "aliases": ""},
    {"student_id": "S08", "display_name": "Chloé Fontaine", "aliases": ""},
    {"student_id": "S09", "display_name": "Yanis Mercier", "aliases": ""},
    {"student_id": "S10", "display_name": "Zoé Perrin", "aliases": ""},
]

# Fictitious teacher. The login and password are chosen by the human in PRONOTE, never stored here.
TEACHER = {"last_name": "DURAND", "first_name": "Sophie", "subject": SUBJECT}

STUDENT_HEADER = ["Nom", "Prénom", "Classe"]
TEACHER_HEADER = ["Nom", "Prénom", "Matière"]

# "utf-8-sig" writes the UTF-8 byte-order mark PRONOTE needs to detect the encoding.
ENCODING = "utf-8-sig"


def load_roster(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return [dict(row) for row in FALLBACK_ROSTER]
    with path.open(encoding="utf-8", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def split_name(display_name: str) -> tuple[str, str]:
    """Split "Prénom Nom" into (last name in capitals, first name); the first word is the first name."""
    first, _, last = display_name.strip().partition(" ")
    if not last:
        raise ValueError(f"display_name needs a first and a last name: {display_name!r}")
    return last.upper(), first


def student_rows(roster: list[dict[str, str]], class_name: str = CLASS_NAME) -> list[list[str]]:
    return [[*split_name(r["display_name"]), class_name] for r in roster]


def teacher_rows() -> list[list[str]]:
    return [[TEACHER["last_name"], TEACHER["first_name"], TEACHER["subject"]]]


def write_table(path_stem: Path, header: list[str], rows: list[list[str]]) -> list[Path]:
    txt = path_stem.with_suffix(".txt")
    csv_path = path_stem.with_suffix(".csv")
    with txt.open("w", encoding=ENCODING, newline="") as f:
        csv.writer(f, delimiter="\t", lineterminator="\r\n").writerows([header, *rows])
    with csv_path.open("w", encoding=ENCODING, newline="") as f:
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows([header, *rows])
    return [txt, csv_path]


def build(roster_path: Path = DEFAULT_ROSTER, out_dir: Path = DEFAULT_OUT) -> list[Path]:
    roster = load_roster(roster_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = write_table(out_dir / "eleves", STUDENT_HEADER, student_rows(roster))
    written += write_table(out_dir / "professeurs", TEACHER_HEADER, teacher_rows())
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    source = args.roster if args.roster.exists() else "built-in fictitious fallback roster"
    for path in build(args.roster, args.out):
        print(f"wrote {path} (from {source})")


if __name__ == "__main__":
    main()
