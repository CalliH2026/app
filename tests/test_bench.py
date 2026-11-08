"""Timing harness: measured and estimated times stay apart, and nothing is computed from one arm alone."""

import json
import sys
from pathlib import Path

import pytest

from scripts import bench

ROOT = Path(__file__).resolve().parents[1]


def _rec(**kw):
    base = {"scenario": "school-outing", "arm": "agent", "basis": "measured", "condition": "cold",
            "started_at": "2026-11-07T18:00:00+01:00", "elapsed_s": 10.0, "ok": True, "source": "runs/x"}
    return {**base, **kw}


def _estimate(**kw):
    return _rec(**{"arm": "human", "basis": "estimate", "condition": "n/a", "source": None, "started_at": None,
                   "assumption": "typing 40 wpm, 3 tabs, no read-back", **kw})


def test_historical_writer_run_converts_with_its_measured_numbers():
    r = bench.from_run(ROOT / "runs/20261107-152520", "pronote-writer-approved-text")
    assert (r["elapsed_s"], r["ok"], r["labels"]["verified"], r["labels"]["items"]) == (300.8, True, 10, 10)
    assert r["basis"] == "measured" and r["cost_note"] and len(r["tools"]) == 10


def test_preparation_job_ready_and_failed():
    job = {"id": "prep-1", "status": "ready", "elapsed_s": 16.3, "created_at": "2026-11-07T18:00:00+0100",
           "updated_at": "2026-11-07T18:00:17+0100", "provider_session_id": "sess-1",
           "provider_runtime": "local", "answer_contract": "json_text_validated",
           "trigger": {"document_id": "copie"}, "preparation_version": "parallel-v3",
           "events": [{"at": "2026-11-07T18:00:05+0100", "kind": "model_tool", "text": "read_case"},
                      {"at": "2026-11-07T18:00:01+0100", "kind": "check", "text": "frozen"}]}
    r = bench.from_preparation(job, "prep-1.json", "warm")
    assert r["ok"] and r["condition"] == "warm" and r["labels"]["trigger"] == "observed"
    assert r["tools"] == [{"name": "read_case", "kind": "model_tool", "offset_s": 5.0}]
    assert "sess-1" in r["source"]
    failed = {**job, "status": "failed", "trigger": None,
              "diagnostic": {"stage": "start", "error_type": "ModuleNotFoundError", "message": "secret-ish"}}
    r = bench.from_preparation(failed, "prep-1.json")
    assert not r["ok"] and r["failure"] == "start:ModuleNotFoundError" and r["labels"]["trigger"] == "manual"
    assert "secret-ish" not in json.dumps(r)


def test_unfinished_preparation_is_rejected():
    with pytest.raises(ValueError, match="not finished"):
        bench.from_preparation({"id": "p", "status": "running", "elapsed_s": None}, "p.json")


@pytest.mark.parametrize("bad, msg", [
    (_rec(arm="agent", basis="estimate", assumption="x"), "never estimated"),
    (_estimate(assumption=""), "assumption"),
    (_rec(source=""), "evidence"),
    (_rec(started_at=None), "started_at"),
    (_rec(elapsed_s=-1), "non-negative"),
    (_rec(elapsed_s=True), "non-negative"),
    (_rec(cost_usd=0.1), "cost_note"),
    (_rec(condition="hot"), "condition"),
    (_rec(retries=-1), "retries"),
])
def test_check_rejects_ambiguous_records(bad, msg):
    with pytest.raises(ValueError, match=msg):
        bench.check(bad)


def test_summary_reports_n_failures_retries_median_and_range_from_successes_only():
    rs = [_rec(elapsed_s=10.0), _rec(elapsed_s=30.0, retries=1), _rec(elapsed_s=99.0, ok=False, failure="exit 1"),
          _rec(elapsed_s=20.0)]
    (g,) = bench.summarize(rs)["groups"]
    assert (g["n"], g["ok"], g["failed"], g["retries"]) == (4, 3, 1, 1)
    assert g["elapsed_s"] == {"median": 20.0, "min": 10.0, "max": 30.0}
    assert g["failures"] == ["exit 1"]


def test_estimates_are_a_separate_group_and_label_the_comparison():
    s = bench.summarize([_rec(), _rec(condition="warm", elapsed_s=4.0), _estimate(elapsed_s=600.0, active_s=540.0)])
    assert {(g["arm"], g["basis"], g["condition"]) for g in s["groups"]} == {
        ("agent", "measured", "cold"), ("agent", "measured", "warm"), ("human", "estimate", "n/a")}
    assert {c["human_basis"] for c in s["comparisons"]} == {"estimated human"}
    assert all("percent" not in k and "saving" not in k for c in s["comparisons"] for k in c)
    assert "estimated human" in bench.render_markdown(s)


def test_no_comparison_from_an_agent_timing_alone():
    (c,) = bench.summarize([_rec(), _rec(elapsed_s=12.0)])["comparisons"]
    assert c["computable"] is False


def test_record_command_measures_once_and_checks_artifacts(tmp_path):
    out, calls = tmp_path / "result.json", tmp_path / "calls.txt"
    script = f"open({str(calls)!r}, 'a').write('x'); open({str(out)!r}, 'w').write('{{}}')"
    r = bench.record_command([sys.executable, "-c", script], "school-outing", "cold", [str(out)])
    assert r["ok"] and r["retries"] == 0 and r["elapsed_s"] >= 0 and calls.read_text() == "x"
    r = bench.record_command([sys.executable, "-c", "pass"], "school-outing", "cold", [str(tmp_path / "nope")])
    assert not r["ok"] and r["failure"].startswith("missing artifact")
    r = bench.record_command([sys.executable, "-c", "raise SystemExit(3)"], "school-outing", "warm", [])
    assert not r["ok"] and r["failure"] == "exit 3"


def test_cli_summarize_rejects_an_invalid_line(tmp_path, capsys):
    f = tmp_path / "b.jsonl"
    f.write_text(json.dumps(_rec()) + "\n" + json.dumps(_rec(arm="agent", basis="estimate")) + "\n")
    with pytest.raises(SystemExit, match=r"b\.jsonl:2"):
        bench.main(["summarize", str(f)])
    f.write_text(json.dumps(_rec()) + "\n")
    assert bench.main(["summarize", str(f), "--markdown"]) == 0
    assert "| school-outing | agent | measured | cold | 1 | 1 |" in capsys.readouterr().out
