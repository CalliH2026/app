"""The Calli time-estimate insert model matches its corpus and its own formulas (offline)."""

import csv
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSERT = ROOT / "video" / "inserts" / "calli-time-estimate"
MODEL = json.loads((INSERT / "model.json").read_text(encoding="utf-8"))


def test_corpus_counts_match_the_csv():
    c = MODEL["corpus"]
    path = ROOT / c["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == c["sha256"]
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == c["items"]
    assert sum(len(r["text"]) for r in rows) == c["comment_characters_including_spaces"]
    words = sum(len(f"{r['student']} {r['text']}".split()) for r in rows)
    assert words == c["spoken_words_including_student_names_whitespace_count"]
    p03 = next(r for r in rows if r["item_id"] == "p03")
    assert ("agent :" in p03["text"]) == c["p03_contains_literal_injection_test_fixture"]


def test_scenarios_follow_the_formulas():
    c, a = MODEL["corpus"], MODEL["assumptions"]
    n = c["items"]
    calli = (
        60 * c["spoken_words_including_student_names_whitespace_count"] / a["spoken_words_per_minute"]
        + n * (a["dictation_turn_overhead_seconds_per_item"] + a["human_final_review_seconds_per_item_both_modes"])
        + a["additional_calli_intervention_seconds"]
    )
    cpms = [s["typing_characters_per_minute"] for s in MODEL["scenarios"]]
    assert cpms == a["typing_characters_per_minute_scenarios"]
    for s in MODEL["scenarios"]:
        manual = 60 * c["comment_characters_including_spaces"] / s["typing_characters_per_minute"] + n * (
            a["manual_navigation_and_save_seconds_per_item"] + a["human_final_review_seconds_per_item_both_modes"]
        )
        assert round(manual, 3) == s["manual_human_active_s_estimated"]
        assert round(calli, 3) == s["calli_human_active_s_estimated"]
        assert (
            round(manual - calli, 3)
            == s["human_active_s_saved_estimated"]
            == s["break_even_extra_calli_intervention_s"]
        )
        assert round(100 * (manual - calli) / manual, 3) == s["human_active_percent_saved_estimated"]


def test_on_screen_rounding_to_nearest_ten_percent():
    pcts = [s["human_active_percent_saved_estimated"] for s in MODEL["scenarios"]]
    central = next(s for s in MODEL["scenarios"] if s["typing_characters_per_minute"] == 225)
    assert round(central["human_active_percent_saved_estimated"] / 10) * 10 == 50
    assert (round(min(pcts) / 10) * 10, round(max(pcts) / 10) * 10) == (40, 60)


def test_insert_plots_only_estimates():
    src = (ROOT / "video" / "explainer" / "src" / "inserts" / "CalliTimeEstimate.tsx").read_text(encoding="utf-8")
    assert MODEL["classification"] == "scenario_estimate_not_human_benchmark"
    assert "separate_measured_reference" not in src and "writer_elapsed" not in src
    for label in (
        "Saisie manuelle · estimée",
        "Avec Calli · estimé",
        "pas une mesure",
        "aucun test utilisateur réalisé",
        "de temps actif en moins",
        "estimation",
        "pas un intervalle de confiance",
    ):
        assert label in src


def test_error_sensitivity_scenarios_recompute():
    model = json.loads((INSERT / "calli-erreurs-sensibilite.json").read_text(encoding="utf-8"))
    h0, c0, n = model["base_manual_active_seconds"], model["base_calli_active_seconds"], model["items"]
    assert model["break_even_net_extra_calli_seconds"] == pytest.approx(h0 - c0)
    got = []
    for s in model["scenarios"]:
        extra_h = n * s["assumed_p_manual_repair_per_comment"] * s["assumed_manual_repair_seconds"]
        extra_c = n * (
            s["assumed_p_asr_repair_per_comment"] * s["assumed_asr_repair_seconds"]
            + s["assumed_p_gui_incident_per_comment"] * s["assumed_gui_human_repair_seconds"]
        )
        assert extra_h == pytest.approx(s["manual_extra_seconds_expected"])
        assert extra_c == pytest.approx(s["calli_extra_seconds_expected"])
        got.append(round(100 * (1 - (c0 + extra_c) / (h0 + extra_h)), 3))
        assert got[-1] == pytest.approx(s["saved_percent_ratio_of_expected_times"], abs=1e-3)
    assert got == [48.521, 47.002, 37.613, 0.056]
