import json
from pathlib import Path

import pytest

from agent.journal import SPEC_FIELDS, STATUSES, Event, Journal, base_item, read_journal, undo_entry


def test_statuses_are_the_spec_ones():
    assert set(STATUSES) == {"written", "verified", "mismatch", "abstained", "false_success", "aborted", "not_found",
                             "unknown"}


def test_roundtrip_has_every_spec_field(tmp_path: Path):
    j = Journal(tmp_path / "run" / "journal.jsonl")
    j.append(Event(item_id="t01", student="s06", status="written", before="", after="Texte", session_id="s",
                   step=4, tokens=120, cost_eur=0.001, model="holo4-27b", screenshot="t01.png"))
    j.append({"item_id": "t01", "student": "s06", "status": "verified", "after": "Texte"})
    rows = read_journal(j.path)
    assert [r["status"] for r in rows] == ["written", "verified"]
    for r in rows:
        assert set(SPEC_FIELDS) <= set(r)
        assert isinstance(r["ts"], float)
    assert rows[0]["step"] == 4 and rows[0]["model"] == "holo4-27b" and rows[1]["screenshot"] is None
    assert j.last_for("t01")["status"] == "verified"


def test_one_json_object_per_line_and_append_only(tmp_path: Path):
    j = Journal(tmp_path / "journal.jsonl")
    j.append(Event(item_id="a", student="s01", status="verified", after="Élève sérieux"))
    first = j.path.read_bytes()
    j.append(Event(item_id="b", student="s02", status="abstained"))
    after = j.path.read_bytes()
    assert after.startswith(first)
    lines = after.decode("utf-8").splitlines()
    assert len(lines) == 2 and all(isinstance(json.loads(line), dict) for line in lines)
    assert "Élève" in lines[0]  # UTF-8, not \u escapes


def test_bad_events_are_rejected(tmp_path: Path):
    j = Journal(tmp_path / "journal.jsonl")
    with pytest.raises(ValueError):
        Event(item_id="a", student="s01", status="done")
    with pytest.raises(ValueError):
        j.append({"item_id": "a", "student": "s01", "status": "ok"})
    with pytest.raises(ValueError):
        j.append({"item_id": "a", "student": "s01", "status": "verified", "grade": 20})
    with pytest.raises(ValueError):
        j.append({"student": "s01", "status": "verified"})
    assert j.read() == []


def test_undo_entry_restores_previous_value(tmp_path: Path):
    j = Journal(tmp_path / "journal.jsonl")
    prev = j.append(Event(item_id="t03", student="s03", status="verified", before="Ancien texte",
                          after="Nouveau texte", text_read_back="Nouveau texte", run_id="r", session_id="x"))
    undo = undo_entry(prev)
    assert undo["item_id"] == "t03-undo" and undo["student"] == "s03"
    assert undo["status"] == "written"
    assert undo["before"] == "Nouveau texte" and undo["after"] == "Ancien texte"
    assert undo["run_id"] == "r" and undo["session_id"] == "x"
    j.append(undo)
    assert j.read()[-1]["item_id"] == "t03-undo"


def test_undo_of_a_mismatch_starts_from_what_the_cell_holds():
    prev = {"item_id": "t04", "student": "s04", "status": "mismatch", "before": None,
            "after": "Bon trimestre.", "text_read_back": "Bon trimestr."}
    undo = undo_entry(prev)
    assert undo["before"] == "Bon trimestr." and undo["after"] == ""


@pytest.mark.parametrize("status", ["abstained", "aborted", "not_found"])
def test_nothing_to_undo_when_nothing_was_written(status: str):
    with pytest.raises(ValueError):
        undo_entry({"item_id": "t05", "student": "s05", "status": status})


def test_last_write_skips_events_that_wrote_nothing(tmp_path: Path):
    j = Journal(tmp_path / "journal.jsonl")
    assert j.last_write() is None
    j.append(Event(item_id="a", student="s01", status="verified", after="A"))
    j.append(Event(item_id="b", student="s02", status="abstained"))
    assert j.last_write()["item_id"] == "a"


def test_undo_last_restores_the_value_before_the_first_attempt(tmp_path: Path):
    j = Journal(tmp_path / "journal.jsonl")
    assert j.undo_last() is None
    j.append(Event(item_id="t01", student="s01", status="written", before="Ancien", after="Nouveau"))
    j.append(Event(item_id="t01", student="s01", status="verified", after="Nouveau", text_read_back="Nouveau"))
    undo = j.undo_last()
    assert undo["item_id"] == "t01-undo" and undo["before"] == "Nouveau" and undo["after"] == "Ancien"


def test_undo_last_after_a_corrective_retry(tmp_path: Path):
    j = Journal(tmp_path / "journal.jsonl")
    j.append(Event(item_id="g01", student="s01", status="mismatch", before=None, after="Bon.", text_read_back="Bn."))
    j.append(Event(item_id="g01-r1", student="s01", status="verified", before="Bn.", after="Bon.",
                   text_read_back="Bon."))
    undo = j.undo_last()
    assert undo["before"] == "Bon." and undo["after"] == ""
    assert base_item("g01-r1") == "g01" and base_item("t03-undo") == "t03-undo"
