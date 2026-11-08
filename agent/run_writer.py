"""Calligraphe writer loop.

Runs an H Company computer-use agent that writes approved comments into a target
application (Moodle demo in the cloud browser, PRONOTE on a desktop) through two
custom tools: `next_item` hands out one approved item at a time, `report_result`
records what was written and what was read back. Every item ends in the journal
with a status decided here, by comparing the read-back to the approved text,
never by trusting the agent's own judgement.

Usage:
    python -m agent.run_writer --items data/demo_items.csv --target moodle
    python -m agent.run_writer --items data/demo_items.csv --target moodle --only-set demo --max-steps 60
    python -m agent.run_writer --queue runs/queue.jsonl --target moodle      # live: items approved in ui/app.py

Environment: HAI_API_KEY (never printed). The default platform is the EU one.
Optional: STRIPE_SECRET_KEY (test mode) and STRIPE_CUSTOMER_ID meter each verified write (billing/meter.py).
CSV mode: a file named STOP in the run directory drains the queue at the next `next_item`.
Live mode (--queue): a file named STOP next to the queue file does; while the queue is
momentarily empty, `next_item` asks the agent to wait, up to --idle-timeout seconds.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from agent.identity import identity_mismatch
from agent.journal import Event, Journal
from agent.queue import Queue, same_text, similarity

TARGETS_DIR = Path(__file__).parent / "targets"
MODEL_DEFAULT = None  # platform default for the inline agent; set --model to pin holo4-27b or holo4-35b-a3b
WAIT_SECONDS = 8
IDLE_TIMEOUT_S = 300.0
WAIT_REPLY = {"wait": True, "seconds": WAIT_SECONDS,
              "message": f"no approved item yet, call wait_web for {WAIT_SECONDS} seconds then next_item again"}
NEXT_ITEM_DOC = ("Return the next approved comment to write as {item_id, student, course, text, previous_value}, "
                 "or null when the queue is empty or stopped.")
NEXT_ITEM_DOC_LIVE = ("Return the next approved comment to write as {item_id, student, course, text, previous_value}. "
                      "If it returns {wait: true, seconds, message}, the teacher is still dictating: wait that many "
                      "seconds, then call next_item again. Null means stop: the queue is closed or STOP was pressed.")


def make_next_item(queue: Queue, started: dict[str, float], live: bool = False,
                   idle_timeout: float = IDLE_TIMEOUT_S, clock: Any = time.monotonic) -> Any:
    """The `next_item` tool. Live mode: an empty queue means "wait", until `idle_timeout` seconds without an item."""
    idle_since: list[float | None] = [None]

    def next_item() -> dict[str, Any] | None:
        it = queue.next_pending()
        if it is None:
            if not live or queue.stop_requested():
                print("[tool] next_item -> null (queue empty or STOP)")
                return None
            now = clock()
            if idle_since[0] is None:
                idle_since[0] = now
            if now - idle_since[0] >= idle_timeout:
                print(f"[tool] next_item -> null (no approved item for {idle_timeout:.0f}s)")
                return None
            print("[tool] next_item -> wait")
            return dict(WAIT_REPLY)
        idle_since[0] = None
        started[it.item_id] = time.time()
        print(f"[tool] next_item -> {it.item_id} for {it.student!r}")
        return {"item_id": it.item_id, "student": it.student, "course": it.course, "text": it.text,
                "previous_value": it.previous_value}

    next_item.__doc__ = NEXT_ITEM_DOC_LIVE if live else NEXT_ITEM_DOC
    return next_item


def bill_verified(run_id: str, item_id: str, client: Any = None) -> tuple[bool | None, str]:
    """Meter one verified write when Stripe is configured: (billed, note suffix). Never raises."""
    customer = os.environ.get("STRIPE_CUSTOMER_ID")
    if not (os.environ.get("STRIPE_SECRET_KEY") and customer):
        return None, ""
    from billing.meter import record_verified_write  # imported late: metering is optional

    try:
        record_verified_write(run_id, item_id, customer, client=client)
    except Exception as e:  # billing must never change the status of a write
        print(f"[billing] {item_id} not billed: {e}", file=sys.stderr)
        return False, f"; not billed: {e}"
    return True, "; billed as one verified write"


def settle_unfinished(items: list[Any], queue: Queue, journal: Journal, *, run_id: str, arm: str, target: str,
                      session_id: str | None, reason: str) -> None:
    """At session end: an item handed out but never reported is `unknown` (it may have been typed), an item
    never started is `aborted`. Both are journaled; neither is retried."""
    for it in items:
        if it.status not in ("pending", "in_progress"):
            continue
        started = it.status == "in_progress"
        it.status = "unknown" if started else "aborted"
        note = (f"session ended mid-item ({reason}): persistence unknown, check the cell" if started
                else f"session ended before this item started ({reason})")
        queue.save(it, note=note, **({} if started else {"not_started": True}))
        journal.append(Event(arm=arm, target=target, run_id=run_id, item_id=it.item_id, student=it.student,
                             after=it.text, status=it.status, session_id=session_id, note=note))


def make_report_result(queue: Queue, journal: Journal, started: dict[str, float], *, run_id: str, arm: str,
                       target: str, retry: bool = True, billing_client: Any = None) -> Any:
    """The `report_result` tool: the status is decided here, by comparing the read-back to the approved text
    and the student name read back to the approved student (agent/identity.py)."""

    def report_result(item_id: str, status: str, student_seen: str = "", text_read_back: str = "") -> str:
        """Report one item after writing it: item_id, status (written|mismatch|not_found|aborted), the student name as displayed, and the exact text read back after leaving and returning. Idempotent per item_id."""
        it = queue.get(item_id)
        if it is None:
            return f"unknown item_id {item_id}"
        if it.status in ("verified", "mismatch", "not_found", "aborted", "abstained", "unknown"):
            return f"{item_id} already reported as {it.status}"
        it.student_seen = student_seen
        it.text_read_back = text_read_back
        wrong_row = None
        no_read_back = status == "written" and same_text("", text_read_back or "")
        claimed_abort = status == "aborted"
        if no_read_back or claimed_abort:
            # "written" without a read-back, or "aborted" after the item was handed out (the target rules report
            # aborted after a wrong-cell edit): persistence is not confirmed either way, so never retried
            it.status = "unknown"
        elif status == "written":
            wrong_row = identity_mismatch(it.student, student_seen)
            it.status = "verified" if wrong_row is None and same_text(it.text, text_read_back) else "mismatch"
        elif status == "not_found":
            it.status = status
        else:
            wrong_row = identity_mismatch(it.student, student_seen)
            it.status = "mismatch"
        sim = similarity(it.text, text_read_back or "")
        seconds = time.time() - started.get(item_id, time.time())
        if no_read_back:
            note = "no read-back: persistence unknown, no corrective write queued"
        elif claimed_abort:
            note = "agent reported aborted after the item was handed out: a partial write is possible, unknown"
        else:
            note = "status decided by read-back comparison of text and student"
        if wrong_row is not None:
            note += f"; {wrong_row}; no corrective write queued"
        queue.save(it, similarity=round(sim, 3), seconds=round(seconds, 1))
        retry_item = None
        # a corrective write goes only to a row known to be the right student, never into a possibly wrong one
        if it.status == "mismatch" and retry and wrong_row is None:
            retry_item = queue.add_retry(it, text_read_back)
            if retry_item is not None:
                note += "; one corrective write queued"
        billed = None
        if it.status == "verified":
            billed, billing_note = bill_verified(run_id, item_id, billing_client)
            note += billing_note
        journal.append(Event(arm=arm, target=target, run_id=run_id, item_id=item_id, student=it.student,
                             student_seen=student_seen, before=it.previous_value, after=it.text,
                             text_read_back=text_read_back, status=it.status, similarity=round(sim, 3),
                             seconds=round(seconds, 1), billed=billed, note=note))
        print(f"[tool] report_result {item_id}: {it.status} (similarity {sim:.3f}, {seconds:.0f}s)")
        if wrong_row is not None:
            return (f"{item_id} recorded as mismatch: the row read back shows {student_seen!r}, not "
                    f"{it.student!r}. No corrective write is queued; do not type in that row again. "
                    f"Call next_item for the next one.")
        if it.status == "unknown":
            return (f"{item_id} recorded as unknown: the write is not confirmed either way. Do not write it again. "
                    f"Call next_item for the next one.")
        if retry_item is not None:
            return (f"{item_id} recorded as mismatch: the field now contains {text_read_back!r}, which differs from the "
                    f"approved text. A corrective item {retry_item.item_id} is queued: call next_item, it will give you "
                    f"the exact text to write again, replacing the current content.")
        return f"{item_id} recorded as {it.status}. Call next_item for the next one."

    return report_result


def load_instructions(target: str) -> str:
    path = TARGETS_DIR / f"{target}.md"
    if not path.exists():
        raise SystemExit(f"unknown target {target!r}: no {path}")
    return path.read_text(encoding="utf-8")


def environments_for(target: str, start_url: str | None, desktop_session_id: str | None = None) -> list[Any]:
    if target == "moodle":
        # markdown: the agent receives the viewport's text with each screenshot, so a read-back can be
        # copied from the page text instead of transcribed from pixels (run 2 misread "rédaction" twice)
        return [{"id": "moodle-browser", "kind": "web", "start_url": start_url or "https://school.moodledemo.net/",
                 "mode": {"type": "visual", "width": 1440, "height": 1000, "markdown": True}}]
    if target == "pronote":
        # a desktop served by `holo local desktop`: this machine by default, or another one (the Windows VM)
        # when its printed session_id is given; the loop, the tools and the journal stay where this runs
        env: dict[str, Any] = {"id": "desktop", "kind": "desktop", "host": "user_device"}
        if desktop_session_id:
            env["session_id"] = desktop_session_id
        return [env]
    raise SystemExit(f"no environment mapping for target {target!r}")


def _to_dict(obj: Any) -> dict[str, Any]:
    for attr in ("model_dump", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            with contextlib.suppress(Exception):
                return fn()
    try:
        return dict(vars(obj))
    except Exception:
        return {"repr": repr(obj)}


def fetch_usage(client: Any, session_id: str) -> dict[str, Any]:
    """Best-effort: session status with step count and token usage, as exposed by the SDK."""
    sessions = getattr(client, "sessions", None)
    for name in ("get_session_status", "get_session", "status", "get"):
        fn = getattr(sessions, name, None)
        if callable(fn):
            try:
                return _to_dict(fn(session_id))
            except Exception as e:  # keep going, usage is nice to have
                last = f"{name}: {type(e).__name__}"
                continue
    return {"note": locals().get("last", "no sessions accessor")}


# Models API list prices in USD per million tokens: (input, cached input, output). Source: hub.hcompany.ai Models
# table read on 7 November 2026. Reasoning tokens are counted as output. This is an estimate of the session's
# cost at list price, not an invoice; the platform's own figure per session is the reference.
PRICES_USD_PER_M = {
    "holo4-27b": (0.40, 0.04, 3.00),
    "holo4-35b-a3b": (0.30, 0.03, 2.00),
    "holo3-1-35b-a3b": (0.25, 0.025, 1.80),
    "holo3-122b-a10b": (0.40, 0.04, 3.00),
}


def extract_metrics(status: dict[str, Any]) -> tuple[int | None, int | None, str | None, float | None]:
    """Return (steps, total_tokens, model, cost_usd) from a session status dict, when present.

    The platform reports `steps` and `usage_per_model` (name, input_tokens, cached_tokens, output_tokens,
    reasoning_tokens). Cost is computed from PRICES_USD_PER_M; None when the model is unknown.
    """
    steps = None
    for key in ("steps", "step_count", "n_steps"):
        if isinstance(status.get(key), int):
            steps = status[key]
            break
    usage = status.get("usage_per_model") or status.get("usage") or status.get("token_usage") or []
    if isinstance(usage, dict):
        usage = [{"name": m, **u} for m, u in usage.items() if isinstance(u, dict)]
    tokens = 0
    cost = 0.0
    model = None
    priced = False
    for u in usage:
        if not isinstance(u, dict):
            continue
        name = str(u.get("name") or u.get("model") or "")
        model = model or name or None
        inp = int(u.get("input_tokens") or 0)
        cached = int(u.get("cached_tokens") or 0)
        out = int(u.get("output_tokens") or 0) + int(u.get("reasoning_tokens") or 0)
        tokens += inp + out
        p = PRICES_USD_PER_M.get(name)
        if p:
            priced = True
            cost += (max(inp - cached, 0) * p[0] + cached * p[1] + out * p[2]) / 1_000_000
    return steps, (tokens or None), model, (round(cost, 4) if priced else None)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--items", help="CSV with item_id, student, text[, previous_value, set]")
    src.add_argument("--queue", help="live mode: the JSONL queue the approval screen writes (runs/queue.jsonl)")
    p.add_argument("--target", default="moodle", choices=["moodle", "pronote"])
    p.add_argument("--only-set", default=None, help="keep rows whose `set` column equals this value")
    p.add_argument("--arm", default="calligraphe")
    p.add_argument("--run-dir", default=None, help="default runs/<timestamp>")
    p.add_argument("--max-steps", type=int, default=120)
    p.add_argument("--max-time", type=float, default=1500.0, help="seconds for the whole session")
    p.add_argument("--model", default=MODEL_DEFAULT)
    p.add_argument("--start-url", default=None)
    p.add_argument("--desktop-session-id", default=None,
                   help="pronote target: session_id printed by `holo local desktop` on the machine that shows PRONOTE")
    p.add_argument("--runtime", default="managed", choices=["managed", "local"],
                   help="managed (default): H cloud agent loop. local: Client.local() on this machine with an inline "
                        "desktop; pronote only, run it inside the interactive Windows guest that shows PRONOTE")
    p.add_argument("--dry-run", action="store_true", help="load everything, create no session")
    p.add_argument("--no-retry", action="store_true", help="do not queue a corrective write after a mismatch")
    p.add_argument("--idle-timeout", type=float, default=IDLE_TIMEOUT_S,
                   help="live mode: seconds without an approved item before next_item returns null")
    args = p.parse_args(argv)
    if args.runtime == "local" and args.desktop_session_id:
        p.error("--runtime local drives this machine's desktop inline; --desktop-session-id names a separate "
                "`holo local desktop` bridge. Use one or the other.")
    if args.runtime == "local" and args.target != "pronote":
        p.error("--runtime local is for the pronote target, run on the Windows guest that shows PRONOTE")

    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.run_dir or f"runs/{run_id}")
    live = args.queue is not None
    if live:
        queue = Queue.from_store(Path(args.queue))
    else:
        queue = Queue.from_csv(Path(args.items), stop_file=run_dir / "STOP", only_set=args.only_set)
    instructions = load_instructions(args.target)
    print(f"[calligraphe] run {run_id} target={args.target} arm={args.arm} "
          f"{'live queue' if live else 'items'}={len(queue.items)} dir={run_dir}")

    if args.dry_run:
        for it in queue.items:
            print(f"  - {it.item_id} {it.student!r} {len(it.text)} chars {it.status}")
        return 0

    if not os.environ.get("HAI_API_KEY"):
        print("HAI_API_KEY is not set", file=sys.stderr)
        return 2

    run_dir.mkdir(parents=True, exist_ok=True)
    journal = Journal(run_dir / "journal.jsonl")
    if live and queue.store is not None:
        for rec in queue.store.recover():
            print(f"[calligraphe] {rec['item_id']} was left in progress by an earlier writer: unknown, check the cell")
        queue.refresh()

    from hai_agents import Client  # imported late so --dry-run works without the SDK

    started: dict[str, float] = {}
    next_item = make_next_item(queue, started, live=live, idle_timeout=args.idle_timeout)

    report_result = make_report_result(queue, journal, started, run_id=run_id, arm=args.arm, target=args.target,
                                       retry=not args.no_retry)

    client = Client.local() if args.runtime == "local" else Client()
    agent_spec: dict[str, Any] = {
        "name": f"calligraphe-{args.target}",
        "description": "Writes approved report-card comments into school software and reads them back.",
        "environments": environments_for(args.target, args.start_url, args.desktop_session_id),
        "instructions": instructions,
    }
    if args.model:
        agent_spec["model"] = args.model

    messages = ("Write the approved comments one at a time. Start by calling next_item. "
                "After each item, call report_result with what you read back, then call next_item again. "
                "Stop when next_item returns null and answer with a one-line summary.")
    if live:
        messages += (" The teacher is still dictating: when next_item returns wait, wait the given seconds "
                     "without touching the page, then call next_item again.")
    t0 = time.time()
    result, client_error = None, None
    try:
        try:
            result = client.run_session(
                agent=agent_spec,
                messages=messages,
                tools=[next_item, report_result],
                max_steps=args.max_steps,
                max_time_s=args.max_time,
                timezone="Europe/Paris",
            )
        except Exception as exc:  # the session never returned: recorded, settled below, never retried
            client_error = {"error_type": type(exc).__name__, "message": redact(str(exc))[:500]}
            print(f"[calligraphe] session failed: {type(exc).__name__}", file=sys.stderr)
        elapsed = time.time() - t0
        status = fetch_usage(client, result.id) if result is not None else {}
        # saved while a local runtime still serves its screenshots; closed only afterwards
        shots = save_events(result.events if result is not None else [], run_dir, local_fetcher(client))
    finally:
        if args.runtime == "local":
            try:
                client.close()
            except Exception as exc:
                print(f"[calligraphe] local runtime close failed: {type(exc).__name__}", file=sys.stderr)
    steps, tokens, model, cost_usd = extract_metrics(status)
    session_id = result.id if result is not None else None
    session_status = status_value(result.status) if result is not None else "client_error"
    queue.refresh()
    # live mode: the store also holds other sessions' items; this run is the items it handed out, and
    # approvals it never claimed stay pending for the next session
    run_items = [it for it in queue.items if it.item_id in started] if live else queue.items
    # settle before counting, so the summary and the exit code see unknown/aborted, never in_progress
    error_code = getattr(result, "error_code", None)
    settle_unfinished(run_items, queue, journal, run_id=run_id, arm=args.arm, target=args.target,
                      session_id=session_id, reason=f"{session_status} {error_code or ''}".strip())
    answer = getattr(result, "answer", None)
    provider_ok = result is not None and session_status in ("completed", "idle") and not error_code
    summary = {
        "run_id": run_id, "target": args.target, "arm": args.arm, "runtime": args.runtime, "session_id": session_id,
        "status": session_status, "provider_ok": provider_ok, "outcome": getattr(result, "outcome", None),
        "error": redact(str(result.error))[:500] if getattr(result, "error", None) else None,
        "error_code": error_code, "client_error": client_error,
        "answer": answer if isinstance(answer, str) else _to_dict(answer) if answer else None,
        "elapsed_s": round(elapsed, 1), "steps": steps, "tokens": tokens, "model": model,
        "cost_usd": cost_usd, "cost_note": "estimate at Models API list prices from the session's token usage",
        "items": _count(run_items), "events": len(getattr(result, "events", None) or []), "screenshots": shots,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "session_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # stamp the session id and metrics on all events of this run
    rows = journal.read()
    for r in rows:
        if r.get("run_id") == run_id:
            r["session_id"] = session_id
            r["model"] = r.get("model") or model
    with open(journal.path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # success needs a settled provider session AND every handed-out item verified: zero items is not success
    # when the provider failed
    return 0 if provider_ok and summary["items"].get("verified", 0) == len(run_items) else 1


_SECRET_ENVS = ("HAI_API_KEY", "GLADIA_API_KEY", "LINKUP_API_KEY", "HAI_AGENT_RUNTIME_API_TOKEN")
_BEARER = re.compile(r"(?i)(bearer\s+|(?:api[_-]?key|token|authorization)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;}]+")


def redact(text: str) -> str:
    for name in _SECRET_ENVS:
        value = os.environ.get(name)
        if value and len(value) >= 6:
            text = text.replace(value, "[redacted]")
    return _BEARER.sub(r"\1[redacted]", text)


def status_value(raw: Any) -> str:
    value = getattr(raw, "value", raw)
    return str(value).strip().lower() if value is not None else ""


def _origin(url: str) -> tuple[str, str, int, str] | None:
    """(scheme, host, effective port, path) of a credential-free http(s) URL, else None."""
    try:
        parts = urlsplit(url)
        port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or port is None or "@" in parts.netloc:
        return None
    path = unquote(parts.path)
    if "\\" in path or any(seg in (".", "..") for seg in path.split("/")):
        return None  # dot segments are resolved by the client after the base-path check
    return parts.scheme, parts.hostname.lower(), port, parts.path


def local_fetcher(client: Any) -> Callable[[str], bytes | None]:
    """Fetch an image served by this client's own local runtime with its authenticated HTTP client.

    Only an exact scheme/host/port match under the runtime's base path is fetched, with redirects off, so the
    runtime authorization is never sent to another origin. Other URLs stay links in events.jsonl."""
    runtime = getattr(client, "local_runtime", None)
    base = _origin(str(getattr(runtime, "base_url", "") or ""))
    http = getattr(getattr(getattr(client, "_client_wrapper", None), "httpx_client", None), "httpx_client", None)

    def fetch(url: str) -> bytes | None:
        target = _origin(url)
        if base is None or http is None or target is None or target[:3] != base[:3]:
            return None
        root = base[3].rstrip("/")
        if root and target[3] != root and not target[3].startswith(root + "/"):
            return None
        try:
            resp = http.get(url, follow_redirects=False)
        except Exception:
            return None
        kind = str(resp.headers.get("content-type", "")).lower()
        return resp.content if resp.status_code == 200 and kind.startswith("image/") else None
    return fetch


def save_events(events: list[Any], run_dir: Path, fetch: Callable[[str], bytes | None]) -> int:
    """events.jsonl with secrets redacted; inline or local-runtime screenshots saved under screenshots/."""
    shots = run_dir / "screenshots"
    count = 0

    def saved(data: bytes) -> dict[str, str]:
        nonlocal count
        count += 1
        shots.mkdir(parents=True, exist_ok=True)
        name = f"{count:04d}.png"
        (shots / name).write_bytes(data)
        return {"saved": f"screenshots/{name}"}

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            if value.get("type") == "base64" and isinstance(value.get("source"), str):
                with contextlib.suppress(ValueError):
                    shot = saved(base64.b64decode(value["source"].split(",", 1)[-1], validate=False))
                    return {**{k: walk(v) for k, v in value.items() if k != "source"}, "source": shot}
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if not isinstance(value, str):
            return value
        data = None
        if value.startswith("data:image/") and ";base64," in value:
            with contextlib.suppress(ValueError):
                data = base64.b64decode(value.split(";base64,", 1)[1], validate=False)
        elif value.startswith(("http://", "https://")):
            data = fetch(value)
        if data is None:
            return redact(value) if not value.startswith("data:") else "[inline data omitted]"
        return saved(data)

    with open(run_dir / "events.jsonl", "w", encoding="utf-8") as f:
        for event in events or []:
            row = _to_dict(event) if not isinstance(event, dict) else event
            f.write(json.dumps(walk(row), ensure_ascii=False, default=str) + "\n")
    return count


def _count(items: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it.status] = out.get(it.status, 0) + 1
    return out


if __name__ == "__main__":
    sys.exit(main())
