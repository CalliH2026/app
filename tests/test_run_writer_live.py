from pathlib import Path

from agent import run_writer
from agent.queue import Queue
from agent.queue_store import QueueStore


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_live_next_item_waits_then_returns_null_after_idle_timeout(tmp_path: Path):
    store = QueueStore(tmp_path / "queue.jsonl")
    clock = Clock()
    queue = Queue.from_store(store.path)
    started: dict[str, float] = {}
    next_item = run_writer.make_next_item(queue, started, live=True, idle_timeout=300, clock=clock)
    assert "wait" in next_item.__doc__

    reply = next_item()
    assert reply == {"wait": True, "seconds": 8,
                     "message": "no approved item yet, call wait_web for 8 seconds then next_item again"}
    clock.t += 200
    assert next_item()["wait"] is True

    # the teacher approves an item: it is handed out and the idle clock restarts
    store.append({"item_id": "q1", "student": "Barbara Gardner", "text": "Participe bien."})
    item = next_item()
    assert item["item_id"] == "q1" and "q1" in started
    assert store.get("q1")["status"] == "in_progress"
    clock.t += 299
    assert next_item()["wait"] is True
    clock.t += 299
    assert next_item()["wait"] is True
    clock.t += 1
    assert next_item() is None


def test_live_next_item_returns_null_at_once_on_stop_and_drains(tmp_path: Path):
    store = QueueStore(tmp_path / "queue.jsonl")
    store.append({"item_id": "q1", "student": "A", "text": "one"})
    queue = Queue.from_store(store.path)
    next_item = run_writer.make_next_item(queue, {}, live=True, idle_timeout=300, clock=Clock())
    (tmp_path / "STOP").write_text("")
    assert next_item() is None
    assert store.get("q1")["status"] == "aborted"


def test_csv_next_item_unchanged_returns_null_when_empty(tmp_path: Path):
    csv = tmp_path / "items.csv"
    csv.write_text("item_id,student,text\na,Léa,Texte A\n", encoding="utf-8")
    queue = Queue.from_csv(csv, stop_file=tmp_path / "STOP")
    next_item = run_writer.make_next_item(queue, {}, live=False)
    assert next_item()["item_id"] == "a"
    assert next_item() is None
    assert "wait" not in next_item.__doc__


def test_cli_accepts_queue_in_dry_run(tmp_path: Path, capsys):
    store = QueueStore(tmp_path / "queue.jsonl")
    store.append({"item_id": "q1", "student": "Barbara Gardner", "text": "Participe bien."})
    assert run_writer.main(["--queue", str(store.path), "--dry-run", "--run-dir", str(tmp_path / "run")]) == 0
    out = capsys.readouterr().out
    assert "live queue=1" in out and "q1" in out
