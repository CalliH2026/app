"""Timing harness: measured agent runs and labelled human estimates, never mixed.

Records are JSON lines (schema in docs/benchmark-protocol.md). Adapters turn existing evidence into records:
a Calli preparation job file, a writer run directory (runs/<id>), or a command timed by `record`.
`summarize` groups records by scenario, arm, basis and condition and reports n, failures, retries, median
and range. Side-by-side human/agent numbers are only produced when both arms have a successful record, and
they carry the human arm's basis, so an estimate is never presented as a measurement. No percentage is
computed: a ratio of an agent latency to a human estimate is not a measured saving.

Usage:
    python scripts/bench.py record --out bench.jsonl --scenario school-outing --condition cold \
        --artifact outputs/report.json -- python -m some.module
    python scripts/bench.py from-preparation <workspace>/preparations/prep-*.json --condition warm --out bench.jsonl
    python scripts/bench.py from-run runs/20261107-152520 --scenario pronote-writer-approved-text --out bench.jsonl
    python scripts/bench.py summarize bench.jsonl [--markdown]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.report import base_item, read_journal

ARMS = ("agent", "human")
BASES = ("measured", "estimate")
CONDITIONS = ("cold", "warm", "unknown", "n/a")


def check(record: dict[str, Any]) -> dict[str, Any]:
    """Validate one record; raise ValueError rather than aggregate an ambiguous number."""
    for key in ("scenario", "arm", "basis", "condition", "elapsed_s", "ok"):
        if key not in record:
            raise ValueError(f"missing field {key!r}")
    if not isinstance(record["scenario"], str) or not record["scenario"]:
        raise ValueError("scenario must be a non-empty string")
    if record["arm"] not in ARMS:
        raise ValueError(f"arm must be one of {ARMS}")
    if record["basis"] not in BASES:
        raise ValueError(f"basis must be one of {BASES}")
    if record["condition"] not in CONDITIONS:
        raise ValueError(f"condition must be one of {CONDITIONS}")
    if not isinstance(record["ok"], bool):
        raise ValueError("ok must be true or false")  # noqa: TRY004 - one error type per invalid record
    for key in ("elapsed_s", "active_s"):
        value = record.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
            raise ValueError(f"{key} must be a non-negative number")
    if record["elapsed_s"] is None:
        raise ValueError("elapsed_s is required")
    if not isinstance(record.get("retries", 0), int) or record.get("retries", 0) < 0:
        raise ValueError("retries must be a non-negative integer")
    if record["basis"] == "estimate":
        if record["arm"] != "human":
            raise ValueError("agent times are measured, never estimated")
        if not str(record.get("assumption") or "").strip():
            raise ValueError("an estimate must state its assumption")
    else:
        if not str(record.get("source") or "").strip():
            raise ValueError("a measured record must point to its evidence (source)")
        if not record.get("started_at"):
            raise ValueError("a measured record needs started_at")
    if record.get("cost_usd") is not None and not str(record.get("cost_note") or "").strip():
        raise ValueError("cost_usd needs a cost_note saying how it was obtained")
    return record


def _iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        # strftime("%z") gives +0100, which fromisoformat accepts only on 3.11+
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")


def from_preparation(job: dict[str, Any], source: str, condition: str = "unknown") -> dict[str, Any]:
    """One finished Calli preparation job file -> one measured agent record."""
    status = job.get("status")
    if status not in ("ready", "failed") or job.get("elapsed_s") is None:
        raise ValueError(f"preparation {job.get('id')} is not finished (status {status})")
    start = _iso(job.get("created_at"))
    tools = []
    for ev in job.get("events", []):
        if ev.get("kind") in ("model_tool", "app_api"):
            at = _iso(ev.get("at"))
            tools.append({"name": ev.get("text", ""), "kind": ev["kind"],
                          "offset_s": round((at - start).total_seconds(), 1) if at and start else None})
    diag = job.get("diagnostic") or {}
    failure = None if status == "ready" else ":".join(
        str(x) for x in (diag.get("stage"), diag.get("error_type")) if x) or "failed"
    return check({
        "scenario": "calli-preparation", "arm": "agent", "basis": "measured", "condition": condition,
        "started_at": job.get("created_at"), "ended_at": job.get("updated_at"),
        "elapsed_s": job["elapsed_s"], "active_s": None, "ok": status == "ready", "failure": failure,
        "retries": 0, "tools": tools, "artifacts": [source],
        "source": " ".join(x for x in (source, job.get("provider_session_id")) if x),
        "labels": {"runtime": job.get("provider_runtime"), "answer_contract": job.get("answer_contract"),
                   "trigger": "observed" if job.get("trigger") else "manual",
                   "preparation_version": job.get("preparation_version")},
    })


def from_run(run_dir: Path, scenario: str, condition: str = "unknown") -> dict[str, Any]:
    """One writer run directory (journal.jsonl + summary.json) -> one measured agent record."""
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    events = read_journal(run_dir / "journal.jsonl")
    if summary.get("elapsed_s") is None:
        raise ValueError(f"{run_dir} has no elapsed_s in summary.json")
    items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        items[base_item(ev["item_id"])].append(ev)
    final = {item: evs[-1]["status"] for item, evs in items.items()}
    verified = sum(s == "verified" for s in final.values())
    provider_ok = summary.get("provider_ok", summary.get("outcome") == "success")
    ok = bool(provider_ok) and bool(final) and verified == len(final)
    failure = None
    if not ok:
        failure = summary.get("error") or f"{verified}/{len(final)} verified"
    try:
        # run ids are the writer host's local time, without an offset (see labels.started_at_from)
        started = dt.datetime.strptime(run_dir.name[:15], "%Y%m%d-%H%M%S").isoformat()
    except ValueError:
        started = None
    ts = [e["ts"] for e in events if isinstance(e.get("ts"), (int, float))]
    ended = dt.datetime.fromtimestamp(max(ts), dt.timezone.utc).isoformat() if ts else None
    return check({
        "scenario": scenario, "arm": "agent", "basis": "measured", "condition": condition,
        "started_at": started, "ended_at": ended, "elapsed_s": summary["elapsed_s"], "active_s": None,
        "ok": ok, "failure": failure, "retries": sum(len(evs) - 1 for evs in items.values()),
        "tools": [{"name": item, "elapsed_s": sum(e.get("seconds") or 0 for e in evs)} for item, evs in items.items()],
        "artifacts": [str(run_dir / "journal.jsonl"), str(run_dir / "summary.json")],
        "source": " ".join(x for x in (str(run_dir), summary.get("session_id")) if x),
        "cost_usd": summary.get("cost_usd"), "cost_note": summary.get("cost_note"),
        "labels": {"model": summary.get("model"), "runtime": summary.get("runtime", "managed"),
                   "items": len(final), "verified": verified,
                   "started_at_from": "run id, writer host local time"},
    })


def record_command(cmd: list[str], scenario: str, condition: str, artifacts: list[str],
                   timeout_s: float | None = None) -> dict[str, Any]:
    """Run a command once, without retry, and measure its wall-clock time and expected artifacts."""
    started = dt.datetime.now().astimezone().isoformat()
    t0 = time.monotonic()
    try:
        code = subprocess.run(cmd, check=False, timeout=timeout_s).returncode
        failure = None if code == 0 else f"exit {code}"
    except subprocess.TimeoutExpired:
        failure = f"timeout after {timeout_s}s"
    elapsed = round(time.monotonic() - t0, 2)
    missing = [a for a in artifacts if not Path(a).exists()]
    if failure is None and missing:
        failure = "missing artifact " + ", ".join(missing)
    return check({
        "scenario": scenario, "arm": "agent", "basis": "measured", "condition": condition,
        "started_at": started, "ended_at": dt.datetime.now().astimezone().isoformat(),
        "elapsed_s": elapsed, "active_s": None, "ok": failure is None, "failure": failure, "retries": 0,
        "tools": [], "artifacts": artifacts, "source": " ".join(cmd), "labels": {},
    })


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "min": None, "max": None}
    return {"median": round(statistics.median(values), 2), "min": min(values), "max": max(values)}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        check(r)
        groups[(r["scenario"], r["arm"], r["basis"], r["condition"])].append(r)
    out = []
    for (scenario, arm, basis, condition), rs in sorted(groups.items()):
        good = [r for r in rs if r["ok"]]
        actives = [r["active_s"] for r in good if r.get("active_s") is not None]
        costs = [r.get("cost_usd") for r in rs]
        starts = sorted(r["started_at"] for r in rs if r.get("started_at"))
        out.append({
            "scenario": scenario, "arm": arm, "basis": basis, "condition": condition,
            "n": len(rs), "ok": len(good), "failed": len(rs) - len(good),
            "retries": sum(r.get("retries", 0) for r in rs),
            "elapsed_s": _stats([r["elapsed_s"] for r in good]),
            "active_s": _stats(actives),
            "first_started_at": starts[0] if starts else None, "last_started_at": starts[-1] if starts else None,
            "cost_usd": round(sum(costs), 4) if costs and all(c is not None for c in costs) else None,
            "failures": [r.get("failure") for r in rs if not r["ok"]],
        })
    return {"groups": out, "comparisons": compare(out)}


def compare(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for scenario in sorted({g["scenario"] for g in groups}):
        agents = [g for g in groups if g["scenario"] == scenario and g["arm"] == "agent" and g["ok"]]
        humans = [g for g in groups if g["scenario"] == scenario and g["arm"] == "human" and g["ok"]]
        if not agents or not humans:
            rows.append({"scenario": scenario, "computable": False,
                         "reason": "needs a successful agent record and a human record"})
            continue
        for a in agents:
            for h in humans:
                rows.append({
                    "scenario": scenario, "computable": True,
                    "human_basis": "measured human" if h["basis"] == "measured" else "estimated human",
                    "agent_condition": a["condition"], "agent_n": a["ok"], "human_n": h["ok"],
                    "agent_elapsed_median_s": a["elapsed_s"]["median"],
                    "human_elapsed_median_s": h["elapsed_s"]["median"],
                    "human_active_median_s": h["active_s"]["median"],
                })
    return rows


def render_markdown(summary: dict[str, Any]) -> str:
    def f(v: Any) -> str:
        return "—" if v is None else str(v)

    lines = [
        (
            "| Scenario | Arm | Basis | Condition | n | OK | Failed | Retries | Elapsed median (s) | Range (s) "
            "| Human active median (s) | Cost (USD) |"
        ),
        "|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    for g in summary["groups"]:
        e = g["elapsed_s"]
        rng = "—" if e["min"] is None else f"{e['min']}–{e['max']}"
        lines.append(f"| {g['scenario']} | {g['arm']} | {g['basis']} | {g['condition']} | {g['n']} | {g['ok']} "
                     f"| {g['failed']} | {g['retries']} | {f(e['median'])} | {rng} | {f(g['active_s']['median'])} "
                     f"| {f(g['cost_usd'])} |")
    for c in summary["comparisons"]:
        if not c["computable"]:
            lines.append(f"\n{c['scenario']}: no comparison ({c['reason']}).")
        else:
            lines.append(f"\n{c['scenario']} ({c['human_basis']}, agent {c['agent_condition']}): agent elapsed "
                         f"{f(c['agent_elapsed_median_s'])} s (n={c['agent_n']}), human elapsed "
                         f"{f(c['human_elapsed_median_s'])} s, human active {f(c['human_active_median_s'])} s "
                         f"(n={c['human_n']}).")
    return "\n".join(lines) + "\n"


def _load(paths: list[Path]) -> list[dict[str, Any]]:
    out = []
    for p in paths:
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    out.append(check(json.loads(line)))
                except ValueError as exc:
                    raise SystemExit(f"{p}:{n}: {exc}") from None
    return out


def _append(path: Path | None, records: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="time one command run (no retry) and append a measured record")
    rec.add_argument("--scenario", required=True)
    rec.add_argument("--condition", choices=CONDITIONS, required=True)
    rec.add_argument("--artifact", action="append", default=[], help="file that must exist after a success")
    rec.add_argument("--timeout", type=float, default=None)
    rec.add_argument("--out", type=Path)
    rec.add_argument("command", nargs=argparse.REMAINDER)
    prep = sub.add_parser("from-preparation", help="convert finished Calli preparation job files")
    prep.add_argument("jobs", type=Path, nargs="+")
    prep.add_argument("--condition", choices=CONDITIONS, default="unknown")
    prep.add_argument("--out", type=Path)
    run = sub.add_parser("from-run", help="convert writer run directories (runs/<id>)")
    run.add_argument("runs", type=Path, nargs="+")
    run.add_argument("--scenario", required=True)
    run.add_argument("--condition", choices=CONDITIONS, default="unknown")
    run.add_argument("--out", type=Path)
    summ = sub.add_parser("summarize", help="group records: n, failures, retries, median and range")
    summ.add_argument("records", type=Path, nargs="+")
    summ.add_argument("--markdown", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "record":
        cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
        if not cmd:
            p.error("record needs a command after --")
        r = record_command(cmd, a.scenario, a.condition, a.artifact, a.timeout)
        _append(a.out, [r])
        return 0 if r["ok"] else 1
    if a.cmd == "from-preparation":
        _append(a.out, [from_preparation(json.loads(j.read_text(encoding="utf-8")), str(j), a.condition)
                        for j in a.jobs])
        return 0
    if a.cmd == "from-run":
        _append(a.out, [from_run(r, a.scenario, a.condition) for r in a.runs])
        return 0
    s = summarize(_load(a.records))
    sys.stdout.write(render_markdown(s) if a.markdown else json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
