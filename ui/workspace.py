"""Teacher workspace routes: sourced cases, background preparation by H, approval bound to a roster ID.

Served by ui/app.py under /workspace and /api/workspace/*, behind the same loopback host, origin and
JSON guards as the approval page. GET routes only read files: they never start a preparation or call
a paid API. A preparation never adds a writer queue item; only POST /api/workspace/approve queues the
exact text the teacher approved, through the same approval logic as POST /api/approve.

Identity and course always come from the server (roster and case files), never from a path or free
text in the request. Responses carry no absolute paths, tokens or raw provider errors.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from research import dossier
from research.preparation import PreparationStore, Preparer, Unavailable, preparer_from_env
from voice.roster import Student

MAX_PRONOTE_CHARS = 255  # PRONOTE appreciation field; a longer text is refused, never truncated
DEFAULT_CASES = Path(__file__).resolve().parents[1] / "data" / "dossiers"
PUBLIC_JOB_FIELDS = ("id", "case_id", "case_hash", "student_id", "student_name", "course", "preparation_version",
                     "status", "created_at", "updated_at", "read_case_called", "provider_session_id",
                     "provider_status", "provider_runtime", "elapsed_s", "events", "error", "preparation", "trigger")


class ObservationIn(BaseModel):
    """A browser-sent app event: the page reports that the teacher opened a source in Calli. Not OS-level proof."""
    event_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    event_type: Literal["document_opened"]
    source_kind: Literal["calli_workspace"]
    student_id: str = Field(max_length=40)
    course: str = Field(max_length=200)
    case_id: str = Field(max_length=100)
    document_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
    case_hash: str = Field(max_length=100)
    observed_at: str = Field(max_length=60)


class ObservationModeIn(BaseModel):
    paused: bool


class PrepareIn(BaseModel):
    retry: bool = False


class WorkspaceApproveIn(BaseModel):
    student_id: str
    student_name: str
    text: str
    course: str | None = None
    previous_value: str | None = None
    confirm_replace: bool = False


def public_job(job: dict | None) -> dict | None:
    return None if job is None else {k: job[k] for k in PUBLIC_JOB_FIELDS if k in job}


def case_json(case: dossier.Case) -> dict[str, Any]:
    return {"case_id": case.case_id, "student_id": case.student_id, "student_name": case.student_name,
            "course": case.course, "source_kind": case.source_kind, "title": case.title,
            "provenance": case.provenance, "question": case.question, "case_hash": dossier.case_hash(case),
            "documents": [{"id": d.id, "role": d.role, "title": d.title, "text": d.text} for d in case.documents]}


def workspace_router(*, students: list[Student], course: str | None, static_dir: Path,
                     queue_approved: Callable[[str, str, str, str | None], dict[str, Any]],
                     avatar: Callable[[Student], dict[str, Any]], cases_dir: Path = DEFAULT_CASES,
                     workspace_dir: Path | None = None, preparer: Preparer | None = None,
                     dictation_info: Callable[[], dict[str, Any]] | None = None) -> APIRouter:
    router = APIRouter()
    by_id = {s.student_id: s for s in students}
    if workspace_dir is None:
        store = PreparationStore.disabled("Répertoire d'état non configuré : relancez avec --workspace-dir.")
    else:
        reason = ""
        if preparer is None:
            preparer, reason = preparer_from_env()
        store = PreparationStore(Path(workspace_dir), preparer, unavailable_reason=reason)

    def cases() -> tuple[dict[str, dossier.Case], str | None]:
        if not course:
            return {}, "Aucun cours configuré : relancez avec --course."
        try:
            return dossier.load_cases(Path(cases_dir), students, course), None
        except (OSError, ValueError) as exc:
            return {}, f"Dossier invalide : {exc}"

    def one_case(case_id: str) -> dossier.Case:
        case = cases()[0].get(case_id)
        if case is None:
            raise HTTPException(404, "unknown case")
        return case

    @router.get("/workspace", include_in_schema=False)
    def page() -> FileResponse:
        return FileResponse(static_dir / "workspace.html")

    @router.get("/api/workspace/cases")
    def list_cases() -> dict[str, Any]:
        found, error = cases()
        by_student = {c.student_id: c.case_id for c in found.values()}
        return {"course": course, "cases_error": error,
                "dictation": dictation_info() if dictation_info else {"available": False, "reason": "dictée non configurée"},
                "preparer": {"available": store.available, "reason": None if store.available else store.unavailable_reason},
                "observation": {"paused": obs["paused"], "surface": "calli_workspace"},
                "roster": [{"student_id": s.student_id, "display_name": s.display_name,
                            "case_id": by_student.get(s.student_id), **avatar(s)} for s in students],
                "cases": [{k: v for k, v in case_json(c).items() if k != "documents"} for c in found.values()]}

    @router.get("/api/workspace/cases/{case_id}")
    def get_case(case_id: str) -> dict[str, Any]:
        case = one_case(case_id)
        return {"case": case_json(case), "preparation": public_job(store.latest(case))}

    @router.post("/api/workspace/cases/{case_id}/prepare", status_code=202)
    def prepare(case_id: str, body: PrepareIn) -> dict[str, Any]:
        case = one_case(case_id)
        try:
            job = store.prepare(case, retry=body.retry)
        except Unavailable as exc:
            raise HTTPException(503, str(exc)) from None
        return {"preparation": public_job(job)}

    obs_path = Path(workspace_dir) / "observations.json" if workspace_dir else None
    obs_lock = threading.Lock()
    obs = json.loads(obs_path.read_text(encoding="utf-8")) if obs_path and obs_path.exists() \
        else {"paused": False, "events": {}}

    def obs_save() -> None:
        if obs_path:
            obs_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = obs_path.with_name(obs_path.name + ".tmp")
            tmp.write_text(json.dumps(obs, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, obs_path)

    @router.post("/api/workspace/observation")
    def observation_mode(body: ObservationModeIn) -> dict[str, Any]:
        with obs_lock:
            obs["paused"] = body.paused
            obs_save()
        return {"paused": body.paused}

    @router.post("/api/workspace/observations", status_code=202)
    def observe(body: ObservationIn) -> dict[str, Any]:
        sent = body.model_dump()
        case = one_case(body.case_id)
        if body.student_id != case.student_id or body.course != course:
            raise HTTPException(409, "the pupil or course changed: event refused")
        if body.case_hash != dossier.case_hash(case):
            raise HTTPException(409, "the case changed since it was displayed: event refused")
        if body.document_id not in {d.id for d in case.documents}:
            raise HTTPException(422, "unknown document for this case")
        with obs_lock:
            done = obs["events"].get(body.event_id)
            if done is not None:
                if any(done.get(k) != v for k, v in sent.items()):
                    raise HTTPException(409, "event id already used for another event")
                job = store.view(done["preparation_id"], case) if done.get("preparation_id") else None
                return {"observation": dict(done, duplicate=True), "preparation": public_job(job)}
            record = {**sent, "origin": "app_event", "received_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                      "preparation_id": None}
            job = None
            if obs["paused"]:
                record["outcome"] = "paused"
            else:
                previous = store.latest(case)
                try:
                    job = store.prepare(case, trigger={k: record[k] for k in (
                        "event_id", "event_type", "source_kind", "origin", "document_id", "observed_at")})
                except Unavailable:
                    record["outcome"] = "unavailable"
                else:
                    record["preparation_id"] = job["id"]
                    record["outcome"] = ("preparation_started" if previous is None or previous["id"] != job["id"]
                                         else "already_failed" if job["status"] == "failed" else "already_prepared")
            obs["events"][body.event_id] = record
            obs_save()
        return {"observation": dict(record, duplicate=False), "preparation": public_job(job)}

    @router.get("/api/workspace/preparations/{prep_id}")
    def get_preparation(prep_id: str) -> dict[str, Any]:
        job = store.get(prep_id)
        if job is None:
            raise HTTPException(404, "unknown preparation")
        return {"preparation": public_job(store.view(prep_id, cases()[0].get(job["case_id"])))}

    @router.post("/api/workspace/approve", status_code=201)
    def approve(body: WorkspaceApproveIn) -> dict[str, Any]:
        student = by_id.get(body.student_id.strip())
        if student is None:
            raise HTTPException(422, f"{body.student_id!r} is not on the roster")
        if body.student_name.strip() != student.display_name:
            raise HTTPException(409, "the selected pupil changed: reselect the pupil before approving")
        if not course:
            raise HTTPException(409, "no course configured: start the server with --course 'CLASS, SUBJECT, PERIOD'")
        if body.course is not None and body.course != course:
            raise HTTPException(409, "the class, subject or period changed: reload the workspace before approving")
        n = len(body.text.strip())
        if n > MAX_PRONOTE_CHARS:
            raise HTTPException(422, f"text is {n} characters, PRONOTE accepts {MAX_PRONOTE_CHARS}: shorten it, "
                                     "nothing is truncated")
        previous = (body.previous_value or "").strip() or None
        if previous and not body.confirm_replace:
            raise HTTPException(409, "replacing an existing appreciation needs its own confirmation")
        return queue_approved(student.display_name, body.text, "workspace", previous)

    return router
