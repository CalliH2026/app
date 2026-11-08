"""File-backed item queue shared between the teacher workspace and the writer loop.

One JSONL file (default `runs/queue.jsonl`), one item per line:
`{item_id, student, course, text, previous_value, status, created_at, updated_at, source, ...}`.
Guarded completed dictations and confirmed manual corrections enter as `pending`;
the writer claims them (`in_progress`) and records an outcome, including `unknown`
when persistence cannot be confirmed (see docs/parallel-workspace.md).

Every read and every rewrite happens under a lock file (`queue.jsonl.lock`, created with
O_EXCL) and rewrites go through a temporary file and `os.replace`, so a reader never sees
a half-written file. That is enough for one writer loop and one approval screen.

A file named STOP next to the queue file means: no new write starts. `drain()` turns every
pending item into `aborted`; it reverts nothing.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agent.queue import normalize, same_text

DEFAULT_PATH = Path("runs/queue.jsonl")
# unknown: the write may or may not have persisted (no read-back, writer died or session ended mid-item);
# aborted: stopped; `not_started=True` marks the proven never-handed-out case (STOP drain, session end). Neither is retried.
STATUSES = ("pending", "in_progress", "verified", "mismatch", "not_found", "aborted", "abstained", "unknown")
OPEN_STATUSES = ("pending", "in_progress")
FIELDS = (
    "item_id", "student", "course", "text", "previous_value", "status", "created_at", "updated_at", "source",
    "student_seen", "text_read_back", "similarity", "seconds", "retry_of", "note", "not_started",
)
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 30.0


class StopRequested(RuntimeError):
    pass


PREVIEW_STOP = "preview: STOP set at launch"


class QueueStore:
    """Persist item transitions and STOP beside one shared queue file.

    Coordinate the local UI and one writer process using atomic rewrites under a file lock.
    This is not a distributed queue. STOP drains pending items; it cannot undo an active write.
    """

    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.stop_file = self.path.with_name("STOP")

    # ---- locking and raw file access -------------------------------------

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                try:
                    if time.time() - self.lock_path.stat().st_mtime > LOCK_STALE_S:
                        self.lock_path.unlink()  # left behind by a killed process
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"could not lock {self.path} within {LOCK_TIMEOUT_S}s") from None
                time.sleep(0.01)
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def _write(self, items: list[dict[str, Any]]) -> None:
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(it, ensure_ascii=False) + "\n" for it in items)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    # ---- public API ------------------------------------------------------

    def append(self, item: Mapping[str, Any], after: str | None = None, dedupe: bool = True,
               idempotent: bool = False, refuse_when_stopped: bool = False) -> dict[str, Any]:
        """Add one item (status `pending` unless given) and return the stored record.

        With `dedupe`, an item for the same student and course with the same text (after normalization) that is
        still pending or in progress is returned instead of a second copy: a double click on Approve
        never produces two writes. With `after`, the item is inserted right after that item_id
        (a corrective write is the next one handed out), else at the end.

        With `idempotent`, an item that already has this item_id is returned (marked duplicate) whatever its
        status, even verified: a retried producer never writes twice. With `refuse_when_stopped`, STOP is checked
        under the queue lock and `StopRequested` is raised; STOP set right after the append drains the item.
        """
        rec = _record(item)
        with self._lock():
            items = self._read()
            existing = next((it for it in items if it["item_id"] == rec["item_id"]), None)
            if existing is not None:
                if idempotent:
                    return dict(existing, duplicate=True)
                raise ValueError(f"item_id {rec['item_id']!r} already in the queue")
            if refuse_when_stopped and self.stop_requested():
                raise StopRequested("STOP is set: nothing new is queued")
            if dedupe:
                for it in items:
                    if (it.get("status") in OPEN_STATUSES and _same_student(it.get("student", ""), rec["student"])
                            and (it.get("course") or None) == rec["course"]
                            and same_text(it.get("text", ""), rec["text"])):
                        return dict(it, duplicate=True)
            idx = next((i + 1 for i, it in enumerate(items) if it["item_id"] == after), len(items))
            items.insert(idx, rec)
            self._write(items)
        return rec

    def next_pending(self) -> dict[str, Any] | None:
        """Claim the first pending item (now `in_progress`), or None when there is none or STOP is set."""
        with self._lock():
            if self.stop_requested():
                return None
            items = self._read()
            for it in items:
                if it.get("status") == "pending":
                    it["status"] = "in_progress"
                    it["updated_at"] = time.time()
                    self._write(items)
                    return dict(it)
        return None

    def update(self, item_id: str, **fields: Any) -> dict[str, Any]:
        unknown = set(fields) - set(FIELDS)
        if unknown:
            raise ValueError(f"unknown item fields: {sorted(unknown)}")
        if "status" in fields:
            _check_status(fields["status"])
        with self._lock():
            items = self._read()
            for it in items:
                if it["item_id"] == item_id:
                    it.update(fields)
                    it["item_id"] = item_id
                    it["updated_at"] = time.time()
                    self._write(items)
                    return dict(it)
        raise KeyError(item_id)

    def get(self, item_id: str) -> dict[str, Any] | None:
        return next((it for it in self.all() if it["item_id"] == item_id), None)

    def all(self) -> list[dict[str, Any]]:
        with self._lock():
            return self._read()

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for it in self.all():
            out[it["status"]] = out.get(it["status"], 0) + 1
        return out

    # ---- STOP ------------------------------------------------------------

    def stop_requested(self) -> bool:
        return self.stop_file.exists()

    def stop(self, reason: str = "user") -> list[dict[str, Any]]:
        """Create the STOP file and drain the queue.

        ``reason="preview"`` marks a STOP set at launch (``ui.shell --stop``): the writer is halted exactly the same way,
        only the page presents it as an inactive preview instead of a stop the teacher asked for.
        """
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        prefix = PREVIEW_STOP if reason == "preview" else "stop requested"
        self.stop_file.write_text(f"{prefix} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")
        return self.drain()

    def stop_reason(self) -> str | None:
        """None when running, "preview" for a launch-time STOP, "user" for any other STOP (unknown content included)."""
        try:
            raw = self.stop_file.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            return "user"
        return "preview" if raw.startswith(PREVIEW_STOP.encode("utf-8")) else "user"

    def resume(self) -> None:
        try:
            self.stop_file.unlink()
        except FileNotFoundError:
            pass

    def recover(self, note: str = "writer restarted mid-item: persistence unknown, check the cell before writing again"
                ) -> list[dict[str, Any]]:
        """Items left `in_progress` by a writer that died become `unknown`: the cell may hold all, part or none of it.

        Call it when a writer starts: there is one reader, so nothing else can be in progress.
        """
        recovered = []
        with self._lock():
            items = self._read()
            now = time.time()
            for it in items:
                if it.get("status") == "in_progress":
                    it.update(status="unknown", note=note, updated_at=now)
                    recovered.append(dict(it))
            if recovered:
                self._write(items)
        return recovered

    def drain(self, note: str = "STOP: not started") -> list[dict[str, Any]]:
        """Every pending item becomes `aborted`; an item already in progress is left to finish its read-back."""
        drained = []
        with self._lock():
            items = self._read()
            now = time.time()
            for it in items:
                if it.get("status") == "pending":
                    it.update(status="aborted", note=note, not_started=True, updated_at=now)
                    drained.append(dict(it))
            if drained:
                self._write(items)
        return drained


def new_item_id() -> str:
    return "q" + time.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:4]


def _same_student(a: str, b: str) -> bool:
    return normalize(a).casefold() == normalize(b).casefold()


def _check_status(status: str) -> str:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {', '.join(STATUSES)}")
    return status


def _record(item: Mapping[str, Any]) -> dict[str, Any]:
    d = dict(item)
    unknown = set(d) - set(FIELDS)
    if unknown:
        raise ValueError(f"unknown item fields: {sorted(unknown)}")
    student = str(d.get("student") or "").strip()
    text = str(d.get("text") or "").strip()
    if not student or not text:
        raise ValueError("an item needs a student and a text")
    now = time.time()
    rec: dict[str, Any] = {
        "item_id": str(d.get("item_id") or new_item_id()),
        "student": student,
        "course": (str(d.get("course") or "").strip() or None),
        "text": text,
        "previous_value": d.get("previous_value") or None,
        "status": _check_status(d.get("status") or "pending"),
        "created_at": d.get("created_at") or now,
        "updated_at": now,
        "source": d.get("source") or "ui",
    }
    for k in FIELDS:
        if k not in rec and d.get(k) is not None:
            rec[k] = d[k]
    return rec
