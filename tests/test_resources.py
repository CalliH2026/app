"""Optional search_resources tool of the read-only preparer (research/resources.py), offline.

Linkup is replaced by a recording fake searcher (test double only); the topic catalog, budget, URL filtering and
PreparationStore integration are real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research import dossier, resources
from research.preparation import PreparationStore
from voice.roster import load_roster

ROOT = Path(__file__).resolve().parents[1]
COURSE = "3A, FRANCAIS, Trimestre 1"
ROSTER = load_roster(ROOT / "data" / "roster.csv")


class FakeLinkup:
    def __init__(self, error: Exception | None = None):
        self.queries, self.error = [], error

    def __call__(self, query):
        self.queries.append(query)
        if self.error:
            raise self.error
        return [{"title": "Écrire en paragraphes", "url": "https://example.org/paragraphes"},
                {"title": "Lien piégé", "url": "javascript:alert(1)"},
                {"title": "", "url": "https://eduscol.example/fiche"}]


def _tool(searcher, read=True):
    events = []
    return resources.ResourceSearch(searcher, lambda k, t: events.append((k, t)), lambda: read), events


def test_only_catalog_topics_reach_linkup_and_only_returned_http_sources_are_kept():
    fake = FakeLinkup()
    tool, events = _tool(fake)
    with pytest.raises(ValueError):
        tool("Lucas Bernard ne fait pas de paragraphes")
    out = json.loads(tool("paragraph_structure"))
    assert fake.queries == [resources.TOPICS["paragraph_structure"]["query"]]
    assert [s["url"] for s in out["sources"]] == ["https://example.org/paragraphes", "https://eduscol.example/fiche"]
    assert out["sources"][1]["title"] == "eduscol.example" and out["status"] == "ok"
    assert [k for k, _ in events] == ["model_tool", "app_api"]


def test_one_search_per_preparation_repeats_return_the_recorded_result():
    fake = FakeLinkup()
    tool, _ = _tool(fake)
    first = tool("paragraph_structure")
    assert tool("oral_participation") == first and len(fake.queries) == 1


def test_read_case_first_and_unavailable_or_failed_are_explicit_without_retry():
    with pytest.raises(ValueError):
        _tool(FakeLinkup(), read=False)[0]("paragraph_structure")
    tool, _ = _tool(None)
    assert json.loads(tool("support_idea"))["status"] == "unavailable"
    failing = FakeLinkup(error=RuntimeError("boom"))
    tool, _ = _tool(failing)
    assert json.loads(tool("support_idea"))["status"] == "failed"
    assert json.loads(tool("support_idea"))["sources"] == [] and len(failing.queries) == 1


def test_model_cannot_supply_a_url_only_returned_ids_are_rendered():
    tool, _ = _tool(FakeLinkup())
    tool("paragraph_structure")
    chosen = tool.chosen(["r2", "r9", "https://evil.example"])
    assert [s["url"] for s in chosen["sources"]] == ["https://eduscol.example/fiche"]


class SearchingPreparer:
    supports_search = True

    def __call__(self, frozen, read_case, search_resources):
        case = json.loads(read_case())
        search_resources("paragraph_structure")
        qid = next(iter(case["quote_catalog"]))
        return {"summary": "Récit vivant.", "evidence": [{"claim": "Consigne.", "quote_id": qid}],
                "unknowns": [], "suggestions": [], "resource_ids": ["r1"],
                "url": "https://invented.example"}


def test_store_records_search_provenance_separately_from_case_quotes(tmp_path):
    case = dossier.load_cases(ROOT / "data" / "dossiers", ROSTER, COURSE)["s01-francais-t1"]
    fake = FakeLinkup()
    store = PreparationStore(tmp_path, SearchingPreparer(), searcher=fake)
    job = store.wait(store.prepare(case)["id"], 5)
    assert job["status"] == "ready"
    res = job["preparation"]["resources"]
    assert [s["url"] for s in res["sources"]] == ["https://example.org/paragraphes"]
    assert all(e["quote_id"].startswith("q") for e in job["preparation"]["evidence"])
    assert "invented" not in json.dumps(job)
    texts = [e["text"] for e in job["events"] if e["kind"] == "app_api"]
    assert any("Linkup" in t for t in texts)
    assert not any(name in q for q in fake.queries for name in ("Lucas", "Bernard"))


def test_linkup_call_is_bounded_by_an_explicit_timeout():
    class Client:
        kwargs = None

        def search(self, **kwargs):
            Client.kwargs = kwargs
            return {"results": [{"name": "Fiche", "url": "https://eduscol.example/f"}]}

    out = resources.linkup_searcher(Client())(resources.TOPICS["support_idea"]["query"])
    assert out == [{"title": "Fiche", "url": "https://eduscol.example/f"}]
    assert 0 < Client.kwargs["timeout"] <= 30


def test_catalog_queries_are_retrieval_instructions_without_pupil_context():
    names = {n for r in ROSTER for n in r.display_name.split()}
    for topic in resources.TOPICS.values():
        q = topic["query"]
        assert "collège" in q and "titre" in q and "URL directe" in q
        assert not any(n in q for n in names | {"Lucas", "Bernard", "s01"})


def test_cached_v2_preparation_is_not_presented_as_the_current_flow(tmp_path, monkeypatch):
    case = dossier.load_cases(ROOT / "data" / "dossiers", ROSTER, COURSE)["s01-francais-t1"]
    store = PreparationStore(tmp_path, SearchingPreparer(), searcher=FakeLinkup())
    monkeypatch.setattr(dossier, "PREPARATION_VERSION", "parallel-v2")
    monkeypatch.setattr(dossier.case_hash, "__defaults__", ("parallel-v2",))
    old = store.wait(store.prepare(case)["id"], 5)
    monkeypatch.undo()
    assert dossier.PREPARATION_VERSION == "parallel-v3"
    assert store.view(old["id"], case)["status"] == "stale"
    assert store.latest(case) is None
    assert store.prepare(case)["id"] != old["id"]
