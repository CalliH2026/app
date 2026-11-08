"""Sourced case files for the teacher workspace, and the citation check on a preparation.

A case is a small JSON file in data/dossiers/: one pupil of the roster, one course, a question and a
few documents (instructions, rubric, pupil work, teacher notes). The committed case is an authored
demo (`source_kind="authored_demo"`): fictitious work written for the demo, not imported from PRONOTE
and not a measured result.

Citations follow the pattern of Francois Amat's H Parallel (Fran-cois/H-Hack-nov26 at 160dd5e,
mvp/engine.py `quote_candidates`, `quote_catalog`, `checked_answer`): each document is split into
short literal excerpts with a deterministic ID (q001, q002, ...). The model only picks IDs; the
program supplies the literal excerpt and its document. A passing check means the citation is
mechanically valid (the excerpt exists word for word in the named document), not that the claim
built on it is pedagogically right: the teacher judges that.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.queue import normalize

PREPARATION_VERSION = "parallel-v3"  # v3: optional search_resources and resource_ids in the answer
SOURCE_KINDS = frozenset({"authored_demo"})
ROLES = frozenset({"instructions", "rubric", "pupil_work", "teacher_notes"})
MAX_QUOTE = 180
MAX_QUOTES_PER_DOCUMENT = 12
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_SPLIT = re.compile(r"(?<=[.;!?])\s+")


class CitationError(ValueError):
    """A preparation whose evidence does not resolve to the case's own excerpts."""


@dataclass(frozen=True)
class Document:
    id: str
    role: str
    title: str
    text: str


@dataclass(frozen=True)
class Case:
    case_id: str
    student_id: str
    student_name: str
    course: str
    source_kind: str
    title: str
    provenance: str
    question: str
    documents: tuple[Document, ...]


