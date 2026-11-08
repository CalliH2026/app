"""Approved-items queue and text comparison.

The queue is the boundary between the human side (dictation, approval) and the
agent side (write, read back). Only items in the queue can ever be written: the
agent has no other source of text. A STOP file next to the run directory drains
the queue immediately, which is how the visible STOP control works at loop level.
"""

from __future__ import annotations

import csv
import difflib
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.queue_store import QueueStore


@dataclass
class Item:
    item_id: str
    student: str
    text: str
    previous_value: str | None = None
    course: str | None = None  # optional: where to find the student (Moodle course, PRONOTE class)
    status: str = "pending"  # pending, in_progress, written, verified, mismatch, abstained, aborted, not_found, unknown
    text_read_back: str | None = None
    student_seen: str | None = None

    @classmethod
    def from_record(cls, rec: dict[str, Any]) -> Item:
        return cls(item_id=rec["item_id"], student=rec["student"], text=rec["text"],
                   previous_value=rec.get("previous_value") or None, course=rec.get("course") or None,
                   status=rec.get("status") or "pending", text_read_back=rec.get("text_read_back"),
                   student_seen=rec.get("student_seen"))


@dataclass
class Queue:
    items: list[Item] = field(default_factory=list)
    stop_file: Path | None = None
    store: QueueStore | None = None  # live mode: items come from the file-backed store, shared with the UI

    @classmethod
    def from_store(cls, path: Path, stop_file: Path | None = None) -> Queue:
        """Wrap the live queue file written by the approval screen (agent/queue_store.py)."""
        from agent.queue_store import QueueStore

        store = QueueStore(path)
        q = cls(items=[], stop_file=stop_file or store.stop_file, store=store)
        q.refresh()
        return q

    def refresh(self) -> None:
        """Reload the items from the store (live mode); no-op for a CSV queue."""
        if self.store is not None:
            self.items = [Item.from_record(r) for r in self.store.all()]

    def save(self, item: Item, **extra: Any) -> None:
        """Persist an item's status and read-back to the store (live mode); no-op for a CSV queue."""
        if self.store is not None:
            self.store.update(item.item_id, status=item.status, student_seen=item.student_seen,
                              text_read_back=item.text_read_back, **extra)

    @classmethod
    def from_csv(cls, path: Path, stop_file: Path | None = None, only_set: str | None = None) -> Queue:
        items: list[Item] = []
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if only_set and (row.get("set") or "").strip() and row["set"].strip() != only_set:
                    continue
                items.append(
                    Item(
                        item_id=row["item_id"].strip(),
                        student=row["student"].strip(),
                        text=row["text"].strip(),
                        previous_value=(row.get("previous_value") or None),
                        course=((row.get("course") or "").strip() or None),
                    )
                )
        return cls(items=items, stop_file=stop_file)

    def stop_requested(self) -> bool:
        return bool(self.stop_file and self.stop_file.exists())

    def next_pending(self) -> Item | None:
        if self.stop_requested():
            if self.store is not None:
                self.store.drain()
                self.refresh()
            return None
        if self.store is not None:
            rec = self.store.next_pending()
            self.refresh()
            return self.get(rec["item_id"]) if rec else None
        for it in self.items:
            if it.status == "pending":
                it.status = "in_progress"
                return it
        return None

    def get(self, item_id: str) -> Item | None:
        if self.store is not None and not any(it.item_id == item_id for it in self.items):
            self.refresh()
        for it in self.items:
            if it.item_id == item_id:
                return it
        return None

    def pending_count(self) -> int:
        return sum(1 for it in self.items if it.status == "pending")

    def add_retry(self, item: Item, wrong_value: str | None) -> Item | None:
        """Queue one corrective write for a mismatched item: same text, previous_value = what the cell holds now.

        One retry per original item; a retry that mismatches again stays `mismatch`. None after STOP.
        """
        if item.item_id.endswith("-r1") or self.stop_requested():
            return None
        retry_id = f"{item.item_id}-r1"
        if self.get(retry_id) is not None:
            return None
        retry = Item(item_id=retry_id, student=item.student, text=item.text,
                     previous_value=wrong_value or None, course=item.course)
        if self.store is not None:
            self.store.append({"item_id": retry_id, "student": retry.student, "text": retry.text,
                               "previous_value": retry.previous_value, "course": retry.course,
                               "source": "retry", "retry_of": item.item_id}, after=item.item_id, dedupe=False)
            self.refresh()
            return self.get(retry_id)
        # insert right after the original so it is the next item handed out
        idx = self.items.index(item)
        self.items.insert(idx + 1, retry)
        return retry

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for it in self.items:
            out[it.status] = out.get(it.status, 0) + 1
        return out


_QUOTES = {
    "’": "'", "‘": "'", "“": '"', "”": '"', "«": '"', "»": '"',
    " ": " ", " ": " ", "…": "...",
}


def normalize(text: str) -> str:
    """Normalize a comment for comparison: unicode NFC, straight quotes, single spaces, trimmed.

    Case and accents are kept: "Lea" and "Léa" are different words in a report card.
    """
    t = unicodedata.normalize("NFC", text or "")
    for k, v in _QUOTES.items():
        t = t.replace(k, v)
    t = re.sub(r"\s+", " ", t).strip()
    # tolerate a missing or extra final period, nothing else
    return t.rstrip(".").strip()


def same_text(expected: str, read_back: str) -> bool:
    return normalize(expected) == normalize(read_back)


def similarity(expected: str, read_back: str) -> float:
    return difflib.SequenceMatcher(None, normalize(expected), normalize(read_back)).ratio()


def load_names(rows: Iterable[dict]) -> list[str]:
    return [r["student"] for r in rows]
