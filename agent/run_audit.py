"""Audit arm: an independent, read-only session re-reads fields another arm wrote and reports what is there.

Why: the baseline arm (agent/run_baseline.py) can only report what the agent itself claims to have
read back. This arm opens a fresh session with no memory of the writes, copies each field from the
page text and compares it with the approved text under the same rule as the Calligraphe arm. The
journal carries arm = audit, so scripts/report.py shows it as its own row.

Usage:
    python -m agent.run_audit --items data/moodle_batch_a.csv --target moodle --audited-session <session id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from agent.journal import Event, Journal
from agent.queue import Queue, same_text, similarity
from agent.run_baseline import parse_answer
from agent.run_writer import _to_dict, environments_for, extract_metrics, fetch_usage, load_instructions


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--items", required=True)
    p.add_argument("--target", default="moodle", choices=["moodle", "pronote"])
    p.add_argument("--only-set", default=None)
    p.add_argument("--audited-session", default="", help="id of the session whose writes are audited (journal note)")
    p.add_argument("--run-dir", default=None)
    p.add_argument("--max-steps", type=int, default=120)
    p.add_argument("--max-time", type=float, default=900.0)
    p.add_argument("--model", default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.run_dir or f"runs/{run_id}-audit")
    queue = Queue.from_csv(Path(args.items), only_set=args.only_set)
    listing = "\n".join(
        f"- item_id {it.item_id}: student {it.student!r}" + (f", course {it.course!r}" if it.course else "")
        for it in queue.items
    )
    task = (
        "READ-ONLY CHECK. Do not type in any field and do not save anything. For each student below, open "
        "the grading page of the assignment named in the application notes and copy the CURRENT content of "
        "the feedback comments field exactly as it appears in the page text (an empty string if the field is "
        "empty). Answer with a JSON array of objects {\"item_id\", \"student_seen\", \"text_read_back\"} and "
        f"nothing else.\n\nStudents:\n{listing}\n"
    )
    print(f"[audit] run {run_id} target={args.target} items={len(queue.items)} dir={run_dir}")
    if args.dry_run:
        print(task)
        return 0
    if not os.environ.get("HAI_API_KEY"):
        print("HAI_API_KEY is not set", file=sys.stderr)
        return 2

    from hai_agents import Client

    run_dir.mkdir(parents=True, exist_ok=True)
    journal = Journal(run_dir / "journal.jsonl")
    notes = load_instructions(args.target).replace("`next_item`", "the list").replace("`report_result`", "your final answer")
    notes += "\n\nThis session is an audit: you never write, you only read fields and report their content."
    agent_spec: dict[str, Any] = {
        "name": f"audit-{args.target}",
        "description": "Reads report-card comment fields in school software and reports their content (audit arm, read-only).",
        "environments": environments_for(args.target, None),
        "instructions": notes,
    }
    if args.model:
        agent_spec["model"] = args.model

    client = Client()
    t0 = time.time()
    result = client.run_session(agent=agent_spec, messages=task, max_steps=args.max_steps,
                                max_time_s=args.max_time, timezone="Europe/Paris")
    elapsed = time.time() - t0
    status = fetch_usage(client, result.id)
    steps, tokens, model, cost_usd = extract_metrics(status)
    claims = {str(c.get("item_id")): c for c in parse_answer(result.answer)}
    per_item = elapsed / max(1, len(queue.items))
    note = f"audit arm: independent read of the fields written by session {args.audited_session or 'unknown'}"
    for it in queue.items:
        c = claims.get(it.item_id)
        read_back = str(c.get("text_read_back", "")) if c else ""
        if not read_back.strip():
            st = "not_found"
        else:
            st = "verified" if same_text(it.text, read_back) else "mismatch"
        journal.append(Event(arm="audit", target=args.target, run_id=run_id, item_id=it.item_id, student=it.student,
                             student_seen=str(c.get("student_seen", "")) if c else None, before=None,
                             after=it.text, text_read_back=read_back or None, status=st,
                             similarity=round(similarity(it.text, read_back), 3) if read_back else None,
                             seconds=round(per_item, 1), session_id=result.id, model=model, note=note))
    summary = {
        "run_id": run_id, "arm": "audit", "target": args.target, "session_id": result.id,
        "audited_session": args.audited_session,
        "status": str(result.status), "outcome": result.outcome, "error": result.error, "error_code": result.error_code,
        "answer": result.answer if isinstance(result.answer, str) else _to_dict(result.answer) if result.answer else None,
        "elapsed_s": round(elapsed, 1), "steps": steps, "tokens": tokens, "model": model,
        "cost_usd": cost_usd, "cost_note": "estimate at Models API list prices from the session's token usage",
        "items": {s: sum(1 for r in journal.read() if r["status"] == s) for s in ("verified", "mismatch", "not_found")},
        "events": len(result.events or []),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "session_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str),
                                                 encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
