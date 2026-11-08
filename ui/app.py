"""The teacher's approval screen, served on http://127.0.0.1:8765.

Left: a dictated (typed or pasted) sentence goes through voice.structurer and comes back as
a proposal {student candidates, text}; the teacher approves, corrects or stops. Right: the
live queue (agent/queue_store.py) and the last journal lines, polled every 2 seconds. Each student
is shown with the illustrated avatar committed in static/avatars/<student_id>.svg (fictitious
faces, never photos; scripts/make_avatars.py), or with their initials when the file is missing.

Nothing enters the queue without a click (or Enter) on Approve, and an approved student must
be on the roster. After Approve, a short sourced suggestion (research/advice.py) may be shown under
the comment; it is appended only when the teacher clicks "Ajouter", and the queued text is the text
on screen. STOP creates the STOP file next to the queue file and drains pending items.

Usage:
    pip install -e ".[ui]"
    python -m ui.app                                   # data/roster.csv, runs/queue.jsonl
    python -m ui.app --roster data/roster_moodle.csv --course "Mindful Course Creation"
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.journal import read_journal
from agent.queue_store import DEFAULT_PATH, QueueStore
from research import advice
from research.preparation import Preparer
from ui import dictation, parallel, workspace
from voice.roster import DEFAULT_ROSTER, Student, load_roster
from voice.structurer import RuleBasedStructurer

STATIC = Path(__file__).resolve().parent / "static"
AVATARS = STATIC / "avatars"
# initials fallback: dark enough for white text (WCAG AA at 40 px)
AVATAR_COLORS = ("#1f5fbf", "#1e6b35", "#8a5a00", "#6b3fa0", "#b3261e", "#00707a", "#5c5c57")
HOST, PORT = "127.0.0.1", 8765
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
JOURNAL_LINES = 30


class StructureIn(BaseModel):
    text: str


class AdviceIn(BaseModel):
    text: str


class ApproveIn(BaseModel):
    student: str
    text: str
    course: str | None = None
    previous_value: str | None = None
    source: str = "ui"


def _hostname(host_header: str) -> str:
    return urlsplit(f"//{host_header}").hostname or ""


def initials(display_name: str) -> str:
    parts = display_name.split()
    return "".join(p[0] for p in (parts[:1] + parts[1:][-1:])).upper() or "?"


def avatar(student: Student, avatars_dir: Path = AVATARS) -> dict[str, Any]:
    """The committed illustrated avatar of a student, or None, plus the initials fallback (text and colour)."""
    has_file = (Path(avatars_dir) / f"{student.student_id}.svg").is_file()
    color = AVATAR_COLORS[sum(student.student_id.encode()) % len(AVATAR_COLORS)]
    return {"avatar": f"/static/avatars/{student.student_id}.svg" if has_file else None,
            "initials": initials(student.display_name), "color": color}


def latest_journal(runs_dir: Path) -> Path | None:
    journals = [p for p in Path(runs_dir).glob("*/journal.jsonl") if p.is_file()]
    return max(journals, key=lambda p: p.stat().st_mtime) if journals else None


def create_app(queue_path: Path = DEFAULT_PATH, roster_path: Path = DEFAULT_ROSTER, journal_path: Path | None = None,
               runs_dir: Path | None = None, course: str | None = None,
               allowed_hosts: Iterable[str] = LOOPBACK_HOSTS,
               advisor: Callable[[str], advice.Suggestion | None] | None = None, avatars_dir: Path = AVATARS,
               cases_dir: Path = workspace.DEFAULT_CASES, workspace_dir: Path | None = None,
               parallel_dir: Path | None = None,
               preparer: Preparer | None = None,
               stt_session_factory: Callable[[dict[str, Any]], Any] | None = None) -> FastAPI:
    store = QueueStore(queue_path)
    students: list[Student] = load_roster(Path(roster_path))
    by_id = {s.student_id: s for s in students}
    names = {s.display_name for s in students}
    structurer = RuleBasedStructurer(students)
    runs_dir = Path(runs_dir) if runs_dir else Path(queue_path).parent
    if advisor is None:
        cache = Path(queue_path).parent / advice.DEFAULT_CACHE.name
        name_forms = [n for s in students for n in s.name_forms()]

        def advisor(text: str) -> advice.Suggestion | None:
            return advice.suggest(text, cache_path=cache, names=name_forms)

    app = FastAPI(title="Calli (Calligraphe app)", docs_url=None, redoc_url=None)
    app.mount("/static/avatars", StaticFiles(directory=avatars_dir, check_dir=False), name="avatars")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    hosts = set(allowed_hosts)

    @app.middleware("http")
    async def local_page_only(request: Request, call_next: Any) -> Any:
        # no authentication: only this page may drive the queue. A foreign Host (DNS rebinding) or Origin is
        # refused, and a POST must be JSON, which another site cannot send without a CORS preflight.
        if _hostname(request.headers.get("host", "")) not in hosts:
            return JSONResponse({"detail": "unknown host"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in hosts:
            return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        if request.method == "POST" and \
                request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            return JSONResponse({"detail": "expected application/json"}, status_code=415)
        return await call_next(request)

    def journal_file() -> Path | None:
        return Path(journal_path) if journal_path else latest_journal(runs_dir)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {"course": course, "roster": [{"student_id": s.student_id, "display_name": s.display_name,
                                              **avatar(s, avatars_dir)} for s in students]}

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        jf = journal_file()
        lines = read_journal(jf)[-JOURNAL_LINES:] if jf else []
        return {"items": store.all(), "summary": store.summary(), "stopped": store.stop_requested(),
                "stop_mode": store.stop_reason(),
                "journal": lines, "journal_path": str(jf) if jf else None}

    @app.post("/api/structure")
    def structure(body: StructureIn) -> dict[str, Any]:
        out = []
        for c in structurer.structure(body.text):
            cands = [{"student_id": sid, "display_name": by_id[sid].display_name}
                     for sid in c.student_candidates if sid in by_id]
            out.append({"kind": c.kind, "text": c.text, "confidence": c.confidence, "candidates": cands,
                        "needs_choice": len(cands) != 1})
        return {"items": out}

    @app.post("/api/advice")
    def suggestion(body: AdviceIn) -> dict[str, Any]:
        # read-only: the queue is never touched here, the page appends the sentence only on "Ajouter"
        try:
            s = advisor(body.text) if body.text.strip() else None
        except Exception:
            s = None
        return {"suggestion": None if s is None else {"text": s.text, "source_name": s.source_name,
                                                      "source_url": s.source_url}}

    def queue_approved(student: str, text: str, source: str, item_course: str | None = None,
                       previous_value: str | None = None) -> dict[str, Any]:
        if store.stop_requested():
            raise HTTPException(409, "stopped: press Resume before approving")
        student, text = student.strip(), text.strip()
        if student not in names:
            raise HTTPException(422, f"{student!r} is not on the roster")
        if not text:
            raise HTTPException(422, "empty text")
        rec = store.append({"student": student, "text": text, "course": item_course or course,
                            "previous_value": previous_value, "source": source})
        return {"item": rec, "duplicate": bool(rec.pop("duplicate", False))}

    @app.post("/api/approve", status_code=201)
    def approve(body: ApproveIn) -> dict[str, Any]:
        return queue_approved(body.student, body.text, body.source, body.course, body.previous_value)

    @app.post("/api/stop")
    def stop() -> dict[str, Any]:
        drained = store.stop()
        return {"stopped": True, "drained": [it["item_id"] for it in drained]}

    @app.post("/api/resume")
    def resume() -> dict[str, Any]:
        store.resume()
        return {"stopped": False}

    def ws_origin_ok(headers: Any) -> bool:
        # same origin, port included: no CORS protects a WebSocket, so another local page must not open one
        host, origin = headers.get("host", ""), headers.get("origin")
        return (_hostname(host) in hosts and bool(origin) and urlsplit(origin).hostname in hosts
                and urlsplit(origin).netloc == host)

    policy = dictation.DictationPolicy(students, course, structurer, store,
                                       Path(workspace_dir) if workspace_dir else None)
    app.include_router(dictation.dictation_router(policy=policy, students=students, origin_ok=ws_origin_ok,
                                                  session_factory=stt_session_factory))
    app.include_router(workspace.workspace_router(
        students=students, course=course, static_dir=STATIC, avatar=lambda s: avatar(s, avatars_dir),
        queue_approved=lambda student, text, source, previous: queue_approved(student, text, source, None, previous),
        cases_dir=Path(cases_dir), workspace_dir=Path(workspace_dir) if workspace_dir else None, preparer=preparer,
        dictation_info=lambda: dictation.speech_availability(stt_session_factory)))
    mods = None
    if parallel_dir is not None:
        from calli_parallel import loader

        mods = loader.upstream(Path(parallel_dir))
    app.include_router(parallel.parallel_router(static_dir=STATIC, mods=mods))
    return app


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--queue", default=str(DEFAULT_PATH), help="live queue file shared with the writer loop")
    p.add_argument("--roster", default=str(DEFAULT_ROSTER), help="student_id, display_name, aliases")
    p.add_argument("--journal", default=None, help="journal to show (default: the latest runs/*/journal.jsonl)")
    p.add_argument("--runs-dir", default=None, help="where to look for journals (default: the queue's directory)")
    p.add_argument("--course", default=None, help="course or class stored with each approved item")
    p.add_argument("--workspace-dir", default=None,
                   help="state directory of the teacher workspace preparations (needed to prepare a case)")
    p.add_argument("--parallel-dir", default=None,
                   help="state directory of the vendored H Parallel outing/practice views (needs .[parallel])")
    p.add_argument("--cases-dir", default=str(workspace.DEFAULT_CASES), help="sourced case files (*.json)")
    p.add_argument("--host", default=HOST, choices=LOOPBACK_HOSTS,
                   help="loopback only: the screen has no authentication")
    p.add_argument("--port", type=int, default=PORT)
    args = p.parse_args(argv)

    import uvicorn

    app = create_app(Path(args.queue), Path(args.roster), Path(args.journal) if args.journal else None,
                     Path(args.runs_dir) if args.runs_dir else None, args.course,
                     cases_dir=Path(args.cases_dir), workspace_dir=Path(args.workspace_dir) if args.workspace_dir else None,
                     parallel_dir=Path(args.parallel_dir) if args.parallel_dir else None)
    print(f"[calligraphe] approval screen on http://{args.host}:{args.port} queue={args.queue} roster={args.roster}")
    print(f"[calligraphe] teacher workspace on http://{args.host}:{args.port}/workspace")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
