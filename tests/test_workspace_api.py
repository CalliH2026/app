"""Teacher workspace API (ui/workspace.py through ui/app.create_app), offline.

The paid provider is replaced by an injected fake preparer (test double only). Everything else is real:
the case files, the preparation store and its thread, the QueueStore, the host/origin/JSON guards.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from agent.queue_store import QueueStore
from research import dossier
from ui.app import create_app

ROOT = Path(__file__).resolve().parents[1]
COURSE = "3A, FRANCAIS, Trimestre 1"
CASE = "s01-francais-t1"
BASE = "http://127.0.0.1:8765"


class FakePreparer:
    """Test double for the H session: reads the frozen case through read_case, answers with catalog IDs."""

    def __init__(self, error: Exception | None = None, gate: threading.Event | None = None):
        self.error, self.gate, self.calls = error, gate, 0

    def __call__(self, frozen, read_case):
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(5)
        case = json.loads(read_case())
        if self.error is not None:
            raise self.error
        qid = next(iter(case["quote_catalog"]))
        return {"summary": "Récit vivant, structure à reprendre.", "evidence": [{"claim": "Consigne en trois paragraphes.",
                                                                               "quote_id": qid}],
                "unknowns": [], "suggestions": ["Plan en trois cases."]}


def _client(tmp_path: Path, preparer=None, workspace=True, monkeypatch=None) -> tuple[TestClient, QueueStore, Path]:
    cases = tmp_path / "dossiers"
    shutil.copytree(ROOT / "data" / "dossiers", cases)
    queue = tmp_path / "runs" / "queue.jsonl"
    app = create_app(queue_path=queue, roster_path=ROOT / "data" / "roster.csv", course=COURSE, cases_dir=cases,
                     workspace_dir=(tmp_path / "workspace") if workspace else None, preparer=preparer)
    return TestClient(app, base_url=BASE), QueueStore(queue), cases


def _wait(client: TestClient, prep_id: str) -> dict:
    for _ in range(250):
        p = client.get(f"/api/workspace/preparations/{prep_id}").json()["preparation"]
        if p["status"] not in ("queued", "running"):
            return p
        time.sleep(0.02)
    raise AssertionError("preparation did not finish")


def test_workspace_page_and_existing_page_are_served(tmp_path):
    client, _, _ = _client(tmp_path, FakePreparer())
    assert client.get("/workspace").status_code == 200
    assert "workspace.js" in client.get("/workspace").text
    assert client.get("/").status_code == 200
    assert client.get("/api/config").json()["course"] == COURSE
    assert client.get("/static/workspace.js").status_code == 200


def test_cases_list_binds_roster_ids_and_only_s01_has_a_case(tmp_path):
    client, _, _ = _client(tmp_path, FakePreparer())
    body = client.get("/api/workspace/cases").json()
    assert body["course"] == COURSE and body["preparer"]["available"] is True
    roster = {r["student_id"]: r for r in body["roster"]}
    assert roster["s01"]["display_name"] == "Lucas Bernard" and roster["s01"]["case_id"] == CASE
    assert roster["s02"]["case_id"] is None
    assert [c["case_id"] for c in body["cases"]] == [CASE]
    assert body["cases"][0]["source_kind"] == "authored_demo"


def test_case_detail_has_documents_and_no_paths(tmp_path):
    client, _, _ = _client(tmp_path, FakePreparer())
    r = client.get(f"/api/workspace/cases/{CASE}")
    assert r.status_code == 200
    case = r.json()["case"]
    assert case["student_name"] == "Lucas Bernard" and len(case["documents"]) == 4 and case["case_hash"]
    assert r.json()["preparation"] is None
    assert str(tmp_path) not in r.text and str(ROOT) not in r.text


@pytest.mark.parametrize("case_id", ["nope", "..%2Fdata%2Froster", "s02-francais-t1"])
def test_unknown_case_is_404_and_paths_are_not_accepted(tmp_path, case_id):
    client, _, _ = _client(tmp_path, FakePreparer())
    assert client.get(f"/api/workspace/cases/{case_id}").status_code == 404
    assert client.post(f"/api/workspace/cases/{case_id}/prepare", json={}).status_code == 404


def test_get_never_launches_a_preparation(tmp_path):
    fake = FakePreparer()
    client, _, _ = _client(tmp_path, fake)
    client.get("/workspace")
    client.get("/api/workspace/cases")
    client.get(f"/api/workspace/cases/{CASE}")
    time.sleep(0.05)
    assert fake.calls == 0
    assert not (tmp_path / "workspace" / "preparations").exists()


def test_prepare_is_deduplicated_and_never_touches_the_queue(tmp_path):
    gate = threading.Event()
    fake = FakePreparer(gate=gate)
    client, store, _ = _client(tmp_path, fake)
    a = client.post(f"/api/workspace/cases/{CASE}/prepare", json={})
    b = client.post(f"/api/workspace/cases/{CASE}/prepare", json={})
    assert a.status_code == 202 and a.json()["preparation"]["id"] == b.json()["preparation"]["id"]
    gate.set()
    done = _wait(client, a.json()["preparation"]["id"])
    assert done["status"] == "ready" and fake.calls == 1
    assert done["preparation"]["evidence"][0]["quote"] and "snapshot" not in done
    assert store.all() == []
    assert client.get(f"/api/workspace/cases/{CASE}").json()["preparation"]["id"] == done["id"]
    assert not (tmp_path / "runs" / "workspace").exists()
    assert (tmp_path / "workspace" / "preparations").is_dir()


def test_changed_case_file_serves_no_old_report(tmp_path):
    client, _, cases = _client(tmp_path, FakePreparer())
    done = _wait(client, client.post(f"/api/workspace/cases/{CASE}/prepare", json={}).json()["preparation"]["id"])
    data = json.loads((cases / "s01.json").read_text(encoding="utf-8"))
    data["documents"][2]["text"] += " Phrase ajoutée."
    (cases / "s01.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert client.get(f"/api/workspace/cases/{CASE}").json()["preparation"] is None
    old = client.get(f"/api/workspace/preparations/{done['id']}").json()["preparation"]
    assert old["status"] == "stale" and "preparation" not in old


def test_provider_failure_is_visible_and_retry_is_explicit(tmp_path):
    fake = FakePreparer(error=RuntimeError("raw provider text with a token"))
    client, _, _ = _client(tmp_path, fake)
    first = _wait(client, client.post(f"/api/workspace/cases/{CASE}/prepare", json={}).json()["preparation"]["id"])
    assert first["status"] == "failed" and "token" not in first["error"]
    again = client.post(f"/api/workspace/cases/{CASE}/prepare", json={}).json()["preparation"]
    assert again["id"] == first["id"] and fake.calls == 1
    fake.error = None
    retried = _wait(client, client.post(f"/api/workspace/cases/{CASE}/prepare", json={"retry": True})
                    .json()["preparation"]["id"])
    assert retried["status"] == "ready" and retried["id"] != first["id"]


def test_without_key_preparation_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    client, _, _ = _client(tmp_path, None)
    body = client.get("/api/workspace/cases").json()
    assert body["preparer"]["available"] is False and "HAI_API_KEY" in body["preparer"]["reason"]
    r = client.post(f"/api/workspace/cases/{CASE}/prepare", json={})
    assert r.status_code == 503 and "HAI_API_KEY" in r.json()["detail"]
    assert not (tmp_path / "workspace" / "preparations").exists()


def test_without_workspace_dir_preparation_is_unavailable(tmp_path):
    client, _, _ = _client(tmp_path, FakePreparer(), workspace=False)
    assert client.get("/api/workspace/cases").json()["preparer"]["available"] is False
    assert client.post(f"/api/workspace/cases/{CASE}/prepare", json={}).status_code == 503


def test_only_explicit_approval_queues_the_exact_text_for_the_bound_student(tmp_path):
    client, store, _ = _client(tmp_path, FakePreparer())
    text = "Lucas, ton récit est vivant ; découpe-le en paragraphes et relis-toi."
    r = client.post("/api/workspace/approve", json={"student_id": "s01", "student_name": "Lucas Bernard",
                                                    "text": text})
    assert r.status_code == 201
    [item] = store.all()
    assert (item["student"], item["text"], item["course"], item["source"]) == ("Lucas Bernard", text, COURSE,
                                                                               "workspace")


@pytest.mark.parametrize("body, code", [
    ({"student_id": "s01", "student_name": "Lucas Petit", "text": "x"}, 409),
    ({"student_id": "s99", "student_name": "Lucas Bernard", "text": "x"}, 422),
    ({"student_id": "s01", "student_name": "Lucas Bernard", "text": "  "}, 422),
    ({"student_name": "Lucas Bernard", "text": "x"}, 422),
])
def test_stale_or_unknown_identity_and_empty_text_queue_nothing(tmp_path, body, code):
    client, store, _ = _client(tmp_path, FakePreparer())
    assert client.post("/api/workspace/approve", json=body).status_code == code
    assert store.all() == []


def test_stop_blocks_workspace_approval(tmp_path):
    client, store, _ = _client(tmp_path, FakePreparer())
    client.post("/api/stop", json={})
    r = client.post("/api/workspace/approve", json={"student_id": "s01", "student_name": "Lucas Bernard",
                                                    "text": "Bon trimestre."})
    assert r.status_code == 409 and store.all() == []


def test_other_origins_cannot_call_workspace_routes(tmp_path):
    fake = FakePreparer()
    client, store, _ = _client(tmp_path, fake)
    evil = {"origin": "https://evil.example"}
    assert client.post(f"/api/workspace/cases/{CASE}/prepare", json={}, headers=evil).status_code == 403
    assert client.post("/api/workspace/approve", json={"student_id": "s01", "student_name": "Lucas Bernard",
                                                       "text": "x"}, headers=evil).status_code == 403
    assert client.post(f"/api/workspace/cases/{CASE}/prepare", content=b"{}",
                       headers={"content-type": "text/plain"}).status_code == 415
    assert client.get("/api/workspace/cases", headers={"host": "evil.example"}).status_code == 403
    assert fake.calls == 0 and store.all() == []


def test_unprepared_case_hash_matches_module(tmp_path):
    client, _, cases = _client(tmp_path, FakePreparer())
    from voice.roster import load_roster
    expected = dossier.load_cases(cases, load_roster(ROOT / "data" / "roster.csv"), COURSE)[CASE]
    assert client.get(f"/api/workspace/cases/{CASE}").json()["case"]["case_hash"] == dossier.case_hash(expected)


def _approve(client, **over):
    body = {"student_id": "s01", "student_name": "Lucas Bernard", "course": COURSE, "text": "Bon trimestre."}
    body.update(over)
    return client.post("/api/workspace/approve", json=body)


def test_text_over_255_characters_is_refused_not_truncated(tmp_path):
    client, store, _ = _client(tmp_path, FakePreparer())
    r = _approve(client, text="é" * 256)
    assert r.status_code == 422 and "256" in r.json()["detail"] and store.all() == []
    assert _approve(client, text="é" * 255).status_code == 201
    assert store.all()[0]["text"] == "é" * 255


def test_replacement_needs_its_own_confirmation(tmp_path):
    client, store, _ = _client(tmp_path, FakePreparer())
    assert _approve(client, previous_value="Ancien texte.").status_code == 409 and store.all() == []
    assert _approve(client, previous_value="Ancien texte.", confirm_replace=True).status_code == 201
    assert store.all()[0]["previous_value"] == "Ancien texte."


def test_changed_context_is_refused(tmp_path):
    client, store, _ = _client(tmp_path, FakePreparer())
    assert _approve(client, course="3A, FRANCAIS, Trimestre 2").status_code == 409 and store.all() == []


def test_approval_without_configured_course_is_refused(tmp_path):
    queue = tmp_path / "runs" / "queue.jsonl"
    app = create_app(queue_path=queue, roster_path=ROOT / "data" / "roster.csv", course=None,
                     cases_dir=ROOT / "data" / "dossiers", workspace_dir=tmp_path / "workspace")
    client = TestClient(app, base_url=BASE)
    r = client.post("/api/workspace/approve", json={"student_id": "s01", "student_name": "Lucas Bernard",
                                                     "text": "Bon trimestre."})
    assert r.status_code == 409 and "course" in r.json()["detail"]
    assert QueueStore(queue).all() == []
