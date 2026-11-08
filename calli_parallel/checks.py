"""Semantic success checks on H Parallel results: terminal state, provenance, expected fields and hashes.

Each function returns the list of failed checks (empty = success). File existence alone never passes.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEVIN_SESSION = re.compile(r"(?:devin-)?[0-9a-f]{32}")
OUTING_TOOLS = ("search_museum_visit", "prepare_transport_and_calendar", "read_class_and_template",
                "wait_for_outing_results", "read_outing_evidence", "fill_administrative_dossier")
REPORT_TOOLS = ("get_evidence_catalog", "transcribe_audio", "search_resources", "validate_dossier")


def _succeeded(job: dict[str, Any], name: str) -> bool:
    return any(c.get("name") == name and c.get("status") == "succeeded" for c in job.get("tool_calls") or [])


def report_checks(job: dict[str, Any]) -> list[str]:
    """A report usable by live practice: a real H session ran the tools and the dossier passed validation."""
    failed = []
    if job.get("status") != "ready":
        failed.append(f"status is {job.get('status')!r}, not 'ready'")
    if job.get("mode") != "live":
        failed.append("mode is not live")
    if not job.get("session_id"):
        failed.append("no H session id")
    for name in REPORT_TOOLS:
        if not _succeeded(job, name):
            failed.append(f"H never completed {name}")
    dossier = job.get("dossier") or {}
    if not dossier.get("evidence"):
        failed.append("dossier has no checked evidence")
    if not (dossier.get("transcription") or {}).get("text"):
        failed.append("dossier has no Gladia transcription")
    if not any(s.get("type") == "external" for s in dossier.get("sources") or []):
        failed.append("dossier has no Linkup source")
    return failed


def practice_checks(state: dict[str, Any], folder: Path) -> list[str]:
    """Live practice: a Devin session, its reported tests and the downloaded file whose hash matches."""
    failed = []
    if state.get("status") != "ready":
        failed.append(f"status is {state.get('status')!r}, not 'ready'")
    if state.get("mode") != "live" or state.get("simulated") is not False:
        failed.append("not a live (non-simulated) generation")
    if not DEVIN_SESSION.fullmatch(str(state.get("session_id") or "")):
        failed.append("no valid Devin session id")
    validation = state.get("validation") or {}
    for key in ("html_structure_checked", "provider_tests_reported", "teacher_review_required"):
        if validation.get(key) is not True:
            failed.append(f"validation.{key} is not true")
    name = str(state.get("artifact_file") or "")
    path = Path(folder) / name
    if name != "activity-live.html" or not path.is_file() or path.is_symlink():
        failed.append("activity-live.html is missing")
    elif hashlib.sha256(path.read_bytes()).hexdigest() != state.get("artifact_sha256"):
        failed.append("activity file hash does not match the recorded sha256")
    return failed


def outing_checks(job: dict[str, Any], domain: str) -> list[str]:
    """Outing prepared by Holo4: every tool succeeded, official-site evidence, route, dossier and H summary."""
    failed = []
    if job.get("status") != "ready":
        failed.append(f"status is {job.get('status')!r}, not 'ready'")
    if job.get("h_outcome"):
        failed.append(f"Holo4 session ended by {job['h_outcome']}: {job.get('h_error', '')}")
    if not job.get("session_id"):
        failed.append("no H session id")
    if (job.get("agent") or {}).get("computer_use_verified") is not True:
        failed.append("computer use not verified")
    if (job.get("browser_evidence") or {}).get("verified") is not True:
        failed.append("no verified workstation screenshot of the official site")
    for name in OUTING_TOOLS:
        if not _succeeded(job, name):
            failed.append(f"Holo4 never completed {name}")
    executions = job.get("executions") or []
    if sorted(e.get("tool_name") for e in executions if e.get("status") == "succeeded") != sorted(OUTING_TOOLS[:3]):
        failed.append("the three collection executions did not all succeed")
    sources = (job.get("visit") or {}).get("sources") or []
    hosts = [(urlsplit(s.get("url", "")).hostname or "").lower() for s in sources]
    if not hosts or not all(h == domain or h.endswith("." + domain) for h in hosts):
        failed.append("visit facts lack official-site sources")
    route = job.get("route") or {}
    if route.get("provider") != "OSRM" or not route.get("distance_km"):
        failed.append("no OSRM route")
    if not job.get("dossier") or not job.get("budget"):
        failed.append("no administrative dossier or budget")
    if not job.get("h_summary"):
        failed.append("no Holo4 summary")
    return failed