def _text(data: dict, key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {key} is missing or empty")
    return value.strip()


def parse_case(data: dict, roster: Iterable[Any], course: str, where: str = "case") -> Case:
    """Validate a case against the actual roster and course; never infer identity from free text."""
    names = {s.student_id: s.display_name for s in roster}
    case_id = _text(data, "case_id", where)
    if not _ID.match(case_id):
        raise ValueError(f"{where}: case_id {case_id!r} is not a simple identifier")
    student_id = _text(data, "student_id", where)
    if student_id not in names:
        raise ValueError(f"{where}: student_id {student_id!r} is not on the roster")
    student_name = _text(data, "student_name", where)
    if student_name != names[student_id]:
        raise ValueError(f"{where}: student_name {student_name!r} does not match roster name {names[student_id]!r}")
    if _text(data, "course", where) != course:
        raise ValueError(f"{where}: course {data.get('course')!r} is not the served course {course!r}")
    kind = _text(data, "source_kind", where)
    if kind not in SOURCE_KINDS:
        raise ValueError(f"{where}: source_kind {kind!r} is not one of {sorted(SOURCE_KINDS)}")
    raw_docs = data.get("documents")
    if not isinstance(raw_docs, list) or not raw_docs:
        raise ValueError(f"{where}: documents must be a non-empty list")
    docs: list[Document] = []
    for i, d in enumerate(raw_docs):
        if not isinstance(d, dict):
            raise ValueError(  # noqa: TRY004 - a malformed case file is a value error for the caller
                f"{where}: documents[{i}] is not an object")
        doc_id = _text(d, "id", f"{where} documents[{i}]")
        if not _ID.match(doc_id):
            raise ValueError(f"{where}: document id {doc_id!r} is not a simple identifier")
        if any(x.id == doc_id for x in docs):
            raise ValueError(f"{where}: duplicate document id {doc_id!r}")
        role = _text(d, "role", f"{where} documents[{i}]")
        if role not in ROLES:
            raise ValueError(f"{where}: document role {role!r} is not one of {sorted(ROLES)}")
        docs.append(Document(doc_id, role, _text(d, "title", f"{where} documents[{i}]"),
                             _text(d, "text", f"{where} documents[{i}]")))
    return Case(case_id=case_id, student_id=student_id, student_name=student_name, course=course,
                source_kind=kind, title=_text(data, "title", where),
                provenance=str(data.get("provenance") or "").strip(),
                question=_text(data, "question", where), documents=tuple(docs))


def load_cases(directory: Path, roster: Iterable[Any], course: str) -> dict[str, Case]:
    """Every *.json case in `directory`, validated; a bad file raises rather than being skipped."""
    roster = list(roster)
    cases: dict[str, Case] = {}
    if not directory.is_dir():
        return cases
    for path in sorted(directory.glob("*.json")):
        case = parse_case(json.loads(path.read_text(encoding="utf-8")), roster, course, where=path.name)
        if case.case_id in cases:
            raise ValueError(f"{path.name}: duplicate case_id {case.case_id!r}")
        cases[case.case_id] = case
    return cases


def quote_candidates(documents: Iterable[Document]) -> dict[str, list[str]]:
    """Short literal excerpts of each document (adapted from H Parallel `quote_candidates`)."""
    out: dict[str, list[str]] = {}
    for doc in documents:
        quotes: list[str] = []
        for part in _SPLIT.split(doc.text):
            quote = part.strip()
            if len(quote) > MAX_QUOTE:
                quote = quote[:MAX_QUOTE].rsplit(" ", 1)[0]
            if quote and quote not in quotes:
                quotes.append(quote)
        out[doc.id] = quotes[:MAX_QUOTES_PER_DOCUMENT]
    return out


def quote_catalog(documents: Iterable[Document]) -> dict[str, dict[str, str]]:
    """Deterministic ID -> {document_id, quote} (adapted from H Parallel `quote_catalog`)."""
    catalog: dict[str, dict[str, str]] = {}
    for doc_id, quotes in quote_candidates(documents).items():
        for quote in quotes:
            catalog[f"q{len(catalog) + 1:03}"] = {"document_id": doc_id, "quote": quote}
    return catalog


def snapshot(case: Case, version: str = PREPARATION_VERSION) -> dict[str, Any]:
    """The frozen case a preparation reads: identity, course, question and documents with their hashes."""
    return {
        "preparation_version": version,
        "case_id": case.case_id, "student_id": case.student_id, "student_name": case.student_name,
        "course": case.course, "source_kind": case.source_kind, "title": case.title, "question": case.question,
        "documents": [{"id": d.id, "role": d.role, "title": d.title, "text": d.text,
                       "sha256": hashlib.sha256(d.text.encode("utf-8")).hexdigest()} for d in case.documents],
    }


def case_hash(case: Case, version: str = PREPARATION_VERSION) -> str:
    """SHA-256 of the canonical snapshot (adapted from H Parallel `native_pipeline.fingerprint`)."""
    canon = json.dumps(snapshot(case, version), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _strings(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise CitationError(f"{key} must be a list of strings")
    return [x.strip() for x in value if x.strip()]


def check_preparation(answer: Any, case: Case) -> dict[str, Any]:
    """Resolve the model's quote IDs to literal excerpts; raise CitationError on any unresolvable piece."""
    if hasattr(answer, "model_dump"):
        answer = answer.model_dump()
    if not isinstance(answer, dict):
        raise CitationError("the answer is not an object")
    summary = answer.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise CitationError("summary is missing or empty")
    raw = answer.get("evidence")
    if not isinstance(raw, list) or not raw:
        raise CitationError("evidence is missing or empty: every preparation must cite the case")
    catalog = quote_catalog(case.documents)
    titles = {d.id: d.title for d in case.documents}
    evidence = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise CitationError(f"evidence[{i}] is not an object")
        claim = item.get("claim")
        if not isinstance(claim, str) or not claim.strip():
            raise CitationError(f"evidence[{i}]: claim is missing or empty")
        qid = item.get("quote_id")
        if not isinstance(qid, str) or not qid.strip():
            raise CitationError(f"evidence[{i}]: quote_id is missing")
        entry = catalog.get(qid.strip())
        if entry is None:
            raise CitationError(f"evidence[{i}]: unknown quote_id {qid.strip()!r}")
        evidence.append({"claim": normalize(claim), "quote_id": qid.strip(), "quote": entry["quote"],
                         "document_id": entry["document_id"], "document_title": titles[entry["document_id"]]})
    return {"summary": summary.strip(), "evidence": evidence,
            "unknowns": _strings(answer.get("unknowns"), "unknowns"),
            "suggestions": _strings(answer.get("suggestions"), "suggestions"),
            "citation_check": "mechanical"}
