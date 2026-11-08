"""Append-only JSONL journal of every write, verification, abstention and undo.

One line per event. The scoreboard in the README is rendered from these files
only (scripts/report.py); nothing in the README is typed by hand.

Field meanings (SPEC.md section 5, plus run context):
- `before` / `after`: cell content before the write and the text the write puts there.
- `step`: agent step index at which the event was recorded, when known.
- `tokens` / `cost_eur`: consumed since the previous event of the same session, so they add up per run.
- `seconds`: wall time spent on the item for this event (retries are separate events).
- `billed`: on a `verified` line, whether its Stripe meter event was accepted (billing/meter.py);
  null when metering is not configured.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

STATUSES = ("written", "verified", "mismatch", "abstained", "false_success", "aborted", "not_found", "unknown")
# statuses after which the cell may hold text the agent typed, hence something to undo
WROTE_STATUSES = ("written", "verified", "mismatch", "false_success")

SPEC_FIELDS = [
    "ts", "item_id", "student", "before", "after", "status", "screenshot", "session_id", "step", "tokens",
    "cost_eur", "model",
]
FIELDS = [
    "ts", "arm", "target", "run_id", "session_id", "item_id", "student", "student_seen",
    "before", "after", "text_read_back", "status", "similarity", "step", "seconds", "tokens",
    "cost_eur", "model", "screenshot", "billed", "note",
]
assert set(SPEC_FIELDS) <= set(FIELDS)
_RETRY = re.compile(r"-r\d+$")


def base_item(item_id: str) -> str:
    """A corrective retry (`g01-r1`) belongs to its original item (`g01`)."""
    return _RETRY.sub("", item_id)


def check_status(status: str) -> str:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {', '.join(STATUSES)}")
    return status


@dataclass
class Event:
    item_id: str
    student: str
    status: str
    arm: str | None = None
    target: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    student_seen: str | None = None
    before: str | None = None
    after: str | None = None
    text_read_back: str | None = None
    similarity: float | None = None
    step: int | None = None
    seconds: float | None = None
    tokens: int | None = None
    cost_eur: float | None = None
    model: str | None = None
    screenshot: str | None = None
    billed: bool | None = None
    note: str | None = None
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        check_status(self.status)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: d.get(k) for k in FIELDS}


def normalize_event(event: Event | Mapping[str, Any]) -> dict[str, Any]:
    """Validate an event and return it with every field of FIELDS, in order (missing ones are null)."""
    d = event.to_dict() if isinstance(event, Event) else dict(event)
    for key in ("item_id", "student", "status"):
        if not d.get(key):
            raise ValueError(f"event without {key}: {d!r}")
    check_status(d["status"])
    unknown = set(d) - set(FIELDS)
    if unknown:
        raise ValueError(f"unknown event fields: {sorted(unknown)}")
    if d.get("ts") is None:
        d["ts"] = time.time()
    return {k: d.get(k) for k in FIELDS}


def read_journal(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class Journal:
    """Append-only: events are only ever added at the end of the file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: Event | Mapping[str, Any]) -> dict[str, Any]:
        row = normalize_event(event)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def read(self) -> list[dict[str, Any]]:
        return read_journal(self.path)

    def last_for(self, item_id: str) -> dict[str, Any] | None:
        for ev in reversed(self.read()):
            if ev.get("item_id") == item_id:
                return ev
        return None

    def last_write(self) -> dict[str, Any] | None:
        """The most recent event that left typed text in a cell: the target of "annule la dernière"."""
        for ev in reversed(self.read()):
            if ev.get("status") in WROTE_STATUSES:
                return ev
        return None

    def undo_last(self) -> dict[str, Any] | None:
        """Undo event for the last write, restoring the cell as it was before its item's first attempt.

        Later events of the same item (verification, corrective retry) may carry a
        `before` that is no longer the original value, so the first one is used.
        """
        events = self.read()
        last = next((ev for ev in reversed(events) if ev.get("status") in WROTE_STATUSES), None)
        if last is None:
            return None
        base = base_item(last["item_id"])
        first = next(ev for ev in events if base_item(ev["item_id"]) == base)
        return undo_entry(last, restore=first.get("before") or "")


def undo_entry(previous: Mapping[str, Any], restore: str | None = None) -> dict[str, Any]:
    """The write-back event that restores the cell to its value before `previous`.

    An undo is a write like any other: the returned event (item `<item_id>-undo`,
    status `written`) is journaled once the agent has typed it, then verified by
    read-back. `before` is what the cell holds now (the read-back if there was one),
    `after` is the value to restore: `restore` if given, else `previous["before"]`.
    Prefer `Journal.undo_last`, which finds the original value across retries.
    """
    status = previous.get("status")
    if status not in WROTE_STATUSES:
        raise ValueError(f"nothing to undo for an event with status {status!r}")
    current = previous.get("text_read_back")
    if current is None:
        current = previous.get("after")
    return Event(
        item_id=f"{previous['item_id']}-undo",
        student=previous["student"],
        status="written",
        arm=previous.get("arm"),
        target=previous.get("target"),
        run_id=previous.get("run_id"),
        session_id=previous.get("session_id"),
        before=current,
        after=restore if restore is not None else previous.get("before") or "",
        model=previous.get("model"),
        note=f"undo of {previous['item_id']}",
    ).to_dict()
