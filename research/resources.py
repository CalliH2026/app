"""Optional `search_resources` tool for the read-only preparer: one Linkup search per preparation.

The model may only pick a topic ID from TOPICS; the query sent to Linkup is the fixed, generic text below, never
pupil text, names or model-written words. Only sources Linkup actually returned are kept, each with its URL as
provenance; the model can refer to them by ID and cannot supply a URL. A link is a reading suggestion for the
teacher, not evidence of educational efficacy, and is kept apart from the frozen-case quotes.

Environment: LINKUP_API_KEY (never printed); without it the tool answers "unavailable" and nothing is faked.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

_ASK = ("Trouve des ressources pour enseignants de français au collège en France sur ce thème : {}. "
        "Donne pour chaque ressource son titre et l'URL directe de la page source, de préférence publiée par une "
        "institution éducative (Eduscol, académie, Réseau Canopé) ou par son auteur d'origine.")
TOPICS: dict[str, dict[str, str]] = {
    "paragraph_structure": {"label": "Structurer un texte en paragraphes",
                            "query": _ASK.format("apprendre aux élèves à structurer un récit en paragraphes")},
    "support_idea": {"label": "Développer et justifier une idée",
                     "query": _ASK.format("aider les élèves à développer et justifier une idée à l'écrit")},
    "oral_participation": {"label": "Encourager la prise de parole",
                           "query": _ASK.format("encourager la prise de parole des élèves en classe")},
}
MAX_SOURCES = 3
SEARCH_TIMEOUT_S = 20.0  # bounds the single preparation worker's wait on Linkup

Searcher = Callable[[str], list[dict[str, str]]]


def _field(obj: Any, name: str) -> str:
    value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
    return str(value or "").strip()


def linkup_searcher(client: Any) -> Searcher:
    def search(query: str) -> list[dict[str, str]]:
        response = client.search(query=query, depth="standard", output_type="searchResults",
                                 timeout=SEARCH_TIMEOUT_S)
        results = response.get("results") if isinstance(response, dict) else getattr(response, "results", None)
        return [{"title": _field(r, "name"), "url": _field(r, "url")} for r in (results or [])]
    return search


def searcher_from_env() -> Searcher | None:
    if not os.environ.get("LINKUP_API_KEY"):
        return None
    from research.advice import default_client

    return linkup_searcher(default_client())


def _valid(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    kept = []
    for s in sources:
        url = (s.get("url") or "").strip()
        parts = urlsplit(url)
        if parts.scheme in ("http", "https") and parts.hostname and len(kept) < MAX_SOURCES:
            kept.append({"id": f"r{len(kept) + 1}", "title": (s.get("title") or "").strip()[:200] or parts.hostname,
                         "url": url, "host": parts.hostname})
    return kept


class ResourceSearch:
    """Per-preparation tool state. `record(kind, text)` writes a real timeline event."""

    def __init__(self, searcher: Searcher | None, record: Callable[[str, str], None],
                 case_read: Callable[[], bool]):
        self.searcher, self.record, self.case_read = searcher, record, case_read
        self.result: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def __call__(self, topic_id: str) -> str:
        if not self.case_read():
            raise ValueError("Appelle d'abord read_case.")
        if topic_id not in TOPICS:
            raise ValueError(f"Sujet inconnu. Choisis parmi : {', '.join(TOPICS)}.")
        with self._lock:
            if self.result is not None:
                return json.dumps(self.result, ensure_ascii=False)
            self.record("model_tool", f"H a demandé une ressource (search_resources : {topic_id}).")
            base = {"topic_id": topic_id, "label": TOPICS[topic_id]["label"], "sources": []}
            if self.searcher is None:
                self.result = {**base, "status": "unavailable"}
                self.record("app_api", "Recherche Linkup indisponible (LINKUP_API_KEY absent).")
                return json.dumps(self.result, ensure_ascii=False)
            started = time.monotonic()
            try:
                sources = _valid(self.searcher(TOPICS[topic_id]["query"]))
            except Exception as exc:
                self.result = {**base, "status": "failed", "error": type(exc).__name__,
                               "elapsed_s": round(time.monotonic() - started, 1)}
                self.record("app_api", f"Recherche Linkup en échec ({type(exc).__name__}).")
                return json.dumps(self.result, ensure_ascii=False)
            self.result = {**base, "status": "ok", "sources": sources,
                           "elapsed_s": round(time.monotonic() - started, 1)}
            self.record("app_api", f"Linkup : {len(sources)} source(s) en {self.result['elapsed_s']} s.")
            return json.dumps(self.result, ensure_ascii=False)

    def tool(self) -> Callable[[str], str]:
        def search_resources(topic_id: str) -> str:
            return self(topic_id)
        search_resources.__doc__ = (
            "Facultatif, après read_case, une seule fois, seulement si le dossier montre un besoin pédagogique : "
            "chercher une ressource publique pour le professeur. topic_id parmi "
            + "; ".join(f"{k} ({v['label']})" for k, v in TOPICS.items())
            + ". Aucun nom ni texte d'élève n'est envoyé. Renvoie des sources avec id, titre et URL.")
        return search_resources

    def chosen(self, ids: Any) -> dict[str, Any] | None:
        """The recorded search with only the sources the model referred to by a returned ID."""
        if self.result is None:
            return None
        wanted = {str(i) for i in ids} if isinstance(ids, list) else set()
        return {**self.result, "sources": [s for s in self.result["sources"] if s["id"] in wanted]}
