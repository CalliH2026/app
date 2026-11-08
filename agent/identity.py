"""Student identity check on the writer's read-back.

A write is only verified when the full student name REPORTED in the agent's read-back (`student_seen`)
is the student the teacher approved. This is a check on what the agent reports, not proof that the
physical row it typed into belongs to that student, and not an independent visual audit of the screen.
A reported wrong or missing name is never verified, billed or retried.

Names are compared as full token multisets after Unicode NFC, casefold and whitespace cleanup, so the
PRONOTE display "BERNARD Lucas" matches "Lucas Bernard". Accents and hyphenated tokens are kept as they
are; there is no fuzzy or partial match: "Gaël" is not "Gaël Lambert", "Gael" is not "Gaël".
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

_SEPARATORS = re.compile(r"[\s,]+")


def name_tokens(name: str | None) -> Counter[str]:
    t = unicodedata.normalize("NFC", name or "").casefold()
    return Counter(tok for tok in _SEPARATORS.split(t) if tok)


def same_student(expected: str | None, seen: str | None) -> bool:
    want = name_tokens(expected)
    return bool(want) and want == name_tokens(seen)


def identity_mismatch(expected: str | None, seen: str | None) -> str | None:
    """None when `seen` is the expected student, else the reason to journal."""
    if same_student(expected, seen):
        return None
    if not name_tokens(seen):
        return f"identity: no student name read back, expected {expected!r}"
    return f"identity: read back the row of {seen!r}, expected {expected!r}"
