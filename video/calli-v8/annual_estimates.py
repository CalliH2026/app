"""Explicit workload scenarios, not a measured human benchmark or confidence interval."""

import json
import random
from pathlib import Path

SEED, SAMPLES = 20261108, 100_000


def scenario(
    typing_cpm=225,
    speaking_wpm=100,
    navigation_s=4,
    turn_s=3,
    meeting_manual=15,
    meeting_assisted=6,
    outing_manual=60,
    outing_assisted=25,
    family_manual=8,
    family_assisted=3,
    intervention_rate=0,
    intervention_s=30,
    typo_rate=0,
    typo_s=15,
):
    # Identical review time in both entry paths; already-composed comments only.
    manual_comment_s = 60 * 129.1 / typing_cpm + navigation_s + 8 + typo_rate * typo_s
    assisted_comment_s = 60 * 21.5 / speaking_wpm + turn_s + 8 + intervention_rate * intervention_s
    entry_hours = (manual_comment_s - assisted_comment_s) * 450 / 3600
    meeting_hours = 20 * (meeting_manual - meeting_assisted) / 60
    outing_hours = 2 * (outing_manual - outing_assisted) / 60
    teacher = entry_hours + meeting_hours + outing_hours - 0.5
    parent = 36 * (family_manual - family_assisted) / 60 + 4 * (4 - 1.5) / 60 - 5 / 60
    return {
        "entry_reduction_pct": 100 * (manual_comment_s - assisted_comment_s) / manual_comment_s,
        "teacher_hours": teacher,
        "class_hours": teacher * 2,
        "school_hours": teacher * 40,
        "parent_household_hours": parent,
        "teacher_comment_hours": entry_hours,
        "teacher_meeting_hours": meeting_hours,
        "teacher_outing_hours": outing_hours,
        "teacher_setup_hours": 0.5,
        "manual_comment_s": manual_comment_s,
        "assisted_comment_s": assisted_comment_s,
    }


def main():
    rng = random.Random(SEED)
    values = []
    for _ in range(SAMPLES):
        # Draw a scenario once per actor/year. Do not shrink uncertainty by drawing
        # a new speed for each pupil. School/class projections scale the same draw.
        tri = lambda low, mode, high: rng.triangular(low, high, mode)
        values.append(
            scenario(
                typing_cpm=tri(150, 225, 300),
                speaking_wpm=tri(85, 100, 130),
                navigation_s=tri(2, 4, 7),
                turn_s=tri(2, 3, 5),
                meeting_manual=tri(10, 15, 20),
                meeting_assisted=tri(4, 6, 10),
                outing_manual=tri(40, 60, 90),
                outing_assisted=tri(15, 25, 40),
                family_manual=tri(5, 8, 12),
                family_assisted=tri(2, 3, 5),
                intervention_rate=tri(0.01, 0.05, 0.15),
                intervention_s=tri(15, 30, 90),
            )
        )
    intervals = {}
    for key in ("entry_reduction_pct", "teacher_hours", "class_hours", "school_hours", "parent_household_hours"):
        xs = sorted(v[key] for v in values)
        intervals[key] = {f"p{p}": xs[round((SAMPLES - 1) * p / 100)] for p in (10, 50, 90)}
    result = {
        "kind": "hypothetical workload and input sensitivity; not measured savings",
        "seed": SEED,
        "samples": SAMPLES,
        "central": scenario(),
        "central_with_assisted_interventions": scenario(intervention_rate=0.05),
        "central_with_hypothetical_errors_both_sides": scenario(intervention_rate=0.05, typo_rate=0.03),
        "model_percentiles_not_confidence_intervals": intervals,
        "annual_workload": {
            "teacher": {"pupils": 150, "terms": 3, "comments": 450, "meetings": 20, "outings": 2, "setup_minutes": 30},
            "school": {"teachers": 40, "classes": 20, "pupils_per_class": 30, "subject_reports_per_pupil_per_term": 10},
            "parent_household": {"children": 2, "weeks": 36, "trip_payments": 4, "setup_minutes": 5},
        },
        "assumptions": {
            "comment_characters": 129.1,
            "dictated_words_including_name": 21.5,
            "typing_cpm": [150, 225, 300],
            "dictation_wpm": [85, 100, 130],
            "review_seconds_both_paths": 8,
            "manual_navigation_seconds": [2, 4, 7],
            "dictation_turn_seconds": [2, 3, 5],
            "meeting_manual_minutes": [10, 15, 20],
            "meeting_assisted_minutes": [4, 6, 10],
            "outing_manual_minutes": [40, 60, 90],
            "outing_assisted_minutes": [15, 25, 40],
            "weekly_family_manual_minutes": [5, 8, 12],
            "weekly_family_assisted_minutes": [2, 3, 5],
            "checkout_manual_minutes": 4,
            "checkout_assisted_minutes": 1.5,
            "assisted_intervention_probability": [0.01, 0.05, 0.15],
            "assisted_intervention_seconds": [15, 30, 90],
        },
        "limits": [
            "All rates, frequencies and time ranges are authored assumptions except the recorded text length.",
            "P10/P50/P90 describe the chosen triangular input distributions, not a population study.",
            "No measured human reference, educational effectiveness, error reduction or monetary ROI is established.",
            "Teacher/class/school figures overlap and must not be added. Parent figures use household as the unit.",
            "All eligible occurrences are assumed to use Calli; onboarding is fixed and maintenance is not estimated.",
            "Active time only. Autonomous agent latency is separate; the user must be able to continue working.",
            "Comment scope is entry of already-written text; no gain attributed to grading or writing the assessment.",
        ],
    }
    Path(__file__).with_name("annual-estimates.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"central": result["central"], "sensitivity": intervals}, indent=2))


if __name__ == "__main__":
    main()
