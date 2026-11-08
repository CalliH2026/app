"""Unknown writes at the writer boundary: claimed aborts, repeated reports, the run summary. Offline.

The H session is replaced by a fake `hai_agents` module whose run_session calls the real tools; the queue,
journal and summary are real.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from agent import run_writer
from agent.journal import Journal
from agent.queue import Queue
from agent.queue_store import QueueStore

TEXT = "Bon trimestre."


def _report(tmp_path: Path):
    store = QueueStore(tmp_path / "queue.jsonl")
    store.append({"item_id": "q1", "student": "Lucas Bernard", "text": TEXT, "course": "3A, FRANCAIS, Trimestre 1"})
    queue = Queue.from_store(store.path)
    assert queue.next_pending().item_id == "q1"
    journal = Journal(tmp_path / "journal.jsonl")
    return store, queue, journal, run_writer.make_report_result(queue, journal, {}, run_id="r", arm="calligraphe",
                                                                target="pronote", retry=True)


def test_claimed_item_reported_aborted_is_unknown_and_never_retried(tmp_path):
    store, queue, journal, report = _report(tmp_path)
    reply = report("q1", "aborted", "Lucas Bernard", "Bon tri")
    assert store.get("q1")["status"] == "unknown" and queue.next_pending() is None
    assert [it["item_id"] for it in store.all()] == ["q1"]
    [row] = journal.read()
    assert row["status"] == "unknown" and "partial write" in row["note"] and row["billed"] is None
    assert "do not write it again" in reply.lower()


def test_unknown_is_terminal_for_later_reports(tmp_path):
    store, _queue, journal, report = _report(tmp_path)
    report("q1", "written", "Lucas Bernard", "")
    assert "already reported as unknown" in report("q1", "written", "Lucas Bernard", TEXT)
    assert store.get("q1")["status"] == "unknown" and len(journal.read()) == 1


def test_run_summary_counts_a_lost_item_as_unknown_not_in_progress(tmp_path, monkeypatch):
    store = QueueStore(tmp_path / "queue.jsonl")
    store.append({"item_id": "q1", "student": "Lucas Bernard", "text": TEXT})

    class FakeClient:
        def run_session(self, *, tools, **kwargs):
            tools[0]()  # next_item hands q1 out; the session then ends without report_result
            return types.SimpleNamespace(id="sess-lost", status="timed_out", outcome=None, error=None,
                                         error_code=None, answer=None, events=[])

    monkeypatch.setitem(sys.modules, "hai_agents", types.SimpleNamespace(Client=FakeClient))
    monkeypatch.setenv("HAI_API_KEY", "test-only")
    run_dir = tmp_path / "run"
    code = run_writer.main(["--queue", str(store.path), "--target", "moodle", "--run-dir", str(run_dir),
                            "--idle-timeout", "0"])
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["items"] == {"unknown": 1} and code == 1
    assert store.get("q1")["status"] == "unknown"
    [row] = Journal(run_dir / "journal.jsonl").read()
    assert row["status"] == "unknown" and row["session_id"] == "sess-lost"
