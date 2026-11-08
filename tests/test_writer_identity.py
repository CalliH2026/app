"""Identity gate on the writer's read-back: a write is verified only when the text AND the student match.

The tests go through the real Queue (CSV and file-backed store), the real Journal and the billing boundary
(bill_verified, with a recording Stripe transport): a reported wrong or missing name is never verified,
retried or billed. The check is on the agent's read-back, not an independent audit of the screen.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent import run_writer
from agent.identity import identity_mismatch, same_student
from agent.journal import Journal
from agent.queue import Item, Queue
from agent.queue_store import QueueStore

FAKE_KEY = "sk_test_" + "0" * 24
TEXT = "Lucas doit soigner son expression écrite et oser prendre la parole à l'oral."


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"object": "ok"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def stripe_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_KEY)
    monkeypatch.setenv("STRIPE_CUSTOMER_ID", "cus_demo")


# ---- name matching ------------------------------------------------------------


@pytest.mark.parametrize("seen", ["Lucas Bernard", "BERNARD Lucas", "  bernard   lucas ", "BERNARD, Lucas",
                                  "Lucas\u00a0Bernard"])
def test_same_student_accepts_display_and_pronote_order(seen):
    assert same_student("Lucas Bernard", seen)


@pytest.mark.parametrize("expected, seen", [
    ("Lucas Bernard", "Lucas Petit"),       # same first name, other pupil
    ("Gaël Lambert", "Gaël"),               # first name only
    ("Gaël Lambert", "LAMBERT"),            # family name only
    ("Gaël Lambert", "Gael Lambert"),       # accents are part of the name
    ("Gaël Lambert", "Gaëlle Lambert"),     # no prefix or fuzzy match
    ("Lucas Bernard", "Lucas Lucas Bernard"),  # repeated tokens count
    ("Lucas Bernard", "Lucas Bernard Petit"),
    ("Lucas Bernard", ""),
    ("Lucas Bernard", "   "),
    ("", ""),
])
def test_same_student_refuses_anything_but_the_full_name(expected, seen):
    assert not same_student(expected, seen)


def test_same_student_keeps_hyphenated_tokens_and_nfc():
    assert same_student("Jean-Baptiste Lefèvre", "LEFÈVRE Jean-Baptiste")
    assert same_student("Noé Lefèvre", "No\u0065\u0301 Lef\u0065\u0300vre")  # decomposed accents
    assert not same_student("Jean-Baptiste Lefèvre", "Jean Baptiste Lefèvre")
    assert not same_student("Jean-Baptiste Lefèvre", "Jean Lefèvre")


def test_identity_mismatch_reason_names_both_identities():
    assert identity_mismatch("Lucas Bernard", "BERNARD Lucas") is None
    assert "no student name" in identity_mismatch("Lucas Bernard", "")
    reason = identity_mismatch("Lucas Bernard", "Lucas Petit")
    assert "Lucas Petit" in reason and "Lucas Bernard" in reason


# ---- the report_result tool -----------------------------------------------------


def _csv_writer(tmp_path: Path, recorder: Recorder, retry: bool = True):
    items = tmp_path / "items.csv"
    items.write_text(f"item_id,student,text\ng01,Lucas Bernard,{TEXT}\n", encoding="utf-8")
    queue = Queue.from_csv(items, stop_file=tmp_path / "STOP")
    queue.next_pending()
    journal = Journal(tmp_path / "journal.jsonl")
    report = run_writer.make_report_result(queue, journal, {}, run_id="20261107-180000", arm="calligraphe",
                                           target="pronote", retry=retry, billing_client=recorder.client())
    return queue, journal, report


def _live_writer(tmp_path: Path, recorder: Recorder):
    store = QueueStore(tmp_path / "queue.jsonl")
    store.append({"item_id": "q1", "student": "Lucas Bernard", "text": TEXT, "course": "3A, FRANCAIS, Trimestre 1"})
    queue = Queue.from_store(store.path)
    assert queue.next_pending().item_id == "q1"
    journal = Journal(tmp_path / "journal.jsonl")
    report = run_writer.make_report_result(queue, journal, {}, run_id="20261107-180000", arm="calligraphe",
                                           target="pronote", billing_client=recorder.client())
    return store, queue, journal, report


@pytest.mark.parametrize("seen", ["Lucas Bernard", "BERNARD Lucas"])
def test_correct_identity_and_text_is_verified_and_billed_once(tmp_path, stripe_env, seen):
    rec = Recorder()
    queue, journal, report = _csv_writer(tmp_path, rec)
    reply = report("g01", "written", seen, TEXT)
    assert "recorded as verified" in reply
    assert queue.get("g01").status == "verified"
    rows = journal.read()
    assert len(rows) == 1 and rows[0]["status"] == "verified" and rows[0]["student_seen"] == seen
    assert rows[0]["billed"] is True and len(rec.requests) == 1


@pytest.mark.parametrize("seen", ["Lucas Petit", "Lucas", "", "Lucas Lucas Bernard"])
def test_wrong_or_missing_identity_with_matching_text_is_mismatch_not_billed_not_retried(tmp_path, stripe_env, seen):
    rec = Recorder()
    queue, journal, report = _csv_writer(tmp_path, rec)
    reply = report("g01", "written", seen, TEXT)
    it = queue.get("g01")
    assert it.status == "mismatch"
    assert queue.get("g01-r1") is None and len(queue.items) == 1
    assert rec.requests == []
    rows = journal.read()
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "mismatch" and row["billed"] is None
    assert "identity" in row["note"] and "Lucas Bernard" in row["note"]
    assert "recorded as mismatch" in reply and "no corrective write" in reply.lower()


@pytest.mark.parametrize("seen", ["BERNARD Lucas", ""])
def test_written_without_read_back_is_unknown_and_never_retried(tmp_path, stripe_env, seen):
    rec = Recorder()
    queue, journal, report = _csv_writer(tmp_path, rec)
    reply = report("g01", "written", seen, "  ")
    assert queue.get("g01").status == "unknown"
    assert queue.get("g01-r1") is None and queue.next_pending() is None
    assert rec.requests == []
    [row] = journal.read()
    assert row["status"] == "unknown" and row["billed"] is None and "persistence unknown" in row["note"]
    assert "recorded as unknown" in reply and "do not write it again" in reply.lower()


def test_session_end_marks_started_items_unknown_and_unstarted_items_aborted(tmp_path, stripe_env):
    queue, journal, _report = _csv_writer(tmp_path, Recorder())
    assert queue.get("g01").status == "in_progress"  # handed out to the agent, never reported
    queue.items.append(Item(item_id="g02", student="Léa Girard", text="Bon trimestre."))
    run_writer.settle_unfinished(queue.items, queue, journal, run_id="r", arm="calligraphe", target="pronote",
                                 session_id="sess", reason="timed_out")
    assert {it.item_id: it.status for it in queue.items} == {"g01": "unknown", "g02": "aborted"}
    rows = {r["item_id"]: r for r in journal.read()}
    assert "persistence unknown" in rows["g01"]["note"] and "before this item started" in rows["g02"]["note"]


def test_text_mismatch_with_correct_identity_still_retries_once(tmp_path, stripe_env):
    rec = Recorder()
    queue, _journal, report = _csv_writer(tmp_path, rec)
    report("g01", "written", "Lucas Bernard", TEXT.replace("écrite", "ecrite"))
    retry = queue.get("g01-r1")
    assert retry is not None and retry.student == "Lucas Bernard" and retry.text == TEXT
    assert queue.next_pending().item_id == "g01-r1"
    report("g01-r1", "written", "Lucas Bernard", TEXT.replace("écrite", "ecrite"))
    assert queue.get("g01-r1").status == "mismatch" and queue.get("g01-r1-r1") is None
    assert rec.requests == []


def test_text_and_identity_both_wrong_is_not_retried(tmp_path, stripe_env):
    rec = Recorder()
    queue, journal, report = _csv_writer(tmp_path, rec)
    report("g01", "written", "Lucas Petit", "autre texte")
    assert queue.get("g01").status == "mismatch" and queue.get("g01-r1") is None
    assert "identity" in journal.read()[0]["note"]


def test_agent_reported_mismatch_on_wrong_row_is_not_retried(tmp_path, stripe_env):
    rec = Recorder()
    queue, _journal, report = _csv_writer(tmp_path, rec)
    report("g01", "mismatch", "Lucas Petit", "autre texte")
    assert queue.get("g01").status == "mismatch" and queue.get("g01-r1") is None


def test_not_found_is_unchanged_by_the_identity_gate(tmp_path, stripe_env):
    rec = Recorder()
    queue, journal, report = _csv_writer(tmp_path, rec)
    report("g01", "not_found", "", "")
    assert queue.get("g01").status == "not_found"
    row = journal.read()[0]
    assert row["status"] == "not_found" and "identity" not in row["note"]


def test_live_store_wrong_identity_is_persisted_as_mismatch_without_retry(tmp_path, stripe_env):
    rec = Recorder()
    store, _queue, _journal, report = _live_writer(tmp_path, rec)
    report("q1", "written", "Lucas Petit", TEXT)
    stored = store.get("q1")
    assert stored["status"] == "mismatch" and stored["student_seen"] == "Lucas Petit"
    assert [it["item_id"] for it in store.all()] == ["q1"]
    assert store.next_pending() is None
    assert rec.requests == []


def test_live_store_correct_identity_is_verified(tmp_path, stripe_env):
    rec = Recorder()
    store, _queue, journal, report = _live_writer(tmp_path, rec)
    report("q1", "written", "BERNARD Lucas", TEXT)
    assert store.get("q1")["status"] == "verified"
    assert journal.read()[0]["billed"] is True and len(rec.requests) == 1
