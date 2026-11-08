"""Baseline arm (ablation): the same items, one plain H session, no custom tools, no verifier in the loop.

The agent receives the list of comments in a single instruction and is asked to
write them all, then to read each one back and answer with a JSON list. Our
code compares its claimed read-backs to the approved texts exactly as the
Calligraphe arm does, so both arms share one journal format (arm = baseline).
What this arm lacks by design: per-item hand-out, the write policy carried by
the tools, the read-back comparison during the run, the corrective retry.

Usage:
    python -m agent.run_baseline --items data/moodle_run1.csv --only-set run1 --target moodle
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from agent.journal import Event, Journal
from agent.queue import Queue, same_text, similarity
from agent.run_writer import _to_dict, environments_for, extract_metrics, fetch_usage, load_instructions


def parse_answer(answer: Any) -> list[dict[str, Any]]:
    """Find a JSON array of {student, text_read_back} objects in the agent's answer, leniently."""
    if isinstance(answer, list):
        return [a for a in answer if isinstance(a, dict)]
    if isinstance(answer, dict):
        for v in answer.values():
            if isinstance(v, list):
                return [a for a in v if isinstance(a, dict)]
        return []
    text = str(answer or "")
    m = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--items", required=True)
    p.add_argument("--target", default="moodle", choices=["moodle", "pronote"])
    p.add_argument("--only-set", default=None)
    p.add_argument("--run-dir", default=None)
    p.add_argument("--max-steps", type=int, default=150)
    p.add_argument("--max-time", type=float, default=1500.0)
    p.add_argument("--model", default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.run_dir or f"runs/{run_id}-baseline")
    queue = Queue.from_csv(Path(args.items), only_set=args.only_set)
    base_instructions = load_instructions(args.target)
    listing = "\n".join(
        f"- item_id {it.item_id}: student {it.student!r}" + (f", course {it.course!r}" if it.course else "")
        + f", text: {it.text!r}" + (f" (the field currently contains {it.previous_value!r}, replace it)" if it.previous_value else "")
        for it in queue.items
    )
    task = (
        "Write ALL of the following comments, one per student, in the target application, following the "
        "application notes below. After writing them all, go back and read each one from the page, then answer "
        "with a JSON array of objects {\"item_id\", \"student_seen\", \"text_read_back\"} and nothing else.\n\n"
        f"Comments:\n{listing}\n"
    )
    print(f"[baseline] run {run_id} target={args.target} items={len(queue.items)} dir={run_dir}")
    if args.dry_run:
        print(task)
        return 0
    if not os.environ.get("HAI_API_KEY"):
        print("HAI_API_KEY is not set", file=sys.stderr)
        return 2

    from hai_agents import Client

    run_dir.mkdir(parents=True, exist_ok=True)
    journal = Journal(run_dir / "journal.jsonl")
    # the baseline agent gets the same application notes but no tools: strip tool mentions from the notes
    notes = base_instructions.replace("`next_item`", "the list").replace("`report_result`", "your final answer")
    agent_spec: dict[str, Any] = {
        "name": f"baseline-{args.target}",
        "description": "Writes a list of report-card comments into school software (ablation arm, no tools).",
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
    for it in queue.items:
        c = claims.get(it.item_id)
        read_back = str(c.get("text_read_back", "")) if c else ""
        if c is None:
            st = "aborted"
        else:
            st = "verified" if same_text(it.text, read_back) else "mismatch"
        journal.append(Event(arm="baseline", target=args.target, run_id=run_id, item_id=it.item_id, student=it.student,
                             student_seen=str(c.get("student_seen", "")) if c else None, before=it.previous_value,
                             after=it.text, text_read_back=read_back or None, status=st,
                             similarity=round(similarity(it.text, read_back), 3) if read_back else None,
                             seconds=round(per_item, 1), session_id=result.id, model=model,
                             note="baseline arm: status from the agent's own final read-back list"))
    summary = {
        "run_id": run_id, "arm": "baseline", "target": args.target, "session_id": result.id,
        "status": str(result.status), "outcome": result.outcome, "error": result.error, "error_code": result.error_code,
        "answer": result.answer if isinstance(result.answer, str) else _to_dict(result.answer) if result.answer else None,
        "elapsed_s": round(elapsed, 1), "steps": steps, "tokens": tokens, "model": model,
        "cost_usd": cost_usd, "cost_note": "estimate at Models API list prices from the session's token usage",
        "items": {s: sum(1 for r in journal.read() if r["status"] == s) for s in ("verified", "mismatch", "aborted")},
        "events": len(result.events or []),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "session_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str),
                                                 encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
