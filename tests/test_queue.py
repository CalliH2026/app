from pathlib import Path

from agent.journal import Event, Journal, undo_entry
from agent.queue import Queue, normalize, same_text, similarity


def test_normalize_tolerates_typography_only():
    assert same_text("Participe bien, doit soigner la rédaction.", "Participe bien, doit soigner la rédaction")
    assert same_text("L’oral est bon.", "L'oral est bon.")
    assert same_text("Deux  espaces", "Deux espaces")
    assert not same_text("Léa participe", "Lea participe")
    assert not same_text("Travail sérieux.", "Travail serieux.")


def test_similarity_is_one_for_identical_after_normalization():
    assert similarity("A b.", "A  b") == 1.0
    assert similarity("abc", "xyz") < 0.5


def test_queue_hands_out_items_once_and_stops_on_stop_file(tmp_path: Path):
    csv = tmp_path / "items.csv"
    csv.write_text("item_id,student,text,previous_value,set\n"
                   "a,Léa,Texte A,,demo\n"
                   "b,Noé,Texte B,,demo\n"
                   "c,Zoé,Texte C,,measured\n", encoding="utf-8")
    q = Queue.from_csv(csv, stop_file=tmp_path / "STOP", only_set="demo")
    assert [i.item_id for i in q.items] == ["a", "b"]
    first = q.next_pending()
    assert first is not None and first.item_id == "a" and first.status == "in_progress"
    (tmp_path / "STOP").write_text("")
    assert q.next_pending() is None
    assert q.pending_count() == 1


def test_journal_roundtrip_and_undo(tmp_path: Path):
    j = Journal(tmp_path / "journal.jsonl")
    j.append(Event(arm="calligraphe", target="moodle", run_id="r1", item_id="a", student="Léa",
                   before="", after="Texte A", text_read_back="Texte A", status="verified"))
    rows = j.read()
    assert rows[0]["status"] == "verified" and rows[0]["item_id"] == "a"
    undo = undo_entry(rows[0])
    assert undo["item_id"] == "a-undo" and undo["after"] == "" and undo["before"] == "Texte A"
    assert normalize(undo["after"]) == ""
