import csv
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pronote" / "make_import_files.py"
spec = importlib.util.spec_from_file_location("make_import_files", SCRIPT)
mif = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mif)


def test_fallback_roster_has_ten_students_and_demo_constraints():
    names = [r["display_name"] for r in mif.FALLBACK_ROSTER]
    assert len(names) == 10 == len(set(names))
    first_names = [n.split()[0] for n in names]
    assert first_names.count("Léa") == 2
    assert any(r["aliases"] == "Max" for r in mif.FALLBACK_ROSTER)


def test_split_name():
    assert mif.split_name("Léa Martin") == ("MARTIN", "Léa")
    assert mif.split_name("Anne Le Gall") == ("LE GALL", "Anne")
    with pytest.raises(ValueError):
        mif.split_name("Cher")


def test_build_uses_roster_file_and_writes_tab_and_csv(tmp_path):
    roster = tmp_path / "roster.csv"
    roster.write_text("student_id,display_name,aliases\nX1,Paul Durand,\nX2,Léa Petit,Lili\n", encoding="utf-8")
    written = mif.build(roster, tmp_path / "out")
    assert sorted(p.name for p in written) == ["eleves.csv", "eleves.txt", "professeurs.csv", "professeurs.txt"]
    lines = (tmp_path / "out" / "eleves.txt").read_text(encoding="utf-8-sig").splitlines()
    assert lines == ["Nom\tPrénom\tClasse", "DURAND\tPaul\t3A", "PETIT\tLéa\t3A"]
    with (tmp_path / "out" / "professeurs.csv").open(encoding="utf-8-sig", newline="") as f:
        assert list(csv.reader(f, delimiter=";")) == [mif.TEACHER_HEADER, ["DURAND", "Sophie", "FRANCAIS"]]


def test_build_falls_back_when_roster_missing(tmp_path):
    mif.build(tmp_path / "missing.csv", tmp_path)
    assert len((tmp_path / "eleves.txt").read_text(encoding="utf-8-sig").splitlines()) == 11


def test_files_start_with_utf8_bom(tmp_path):
    # PRONOTE 2026.2.8 reads a UTF-8 file without BOM as ANSI ("GaÃ«l"); with a BOM it imports correctly.
    for path in mif.build(tmp_path / "missing.csv", tmp_path):
        data = path.read_bytes()
        assert data.startswith(b"\xef\xbb\xbf"), path.name
        assert not data[3:].startswith(b"\xef\xbb\xbf"), path.name


def test_committed_import_files_match_generator(tmp_path):
    mif.build(mif.DEFAULT_ROSTER, tmp_path)
    for name in ["eleves.txt", "eleves.csv", "professeurs.txt", "professeurs.csv"]:
        assert (tmp_path / name).read_bytes() == (mif.DEFAULT_OUT / name).read_bytes(), name
