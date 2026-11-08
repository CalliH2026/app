"""Root-side live harness for H Parallel through Calli's adapter: real providers, fresh state, semantic checks.

  report          real H analysis of the fictitious Pythagore case (report only, no video)
  practice        live Devin practice from that report: one session create, no retry
  outing          Holo4 school-outing preparation (H cloud workstation + Linkup + OSRM)
  record-outing   turn an existing outing job file (e.g. from Francois's own app) into a bench record

Each subcommand prints a JSON summary and, with --out, appends one record in the scripts/bench.py schema. It
exits 1 unless the semantic checks pass. Keys come from the environment only (HAI_API_KEY or H_COMPANY_API_KEY,
GLADIA_API_KEY, LINKUP_API_KEY, DEVIN_API_KEY or DEVIN_API, DEVIN_ORG_ID); they are never printed. No simulation
is ever substituted for a failed provider call.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calli_parallel import checks, loader
from scripts import bench

CONDITIONS = ("cold", "warm", "unknown")


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fresh(data_dir: Path, reuse: bool, condition: str) -> None:
    if data_dir.exists() and any(data_dir.iterdir()):
        if not reuse:
            raise SystemExit(f"{data_dir} is not empty: use a fresh directory, or --reuse with --condition warm")
        if condition != "warm":
            raise SystemExit("a reused state directory is a warm run: pass --condition warm")


def _emit(record: dict[str, Any], summary: dict[str, Any], out: Path | None) -> int:
    bench.check(record)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return 0 if record["ok"] else 1


def _tool_timings(job: dict[str, Any]) -> list[dict[str, Any]]:
    out = [{"name": c.get("name"), "kind": "model_tool", "status": c.get("status"), "cached": bool(c.get("cached")),
            "elapsed_s": round(c["duration_ms"] / 1000, 3) if isinstance(c.get("duration_ms"), (int, float)) else None}
           for c in job.get("tool_calls") or []]
    out += [{"name": e.get("tool_name"), "kind": "app_api", "status": e.get("status"),
             "elapsed_s": round(e["duration_ms"] / 1000, 3) if isinstance(e.get("duration_ms"), (int, float)) else None}
            for e in job.get("executions") or []]
    return out


def cmd_report(a: argparse.Namespace) -> int:
    from calli_parallel import report_only

    _fresh(a.data_dir, a.reuse, a.condition)
    loader.upstream(a.data_dir)
    t0, started = time.monotonic(), _now()
    job = report_only.run(scenario=a.scenario, runtime=a.runtime, model=a.model, timeout_s=a.timeout)
    elapsed = round(time.monotonic() - t0, 2)
    failed = checks.report_checks(job)
    state = a.data_dir.resolve() / job["id"] / "state.json"
    record = {"scenario": f"pythagore-report-{a.scenario}", "arm": "agent", "basis": "measured",
              "condition": a.condition, "started_at": started, "ended_at": _now(), "elapsed_s": elapsed,
              "ok": not failed, "failure": "; ".join(failed) or None, "retries": 0, "tools": _tool_timings(job),
              "artifacts": [f"{state} sha256:{_sha(state)}"], "source": f"{state} {job.get('session_id') or ''}".strip(),
              "labels": {"h_session_id": job.get("session_id"), "runtime": a.runtime, "model": a.model,
                         "workflow": job.get("workflow_version"), "report_job": job["id"]}}
    return _emit(record, {"report_job": job["id"], "status": job.get("status"), "h_session_id": job.get("session_id"),
                          "error": job.get("error"), "failed_checks": failed, "elapsed_s": elapsed}, a.out)


def _ensure_devin_org() -> None:
    loader.alias_credentials()
    if not os.environ.get("DEVIN_API_KEY"):
        raise SystemExit("DEVIN_API_KEY (or DEVIN_API) is not set")
    if os.environ.get("DEVIN_ORG_ID"):
        return
    import httpx

    resp = httpx.get("https://api.devin.ai/v3/self", headers={"Authorization": "Bearer " + os.environ["DEVIN_API_KEY"]},
                     timeout=30, follow_redirects=False)
    resp.raise_for_status()
    org = (resp.json() or {}).get("org_id")
    if not isinstance(org, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", org):
        raise SystemExit("GET /v3/self returned no usable org_id; set DEVIN_ORG_ID")
    os.environ["DEVIN_ORG_ID"] = org


def cmd_practice(a: argparse.Namespace) -> int:
    mods = loader.upstream(a.data_dir)
    job = mods.engine.JOBS.get(a.report_job)
    if job is None:
        raise SystemExit(f"no report job {a.report_job} in {a.data_dir}")
    failed = checks.report_checks(job)
    if failed:
        raise SystemExit("the report is not a verified live H analysis: " + "; ".join(failed))
    folder = mods.practice.FOLDER / a.report_job
    live_state = folder / "state-live.json"
    if live_state.exists():
        raise SystemExit(f"{live_state} exists: reconcile that Devin session instead of creating another")
    _ensure_devin_org()
    brief = mods.practice._source(a.report_job)["brief"]
    t0, started = time.monotonic(), _now()
    mods.practice.start(a.report_job, mode="live")
    deadline = t0 + a.timeout
    while time.monotonic() < deadline and mods.practice.get(a.report_job)["status"] == "running":
        time.sleep(5)
    elapsed = round(time.monotonic() - t0, 2)
    state = json.loads(live_state.read_text(encoding="utf-8")) if live_state.exists() else {}
    if state.get("status") == "running":
        state["status"] = "unknown (harness timeout; the Devin session may still be working)"
    failed = checks.practice_checks(state, folder)
    artifact = folder / "activity-live.html"
    record = {"scenario": "pythagore-practice-devin-live", "arm": "agent", "basis": "measured",
              "condition": a.condition, "started_at": started, "ended_at": _now(), "elapsed_s": elapsed,
              "ok": not failed, "failure": "; ".join(failed) or None, "retries": 0, "tools": [],
              "artifacts": [f"{artifact} sha256:{_sha(artifact)}"] if artifact.is_file() else [],
              "source": f"{live_state} {state.get('session_id') or state.get('created_session_id') or ''}".strip(),
              "labels": {"devin_session_id": state.get("session_id"), "created_session_id": state.get("created_session_id"),
                         "session_url": state.get("session_url"), "acus_consumed": state.get("acus_consumed"),
                         "acus_reported": state.get("acus_reported"), "priority_skills": brief["priority_skills"],
                         "h_session_id": job.get("session_id"), "report_job": a.report_job,
                         "provider_claims": "math/browser tests are Devin's report, not a local verification"}}
    return _emit(record, {"status": state.get("status"), "message": state.get("message"),
                          "devin_session": state.get("session_url"), "priority_skills": brief["priority_skills"],
                          "artifact": str(artifact) if artifact.is_file() else None, "failed_checks": failed,
                          "elapsed_s": elapsed}, a.out)


def _outing_record(mods: Any, job: dict[str, Any], path: Path, condition: str, measured_s: float | None) -> tuple:
    destination = next(d for d in mods.outings.DESTINATIONS if d["id"] == job["input"]["destination_id"])
    failed = checks.outing_checks(job, destination["domain"])
    created, ended = bench._iso(job.get("created_at")), bench._iso(job.get("completed_at") or job.get("updated_at"))
    elapsed = measured_s if measured_s is not None else round((ended - created).total_seconds(), 2)
    execs = [e for e in job.get("executions") or [] if isinstance(e.get("duration_ms"), (int, float))]
    starts = [bench._iso(e["started_at"]) for e in execs if e.get("started_at")]
    ends = [bench._iso(e["ended_at"]) for e in execs if e.get("ended_at")]
    visit = job.get("visit") or {}
    labels = {"h_session_id": job.get("session_id"), "outing_job": job["id"], "status": job.get("status"),
              "max_concurrent": (job.get("parallel") or {}).get("max_concurrent"),
              "collections_sum_s": round(sum(e["duration_ms"] for e in execs) / 1000, 3),
              "collections_span_s": round((max(ends) - min(starts)).total_seconds(), 3) if starts and ends else None,
              "unknown_visit_fields": [f for f in ("opening_time", "closing_time", "closed_on_date", "student_unit_price",
                                                   "adult_unit_price", "group_fee", "max_group_size") if visit.get(f) is None],
              "unsupported_fields": visit.get("unsupported_fields"),
              "h_outcome": job.get("h_outcome"), "h_error": job.get("h_error"),
              "session_cancel": job.get("session_cancel"),
              "provider_status_after_wait": (job.get("session_cleanup") or {}).get("provider_status_before"),
              "evidence_note": "Linkup excerpts are provider quotes, not independently validated page content; the "
                               "workstation screenshot proves navigation only"}
    record = {"scenario": f"school-outing-{destination['id']}", "arm": "agent", "basis": "measured",
              "condition": condition, "started_at": job.get("created_at"), "ended_at": job.get("completed_at"),
              "elapsed_s": elapsed, "ok": not failed, "failure": "; ".join(failed) or None,
              "retries": sum(c.get("status") == "failed" for c in job.get("tool_calls") or []),
              "tools": _tool_timings(job), "artifacts": [f"{path} sha256:{_sha(path)}"],
              "source": f"{path} {job.get('session_id') or ''}".strip(), "labels": labels}
    return record, failed


def cmd_outing(a: argparse.Namespace) -> int:
    _fresh(a.data_dir, a.reuse, a.condition)
    mods = loader.upstream(a.data_dir)
    payload = {"destination_id": a.destination, "objective": a.objective}
    if a.date:
        payload["date"] = a.date
    t0 = time.monotonic()
    job = mods.outings.start(payload)
    deadline = t0 + a.timeout
    while time.monotonic() < deadline and job["status"] == "preparing":
        time.sleep(3)
        job = mods.outings.get(job["id"])
    measured = round(time.monotonic() - t0, 2)
    if job["status"] == "preparing":
        job = {**job, "status": "unknown (harness timeout; the H session may still be running)"}
    path = mods.outings.FOLDER / (job["id"] + ".json")
    record, failed = _outing_record(mods, job, path, a.condition, measured)
    return _emit(record, {"outing_job": job["id"], "status": job["status"], "h_session_id": job.get("session_id"),
                          "failed_checks": failed, "labels": record["labels"]}, a.out)


def cmd_record_outing(a: argparse.Namespace) -> int:
    mods = loader.upstream(Path(tempfile.mkdtemp(prefix="h-parallel-record-")))
    job = json.loads(a.job_file.read_text(encoding="utf-8"))
    record, failed = _outing_record(mods, job, a.job_file, a.condition, None)
    return _emit(record, {"outing_job": job.get("id"), "status": job.get("status"), "failed_checks": failed,
                          "labels": record["labels"]}, a.out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser, data: bool = True) -> None:
        if data:
            sp.add_argument("--data-dir", type=Path, required=True, help="H Parallel state directory")
        sp.add_argument("--condition", choices=CONDITIONS, required=True)
        sp.add_argument("--out", type=Path, help="append the bench record to this JSONL file")

    r = sub.add_parser("report", help="real H analysis of the Pythagore case, report only")
    common(r)
    r.add_argument("--scenario", choices=["points", "progress"], default="points")
    r.add_argument("--runtime", choices=["managed", "local"], default="managed")
    r.add_argument("--model", default=None)
    r.add_argument("--timeout", type=int, default=600)
    r.add_argument("--reuse", action="store_true")
    r.set_defaults(fn=cmd_report)
    pr = sub.add_parser("practice", help="live Devin practice from a verified report")
    common(pr)
    pr.add_argument("--report-job", required=True)
    pr.add_argument("--timeout", type=int, default=720)
    pr.set_defaults(fn=cmd_practice)
    o = sub.add_parser("outing", help="Holo4 school-outing preparation")
    common(o)
    o.add_argument("--destination", default="orsay")
    o.add_argument("--date", default=None, help="YYYY-MM-DD, default: upstream's proposed weekday")
    o.add_argument("--objective", default="Observer des œuvres étudiées en classe et préparer un compte rendu.")
    o.add_argument("--timeout", type=int, default=480)
    o.add_argument("--reuse", action="store_true")
    o.set_defaults(fn=cmd_outing)
    ro = sub.add_parser("record-outing", help="bench record from an existing outing job file")
    common(ro, data=False)
    ro.add_argument("--job-file", type=Path, required=True)
    ro.set_defaults(fn=cmd_record_outing)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
