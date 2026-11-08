import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_RUNS = ROOT / "tests" / "fixtures" / "runs"
_spec = importlib.util.spec_from_file_location("report", ROOT / "scripts" / "report.py")
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)

README = """# Title

Intro.

<!-- scoreboard:start -->
placeholder
<!-- scoreboard:end -->

Footer.
"""


def test_fixture_run_metrics():
    rows = {r["run"]: r for r in report.load_runs(FIXTURE_RUNS)}
    assert list(rows) == ["20261107-100000-fixture", "20261107-110000-fixture-human"]
    r = rows["20261107-100000-fixture"]
    assert (r["arm"], r["model"]) == ("calligraphe", "holo4-27b")
    assert r["attempted"] == 6  # f02-r1 belongs to f02
    assert (r["verified"], r["abstained"], r["mismatch"], r["false_success"], r["aborted"]) == (2, 1, 1, 1, 1)
    assert r["not_found"] == 0
    assert r["seconds_median"] == pytest.approx(52.5)  # 10, 40, 45, 60, 80, 120
    assert r["seconds_worst"] == pytest.approx(120.0)
    assert r["steps"] == 34
    assert r["tokens_per_verified"] == pytest.approx(3750)
    assert r["cost_per_verified"] == pytest.approx(0.0375)

    h = rows["20261107-110000-fixture-human"]
    assert (h["arm"], h["model"], h["steps"], h["tokens_per_verified"], h["cost_per_verified"]) == (
        "human", None, None, None, None)
    assert (h["seconds_median"], h["seconds_worst"]) == (80.0, 90.0)


def test_not_found_is_counted():
    events = [{"item_id": "t01", "student": "Lucas", "status": "not_found", "seconds": 20.0}]
    r = report.run_row("r", events)
    assert (r["attempted"], r["not_found"], r["verified"]) == (1, 1, 0)


def test_summary_json_fills_totals_the_journal_lacks():
    events = [{"item_id": "g01", "student": "x", "status": "verified", "seconds": 12.0}]
    r = report.run_row("r", events, {"arm": "baseline", "steps": 7, "tokens": 900, "model": "holo4-35b-a3b"})
    assert (r["arm"], r["steps"], r["tokens_per_verified"], r["model"]) == ("baseline", 7, 900, "holo4-35b-a3b")
    assert r["cost_per_verified"] is None


def test_render_into_readme_keeps_everything_outside_the_markers(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text(README, encoding="utf-8")
    assert report.main(["--runs", str(FIXTURE_RUNS), "--readme", str(readme)]) == 0
    text = readme.read_text(encoding="utf-8")
    assert text.startswith("# Title\n\nIntro.\n\n<!-- scoreboard:start -->\n| Run | Arm |")
    assert text.endswith("<!-- scoreboard:end -->\n\nFooter.\n")
    assert "placeholder" not in text
    assert "| 20261107-100000-fixture | calligraphe | holo4-27b | 6 | 2 | 1 | 1 | 1 | 1 | 0 | 52.5 | 120.0 | 34 | 3750 | 0.0375 |" in text
    assert "| 20261107-110000-fixture-human | human | — | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 80.0 | 90.0 | — | — | — |" in text
    assert "tests/fixtures/runs/*/journal.jsonl" in text
    # idempotent, and --check agrees
    assert report.main(["--runs", str(FIXTURE_RUNS), "--readme", str(readme)]) == 0
    assert readme.read_text(encoding="utf-8") == text
    assert report.main(["--runs", str(FIXTURE_RUNS), "--readme", str(readme), "--check"]) == 0


def test_check_fails_on_stale_readme(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text(README, encoding="utf-8")
    assert report.main(["--runs", str(FIXTURE_RUNS), "--readme", str(readme), "--check"]) == 1
    assert readme.read_text(encoding="utf-8") == README


def test_no_runs_renders_the_empty_message(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text(README, encoding="utf-8")
    report.main(["--runs", str(tmp_path / "none"), "--readme", str(readme)])
    assert report.EMPTY in readme.read_text(encoding="utf-8")


def test_missing_markers_is_an_error():
    with pytest.raises(ValueError):
        report.replace_scoreboard("# no markers\n", "table")


def test_committed_readme_is_rendered_from_runs():
    assert report.main(["--check"]) == 0
