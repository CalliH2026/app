"""Observed document opening inside Calli -> anticipatory preparation (ui/workspace.py), offline.

The H preparer is an injected fake (test double only); the case files, PreparationStore, observation ledger,
QueueStore and guards are real.
"""

from __future__ import annotations

import json
import shutil
import threading
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
        return {"summary": "Récit vivant.", "evidence": [{"claim": "Consigne.", "quote_id": qid}],
                "unknowns": [], "suggestions": []}


def _client(tmp_path, preparer):
    cases = tmp_path / "dossiers"
    shutil.copytree(ROOT / "data" / "dossiers", cases)
    queue = tmp_path / "runs" / "queue.jsonl"
    app = create_app(queue_path=queue, roster_path=ROOT / "data" / "roster.csv", course=COURSE, cases_dir=cases,
                     workspace_dir=tmp_path / "workspace", preparer=preparer)
    return TestClient(app, base_url=BASE), QueueStore(queue), cases


def _hash(client):
    return client.get(f"/api/workspace/cases/{CASE}").json()["case"]["case_hash"]


def _event(client, **over):
    body = {"event_id": "obs-0000000001", "event_type": "document_opened", "source_kind": "calli_workspace",
            "student_id": "s01", "course": COURSE, "case_id": CASE, "document_id": "copie",
            "case_hash": _hash(client), "observed_at": "2026-11-07T18:00:00+01:00"}
    body.update(over)
    return client.post("/api/workspace/observations", json=body)


def _wait(client, prep_id):
    for _ in range(200):
        job = client.get(f"/api/workspace/preparations/{prep_id}").json()["preparation"]
        if job["status"] not in ("queued", "running"):
            return job
        threading.Event().wait(0.02)
    raise AssertionError("preparation did not settle")


def test_opening_a_source_starts_one_preparation_with_trigger_provenance(tmp_path):
    fake = FakePreparer()
    client, store, _ = _client(tmp_path, fake)
    r = _event(client)
    assert r.status_code == 202
    obs, prep = r.json()["observation"], r.json()["preparation"]
    assert obs["outcome"] == "preparation_started" and obs["source_kind"] == "calli_workspace"
    job = _wait(client, prep["id"])
    assert job["status"] == "ready" and fake.calls == 1
    assert job["trigger"]["event_id"] == "obs-0000000001" and job["trigger"]["document_id"] == "copie"
    kinds = {e.get("kind") for e in job["events"]}
    assert {"observed", "model_tool", "check"} <= kinds
    assert store.all() == []


def test_repeated_reopened_and_flickering_events_never_duplicate(tmp_path):
    fake = FakePreparer()
    client, _store, _ = _client(tmp_path, fake)
    first = _event(client).json()["preparation"]
    _wait(client, first["id"])
    again = _event(client).json()  # same event id (retry / re-render)
    other_doc = _event(client, event_id="obs-0000000002", document_id="bareme").json()  # another source, same case
    reopened = _event(client, event_id="obs-0000000003").json()  # same source reopened after refresh
    assert again["observation"]["duplicate"] is True
    assert {other_doc["preparation"]["id"], reopened["preparation"]["id"]} == {first["id"]}
    assert other_doc["observation"]["outcome"] == "already_prepared"
    assert fake.calls == 1


def test_paused_observation_starts_nothing(tmp_path):
    fake = FakePreparer()
    client, _store, _ = _client(tmp_path, fake)
    assert client.post("/api/workspace/observation", json={"paused": True}).json()["paused"] is True
    r = _event(client).json()
    assert r["observation"]["outcome"] == "paused" and r["preparation"] is None and fake.calls == 0
    assert client.get("/api/workspace/cases").json()["observation"]["paused"] is True
    client.post("/api/workspace/observation", json={"paused": False})
    assert _event(client, event_id="obs-0000000009").json()["observation"]["outcome"] == "preparation_started"


@pytest.mark.parametrize("over, status", [
    ({"course": "3A, FRANCAIS, Trimestre 2"}, 409),
    ({"case_hash": "0" * 64}, 409),
    ({"student_id": "s02"}, 409),
    ({"document_id": "../secret"}, 422),
    ({"case_id": "nope"}, 404),
    ({"source_kind": "pronote_native"}, 422),
    ({"event_type": "window_focused"}, 422),
    ({"event_id": "x"}, 422),
])
def test_stale_foreign_or_unregistered_events_are_rejected(tmp_path, over, status):
    fake = FakePreparer()
    client, _store, _ = _client(tmp_path, fake)
    assert _event(client, **over).status_code == status
    assert fake.calls == 0


