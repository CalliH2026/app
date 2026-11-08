"""Secondary Calli views over Francois Amat's vendored H Parallel: school outing and Pythagore practice.

Routes are namespaced under /api/parallel and only exist when a state directory is configured; the pages are
always served and say when the capability is off. Upstream logic (validation, citations, tool logs, the
simulation/live split, teacher review before download) runs unchanged; this module only maps HTTP to it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

PREVIEW_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
               "img-src data:; connect-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; "
               "form-action 'none'; frame-ancestors 'self'")
DOWNLOAD_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                "img-src data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")


class OutingRequest(BaseModel):
    model_config = {"extra": "forbid"}
    class_id: str = Field(default="4e-b", max_length=32)
    destination_id: str = Field(default="orsay", max_length=32)
    date: str = Field(max_length=10)
    visit_time: str = Field(default="10:00", max_length=5)
    duration_minutes: int = Field(default=120, ge=30, le=360)
    adults: int = Field(default=2, ge=1, le=10)
    transport_total: str = Field(default="180.00", max_length=16)
    subsidy: str = Field(default="0.00", max_length=16)
    objective: str = Field(default="", max_length=3000)
    mode: Literal["live"] = "live"


class PracticeRequest(BaseModel):
    model_config = {"extra": "forbid"}
    mode: Literal["simulation", "live"] = "simulation"
    retry: bool = False


def _call(action: Any, *args: Any, missing: str, **kwargs: Any) -> Any:
    try:
        return action(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, missing) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None


def nothing_prepared(job: dict[str, Any]) -> bool:
    """A finished outing where every collection failed and no tool call or collection succeeded.

    Display-only, for jobs saved before h_outcome existed: it names no cause (timeout, cancel) the job does not record.
    """
    if job.get("status") in (None, "preparing"):
        return False
    collections = [t for t in job.get("tasks") or [] if t.get("id") != "dossier"]
    succeeded = any(item.get("status") == "succeeded" for key in ("tool_calls", "executions") for item in job.get(key) or [])
    return bool(collections) and all(t.get("status") == "failed" for t in collections) and not succeeded


def _outing_view(job: dict[str, Any]) -> dict[str, Any]:
    return {**job, "calli_view": {"nothing_prepared": nothing_prepared(job)}}


def _no_store(value: Any) -> Response:
    return Response(json.dumps(value, ensure_ascii=False), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


def parallel_router(*, static_dir: Path, mods: Any | None) -> APIRouter:
    router = APIRouter()

    @router.get("/sortie", include_in_schema=False)
    def outing_page() -> FileResponse:
        return FileResponse(static_dir / "sortie.html")

    @router.get("/entrainement", include_in_schema=False)
    def practice_page() -> FileResponse:
        return FileResponse(static_dir / "entrainement.html")

    @router.get("/api/parallel/config")
    def config() -> dict[str, Any]:
        return {"enabled": mods is not None}

    if mods is None:
        return router
    outings, practice = mods.outings, mods.practice

    @router.get("/api/parallel/outings/options")
    def outing_options() -> dict[str, Any]:
        return outings.options()

    @router.post("/api/parallel/outings")
    def outing_start(body: OutingRequest) -> Any:
        return _outing_view(_call(outings.start, body.model_dump(), missing="Sortie introuvable."))

    @router.get("/api/parallel/outings/{outing_id}")
    def outing_get(outing_id: str) -> Response:
        try:
            return _no_store(_outing_view(outings.get(outing_id)))
        except (KeyError, ValueError):
            raise HTTPException(404, "Sortie introuvable.") from None

    def with_artifact(job_id: str, value: dict[str, Any]) -> dict[str, Any]:
        # The page reloads its preview frame when this hash (or the job or mode) changes.
        if value.get("status") == "ready":
            value["artifact_sha256"] = (practice._load(job_id) or {}).get("artifact_sha256")
        return value

    @router.get("/api/parallel/practice/{job_id}")
    def practice_get(job_id: str) -> Response:
        return _no_store(with_artifact(job_id, _call(practice.get, job_id, missing="Rapport ou entraînement introuvable.")))

    @router.post("/api/parallel/practice/{job_id}")
    def practice_start(job_id: str, body: PracticeRequest) -> Any:
        return with_artifact(job_id, _call(practice.start, job_id, retry=body.retry, mode=body.mode,
                                           missing="Rapport ou entraînement introuvable."))

    @router.post("/api/parallel/practice/{job_id}/approve")
    def practice_approve(job_id: str) -> Any:
        return _call(practice.approve, job_id, missing="Rapport ou entraînement introuvable.")

    @router.get("/api/parallel/practice/{job_id}/preview")
    def practice_preview(job_id: str) -> FileResponse:
        path = _call(practice.artifact_path, job_id, missing="Rapport ou entraînement introuvable.")
        return FileResponse(path, media_type="text/html", headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
            "Content-Security-Policy": PREVIEW_CSP})

    @router.get("/api/parallel/practice/{job_id}/download")
    def practice_download(job_id: str) -> FileResponse:
        path = _call(practice.artifact_path, job_id, download=True, missing="Rapport ou entraînement introuvable.")
        return FileResponse(path, media_type="text/html", filename="entrainement-pythagore.html", headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": DOWNLOAD_CSP})

    return router
