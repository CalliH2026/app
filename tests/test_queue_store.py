import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent.queue import Queue
from agent.queue_store import QueueStore

ROOT = Path(__file__).resolve().parents[1]

APPEND = """
import sys
from agent.queue_store import QueueStore
s = QueueStore(sys.argv[1])
for i in range(int(sys.argv[3])):
    s.append({"item_id": f"{sys.argv[2]}-{i}", "student": "Léa Girard", "text": f"Texte {sys.argv[2]} {i}"})
"""

CLAIM = """
import json, sys
from agent.queue_store import QueueStore
s = QueueStore(sys.argv[1])
got = []
while (it := s.next_pending()) is not None:
    got.append(it["item_id"])
print(json.dumps(got))
"""


def _spawn(code: str, *args: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", code, *args], cwd=ROOT, stdout=subprocess.PIPE, text=True)


def test_append_next_update_summary(tmp_path: Path):
    s = QueueStore(tmp_path / "queue.jsonl")
    a = s.append({"student": "Barbara Gardner", "text": "Participe bien.", "course": "Mindful Course Creation"})
    b = s.append({"student": "Brian Franklin", "text": "Trimestre sérieux."})
    assert a["status"] == "pending" and a["source"] == "ui" and a["created_at"] <= a["updated_at"]
    assert set(a) >= {"item_id", "student", "course", "text", "previous_value", "status", "created_at",
                      "updated_at", "source"}
    first = s.next_pending()
    assert first["item_id"] == a["item_id"] and first["status"] == "in_progress"
    s.update(a["item_id"], status="verified", text_read_back="Participe bien", similarity=1.0)
    assert s.get(a["item_id"])["status"] == "verified"
    assert s.next_pending()["item_id"] == b["item_id"]
    assert s.next_pending() is None
    assert s.summary() == {"verified": 1, "in_progress": 1}
    lines = (tmp_path / "queue.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["item_id"] for x in lines] == [a["item_id"], b["item_id"]]
    assert not (tmp_path / "queue.jsonl.lock").exists()


def test_rejects_bad_items_and_statuses(tmp_path: Path):
    s = QueueStore(tmp_path / "queue.jsonl")
    with pytest.raises(ValueError):
        s.append({"student": "", "text": "x"})
    with pytest.raises(ValueError):
        s.append({"student": "A", "text": "x", "colour": "red"})
    it = s.append({"student": "A", "text": "x"})
    with pytest.raises(ValueError):
        s.update(it["item_id"], status="done")
    with pytest.raises(KeyError):
        s.update("nope", status="verified")


def test_double_approve_is_deduplicated_while_open(tmp_path: Path):
    s = QueueStore(tmp_path / "queue.jsonl")
    a = s.append({"student": "Léa Girard", "text": "Très bon trimestre."})
    again = s.append({"student": "léa girard", "text": "Très  bon trimestre"})
    assert again["item_id"] == a["item_id"] and again["duplicate"] is True
    s.update(a["item_id"], status="verified")
    assert s.append({"student": "Léa Girard", "text": "Très bon trimestre."})["item_id"] != a["item_id"]


def test_stop_drains_pending_and_blocks_next(tmp_path: Path):
    s = QueueStore(tmp_path / "queue.jsonl")
    a = s.append({"student": "A", "text": "one"})
    b = s.append({"student": "B", "text": "two"})
    s.next_pending()
    drained = s.stop()
    assert (tmp_path / "STOP").exists()
    assert [d["item_id"] for d in drained] == [b["item_id"]]
    assert s.get(a["item_id"])["status"] == "in_progress"  # STOP reverts nothing, the write in flight finishes
    assert s.get(b["item_id"])["status"] == "aborted" and s.get(b["item_id"]).get("not_started") is True
    assert "not_started" not in s.get(a["item_id"])
    s.append({"student": "C", "text": "three"})
    assert s.next_pending() is None
    s.resume()
    assert s.next_pending()["student"] == "C"


def test_stale_lock_is_broken(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import agent.queue_store as qs

    s = QueueStore(tmp_path / "queue.jsonl")
    s.lock_path.parent.mkdir(parents=True, exist_ok=True)
    s.lock_path.write_text("12345")
    monkeypatch.setattr(qs, "LOCK_STALE_S", -1.0)
    s.append({"student": "A", "text": "x"})
    assert len(s.all()) == 1


def test_two_processes_append_then_claim_each_item_once(tmp_path: Path):
    path = str(tmp_path / "queue.jsonl")
    writers = [_spawn(APPEND, path, "ui", "25"), _spawn(APPEND, path, "voice", "25")]
    for w in writers:
        assert w.wait(timeout=60) == 0
    store = QueueStore(path)
    assert len(store.all()) == 50
    readers = [_spawn(CLAIM, path), _spawn(CLAIM, path)]
    claimed = [json.loads(r.communicate(timeout=60)[0]) for r in readers]
    a, b = set(claimed[0]), set(claimed[1])
    assert not a & b
    assert a | b == {it["item_id"] for it in store.all()}
    assert store.summary() == {"in_progress": 50}


def test_queue_wraps_the_store_with_retry_after_original(tmp_path: Path):
    s = QueueStore(tmp_path / "queue.jsonl")
    s.append({"item_id": "a", "student": "Barbara Gardner", "text": "Participe bien."})
    s.append({"item_id": "b", "student": "Brian Franklin", "text": "Trimestre sérieux."})
    q = Queue.from_store(tmp_path / "queue.jsonl")
    assert q.stop_file == tmp_path / "STOP"
    it = q.next_pending()
    assert it.item_id == "a"
    it.status, it.text_read_back = "mismatch", "Participe bien, rédactation"
    q.save(it, similarity=0.9)
    retry = q.add_retry(it, it.text_read_back)
    assert retry.item_id == "a-r1" and retry.previous_value == "Participe bien, rédactation"
    assert [r["item_id"] for r in s.all()] == ["a", "a-r1", "b"]
    assert s.get("a-r1")["retry_of"] == "a" and s.get("a")["similarity"] == 0.9
    assert q.next_pending().item_id == "a-r1"
    assert q.add_retry(it, "x") is None
    # the approval screen appends while the loop runs: the live queue sees it
    s.append({"item_id": "c", "student": "Stephanie Adams", "text": "Des progrès."})
    assert q.next_pending().item_id == "b"
    assert q.next_pending().item_id == "c"
    assert q.next_pending() is None


def test_recover_marks_items_left_in_progress_unknown(tmp_path: Path):
    s = QueueStore(tmp_path / "queue.jsonl")
    s.append({"item_id": "a", "student": "Léa Girard", "text": "Bon trimestre."})
    s.append({"item_id": "b", "student": "Léa Girard", "text": "Autre texte."})
    s.next_pending()  # the writer dies here
    [rec] = s.recover()
    assert rec["item_id"] == "a" and s.get("a")["status"] == "unknown" and "restarted" in s.get("a")["note"]
    assert s.get("b")["status"] == "pending"
    # the teacher can approve the same text again
    assert not s.append({"student": "Léa Girard", "text": "Bon trimestre."}).get("duplicate")


def test_same_comment_in_two_courses_is_two_items(tmp_path: Path):
    s = QueueStore(tmp_path / "queue.jsonl")
    a = s.append({"student": "Léa Girard", "text": "Bon trimestre.", "course": "Maths"})
    b = s.append({"student": "Léa Girard", "text": "Bon trimestre.", "course": "Histoire"})
    assert not b.get("duplicate") and a["item_id"] != b["item_id"] and len(s.all()) == 2


def test_no_corrective_write_is_queued_after_stop(tmp_path: Path):
    q = Queue.from_store(tmp_path / "queue.jsonl")
    q.store.append({"item_id": "a", "student": "Léa Girard", "text": "Bon trimestre."})
    it = q.next_pending()
    q.store.stop()  # STOP while "a" is being written; its read-back then mismatches
    assert q.add_retry(it, "Bon trimestr.") is None
    assert [r["item_id"] for r in q.store.all()] == ["a"]


def test_session_end_marks_only_unstarted_items_as_proven_not_started(tmp_path: Path):
    from agent import run_writer
    from agent.journal import Journal
    from agent.queue import Queue

    s = QueueStore(tmp_path / "queue.jsonl")
    a = s.append({"student": "A", "text": "one"})
    b = s.append({"student": "B", "text": "two"})
    queue = Queue.from_store(tmp_path / "queue.jsonl")
    queue.next_pending()  # A handed out, never reported
    run_writer.settle_unfinished(queue.items, queue, Journal(tmp_path / "journal.jsonl"), run_id="r",
                                 arm="calligraphe", target="pronote", session_id="s", reason="timed_out")
    assert s.get(a["item_id"])["status"] == "unknown" and "not_started" not in s.get(a["item_id"])
    assert s.get(b["item_id"])["status"] == "aborted" and s.get(b["item_id"])["not_started"] is True
