"""Class roster loading, name normalization and the Gladia custom vocabulary.

`data/roster.csv` columns: `student_id, display_name, aliases`. Aliases are
separated by `|` (`;` is accepted too) and cover nicknames and spelling
variants ("Max", "Coco").
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROSTER = Path(__file__).resolve().parent.parent / "data" / "roster.csv"

_ALIAS_SEP = re.compile(r"[|;]")
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class Student:
    student_id: str
    display_name: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def name_forms(self) -> list[str]:
        """Every way the teacher may say this student's name: full name, first name, last name, aliases."""
        parts = self.display_name.split()
        forms = [self.display_name]
        if len(parts) > 1:
            forms += [parts[0], " ".join(parts[1:])]
        forms += list(self.aliases)
        seen: set[str] = set()
        unique = []
        for f in forms:
            key = normalize(f)
            if key and key not in seen:
                seen.add(key)
                unique.append(f)
        return unique


def load_roster(path: Path = DEFAULT_ROSTER) -> list[Student]:
    students: list[Student] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            if not row.get("student_id"):
                continue
            aliases = tuple(a.strip() for a in _ALIAS_SEP.split(row.get("aliases", "")) if a.strip())
            students.append(Student(row["student_id"], row["display_name"], aliases))
    return students


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize(s: str) -> str:
    """Accent- and case-insensitive form: 'Maëlle  Roux!' -> 'maelle roux'."""
    return " ".join(_WORD.findall(strip_accents(s).lower()))


_PHONETIC_RULES: list[tuple[str, str]] = [
    (r"ch", "S"),
    (r"ph", "f"),
    (r"qu", "k"),
    (r"ck", "k"),
    (r"c(?=[eiy])", "s"),
    (r"c", "k"),
    (r"g(?=[eiy])", "j"),
    (r"h", ""),
    (r"y", "i"),
    (r"eau", "o"),
    (r"au", "o"),
    (r"[ae]i", "e"),
    (r"en", "an"),
    (r"z", "s"),
    (r"(.)\1+", r"\1"),
    (r"(?<=..)e$", ""),
    (r"(?<=..)[stxd]$", ""),
]


def phonetic(word: str) -> str:
    """Rough French phonetic key so that homophones collide: 'Maëlle' and 'Maël' -> 'mael', 'Inesse' -> 'ine'."""
    out = []
    for w in normalize(word).split():
        for pattern, repl in _PHONETIC_RULES:
            w = re.sub(pattern, repl, w)
        out.append(w)
    return " ".join(out)


def vocabulary_terms(students: list[Student]) -> list[str]:
    """Unique name words for Gladia's custom vocabulary: first names, last names and aliases."""
    terms: list[str] = []
    seen: set[str] = set()
    for s in students:
        for term in [*s.display_name.split(), *s.aliases]:
            key = normalize(term)
            if key and key not in seen:
                seen.add(key)
                terms.append(term)
    return terms
