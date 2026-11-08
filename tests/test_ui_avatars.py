"""The approval screen shows an illustrated, committed avatar for every fictitious student (no network at runtime)."""

from pathlib import Path

import pytest

from voice.roster import load_roster

ROOT = Path(__file__).resolve().parent.parent
AVATARS = ROOT / "ui" / "static" / "avatars"


@pytest.mark.parametrize("roster", ["roster.csv", "roster_moodle.csv"])
def test_every_roster_entry_has_a_committed_illustrated_avatar(roster):
    for sid in [s.student_id for s in load_roster(ROOT / "data" / roster)]:
        svg = AVATARS / f"{sid}.svg"
        assert svg.is_file(), f"missing avatar for {sid}: run python scripts/make_avatars.py"
        head = svg.read_text(encoding="utf-8")[:2000]
        assert head.startswith("<svg") and "<image" not in svg.read_text(encoding="utf-8"), sid  # vector, no photo
        assert "creativecommons.org/licenses/by/4.0" in head and svg.stat().st_size < 20_000


def test_workspace_portrait_atlas_is_the_committed_ai_generated_file():
    import hashlib

    atlas = AVATARS / "calli-portraits-fictifs-ia-s01-s10.png"
    assert hashlib.sha256(atlas.read_bytes()).hexdigest() == (
        "da4b1a4b8fe2ed3675aaaa5ae72517fe3508442de7251228a68530dc49fd8a2d")
    js = (AVATARS.parent / "workspace.js").read_text(encoding="utf-8")
    assert '["s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "s09", "s10"]' in js
    assert "Portraits fictifs générés par IA." in (AVATARS.parent / "workspace.html").read_text(encoding="utf-8")