def test_changed_case_rejects_old_hash_and_failure_is_not_retried_automatically(tmp_path):
    fake = FakePreparer(error=RuntimeError("provider down"))
    client, _store, cases = _client(tmp_path, fake)
    old = _hash(client)
    job = _wait(client, _event(client).json()["preparation"]["id"])
    assert job["status"] == "failed"
    again = _event(client, event_id="obs-0000000004").json()
    assert again["observation"]["outcome"] == "already_failed" and fake.calls == 1
    data = json.loads((cases / "s01.json").read_text(encoding="utf-8"))
    data["question"] += " Et à l'oral ?"
    (cases / "s01.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert _event(client, event_id="obs-0000000005", case_hash=old).status_code == 409


def test_without_key_observation_is_recorded_as_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    client, _store, _ = _client(tmp_path, None)
    r = _event(client)
    assert r.status_code == 202 and r.json()["observation"]["outcome"] == "unavailable"
    assert r.json()["preparation"] is None


def test_other_origin_cannot_post_observations(tmp_path):
    client, _store, _ = _client(tmp_path, FakePreparer())
    body = {"event_id": "obs-0000000001", "event_type": "document_opened", "source_kind": "calli_workspace",
            "student_id": "s01", "course": COURSE, "case_id": CASE, "document_id": "copie",
            "case_hash": dossier.PREPARATION_VERSION, "observed_at": "x"}
    r = client.post("/api/workspace/observations", json=body, headers={"origin": "http://evil.example"})
    assert r.status_code == 403


def test_replayed_event_after_case_change_is_refused_as_stale(tmp_path):
    client, _store, cases = _client(tmp_path, FakePreparer())
    old_hash = _hash(client)
    _wait(client, _event(client).json()["preparation"]["id"])
    data = json.loads((cases / "s01.json").read_text(encoding="utf-8"))
    data["question"] += " Et à l'oral ?"
    (cases / "s01.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert _event(client, case_hash=old_hash).status_code == 409


def test_identical_replay_is_idempotent_but_a_reused_id_with_other_content_conflicts(tmp_path):
    fake = FakePreparer()
    client, _store, _ = _client(tmp_path, fake)
    first = _event(client).json()
    replay = _event(client).json()
    assert replay["observation"]["duplicate"] is True
    assert replay["preparation"]["id"] == first["preparation"]["id"]
    assert _event(client, document_id="bareme").status_code == 409
    assert _event(client, observed_at="2026-11-07T18:05:00+01:00").status_code == 409
    assert fake.calls == 1


def test_reused_id_for_another_pupil_never_returns_the_first_pupils_preparation(tmp_path):
    client, _store, cases = _client(tmp_path, FakePreparer())
    data = json.loads((cases / "s01.json").read_text(encoding="utf-8"))
    data.update(case_id="s02-francais-t1", student_id="s02", student_name="Lucas Petit")
    (cases / "s02.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _event(client)
    other_hash = client.get("/api/workspace/cases/s02-francais-t1").json()["case"]["case_hash"]
    r = _event(client, student_id="s02", case_id="s02-francais-t1", case_hash=other_hash)
    assert r.status_code == 409 and "preparation" not in r.json()


def test_concurrent_identical_arrivals_start_one_preparation(tmp_path):
    fake = FakePreparer(gate=threading.Event())
    client, _store, _ = _client(tmp_path, fake)
    body = {"event_id": "obs-concurrent1", "event_type": "document_opened", "source_kind": "calli_workspace",
            "student_id": "s01", "course": COURSE, "case_id": CASE, "document_id": "copie",
            "case_hash": _hash(client), "observed_at": "2026-11-07T18:00:00+01:00"}
    out = []
    threads = [threading.Thread(target=lambda: out.append(
        client.post("/api/workspace/observations", json=body).json())) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fake.gate.set()
    assert sorted(o["observation"]["duplicate"] for o in out) == [False] + [True] * 5
    assert len({o["preparation"]["id"] for o in out}) == 1
    _wait(client, out[0]["preparation"]["id"])
    assert fake.calls == 1
