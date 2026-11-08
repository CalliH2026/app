"""Selectable agent loop for the read-only preparer: managed (default) or local (Client.local()), offline.

The SDK is replaced by a recording stand-in module (test double only); no runtime starts and no provider is called.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from research import preparation
from research.preparation import HPreparer, PreparationStore, preparer_from_env
from tests.test_dossier import FakeClient, FakeResult, FakeSession, SessionStatus, _answer, _case


class FakeSdk:
    def __init__(self, local_error: Exception | None = None, client: FakeClient | None = None):
        self.local_calls = self.managed_calls = 0
        self.local_error, self.client = local_error, client
        sdk = self

        class Client:
            def __init__(self, **kwargs):
                sdk.managed_calls += 1

            @classmethod
            def local(cls, **kwargs):
                sdk.local_calls += 1
                if sdk.local_error:
                    raise sdk.local_error
                return sdk.client

        self.module = types.SimpleNamespace(Client=Client)


@pytest.fixture
def sdk(monkeypatch):
    def install(**kwargs):
        fake = FakeSdk(**kwargs)
        monkeypatch.setitem(sys.modules, "hai_agents", fake.module)
        return fake
    return install


class ClosingClient(FakeClient):
    closed = 0

    def close(self):
        self.closed += 1


@pytest.mark.parametrize("value, runtime", [(None, "managed"), ("managed", "managed"), ("local", "local")])
def test_runtime_is_selected_explicitly_and_nothing_starts_at_selection(monkeypatch, sdk, value, runtime):
    fake = sdk()
    monkeypatch.setenv("HAI_API_KEY", "test-only")
    if value is None:
        monkeypatch.delenv("CALLI_PREPARER_RUNTIME", raising=False)
    else:
        monkeypatch.setenv("CALLI_PREPARER_RUNTIME", value)
    prep, reason = preparer_from_env()
    assert prep.runtime == runtime and reason == ""
    assert fake.local_calls == fake.managed_calls == 0


def test_unknown_runtime_is_unavailable_not_a_fallback(monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", "test-only")
    monkeypatch.setenv("CALLI_PREPARER_RUNTIME", "cloud-or-whatever")
    prep, reason = preparer_from_env()
    assert prep is None and "CALLI_PREPARER_RUNTIME" in reason


def test_local_job_uses_same_tools_and_schema_records_runtime_and_closes_client(tmp_path, sdk):
    case = _case(tmp_path)
    client = ClosingClient(FakeSession(SessionStatus(status="idle"), FakeResult("idle", _answer(case))))
    fake = sdk(client=client)
    store = PreparationStore(tmp_path / "ws", HPreparer(runtime="local", model="holo4-35b-a3b"), searcher=None)
    job = store.wait(store.prepare(case)["id"], 5)
    assert job["status"] == "ready" and job["provider_runtime"] == "local"
    started = client.started[0]
    assert [t.__name__ for t in started["tools"]] == ["read_case", "search_resources"]
    assert "answer_schema" not in started and started["agent"]["environments"] == []
    assert preparation.LOCAL_ANSWER_FORMAT in started["messages"] and job["answer_contract"] == "json_text_validated"
    assert started["agent"]["model"] == "holo4-35b-a3b"
    assert fake.local_calls == 1 and fake.managed_calls == 0 and client.closed == 1


def test_local_failure_is_a_failed_job_closed_and_never_retried_on_managed(tmp_path, sdk):
    case = _case(tmp_path)
    client = ClosingClient(FakeSession(SessionStatus(status="idle"), FakeResult("failed", None)))
    fake = sdk(client=client)
    store = PreparationStore(tmp_path / "ws", HPreparer(runtime="local"), searcher=None)
    job = store.wait(store.prepare(case)["id"], 5)
    assert job["status"] == "failed" and job["provider_runtime"] == "local" and client.closed == 1
    assert fake.managed_calls == 0


def test_local_runtime_start_failure_fails_the_job_without_fallback(tmp_path, sdk):
    case = _case(tmp_path)
    fake = sdk(local_error=RuntimeError("download blocked"))
    store = PreparationStore(tmp_path / "ws", HPreparer(runtime="local"), searcher=None)
    job = store.wait(store.prepare(case)["id"], 5)
    assert job["status"] == "failed" and job["provider_session_id"] is None
    assert fake.local_calls == 1 and fake.managed_calls == 0
    assert "download" not in (job["error"] or "")


def test_invalid_runtime_name_is_refused():
    with pytest.raises(ValueError):
        HPreparer(runtime="Local ")


def test_get_routes_never_build_a_client(tmp_path, sdk, monkeypatch):
    fake = sdk()
    monkeypatch.setenv("HAI_API_KEY", "test-only")
    monkeypatch.setenv("CALLI_PREPARER_RUNTIME", "local")
    from fastapi.testclient import TestClient

    from ui.app import create_app
    root = Path(__file__).resolve().parents[1]
    app = create_app(queue_path=tmp_path / "q.jsonl", roster_path=root / "data" / "roster.csv",
                     course="3A, FRANCAIS, Trimestre 1", cases_dir=root / "data" / "dossiers",
                     workspace_dir=tmp_path / "ws")
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    assert c.get("/workspace").status_code == 200 and c.get("/api/workspace/cases").status_code == 200
    assert fake.local_calls == fake.managed_calls == 0


def test_session_start_failure_keeps_runtime_provenance(tmp_path, sdk):
    case = _case(tmp_path)

    class Refusing(ClosingClient):
        def start_session(self, **kwargs):
            raise RuntimeError("refused")

    client = Refusing(None)
    sdk(client=client)
    store = PreparationStore(tmp_path / "ws", HPreparer(runtime="local"), searcher=None)
    job = store.wait(store.prepare(case)["id"], 5)
    assert job["status"] == "failed" and job["provider_runtime"] == "local" and client.closed == 1


class FailedRun(FakeResult):
    def __init__(self, error, error_code):
        super().__init__("failed", None)
        self.error, self.error_code = error, error_code


def test_failed_local_session_keeps_sanitized_private_diagnostic_and_a_short_public_message(tmp_path, sdk,
                                                                                            monkeypatch):
    from ui.workspace import public_job

    monkeypatch.setenv("HAI_API_KEY", "hk-test-only-value")
    case = _case(tmp_path)
    error = "tool bridge refused: Authorization: Bearer abc.def key hk-test-only-value"
    client = ClosingClient(FakeSession(SessionStatus(status="idle"), FailedRun(error, "agent_error")))
    sdk(client=client)
    store = PreparationStore(tmp_path / "ws", HPreparer(runtime="local"), searcher=None)
    job = store.wait(store.prepare(case)["id"], 5)
    assert job["status"] == "failed" and job["error"].endswith("(statut failed, code agent_error).")
    diag = job["diagnostic"]
    assert diag["stage"] == "wait" and diag["runtime"] == "local" and diag["provider_error_code"] == "agent_error"
    assert diag["provider_status"] == "failed" and "tool bridge refused" in diag["provider_error"]
    on_disk = next((tmp_path / "ws").rglob(f"{job['id']}.json")).read_text(encoding="utf-8")
    assert '"diagnostic"' in on_disk and "hk-test-only-value" not in on_disk and "abc.def" not in on_disk
    assert "diagnostic" not in public_job(job) and "Préparation en échec pendant la session H." in \
        [e["text"] for e in job["events"]]


def test_session_start_failure_diagnostic_names_the_stage_and_http_status(tmp_path, sdk):
    case = _case(tmp_path)

    class ApiError(Exception):
        status_code = 503

    class Refusing(ClosingClient):
        def start_session(self, **kwargs):
            raise ApiError("service unavailable")

    sdk(client=Refusing(None))
    store = PreparationStore(tmp_path / "ws", HPreparer(runtime="local"), searcher=None)
    job = store.wait(store.prepare(case)["id"], 5)
    assert job["diagnostic"]["stage"] == "start" and job["diagnostic"]["http_status"] == 503
    assert job["diagnostic"]["error_type"] == "ApiError" and "service unavailable" not in job["error"]


@pytest.mark.parametrize("code, shown", [("agent_error", True), ("token=hk-abc123456 leaked", False), ("X" * 50, False)])
def test_only_a_category_like_error_code_reaches_the_public_message(code, shown):
    err = preparation.SessionEnded("failed", None, code)
    assert (f"code {code}" in str(err)) is shown and err.error_code == code


def _local_job(tmp_path, sdk, answer):
    case = _case(tmp_path)
    client = ClosingClient(FakeSession(SessionStatus(status="idle"), FakeResult("completed", answer(case))))
    sdk(client=client)
    store = PreparationStore(tmp_path / "ws", HPreparer(runtime="local"), searcher=None)
    return store.wait(store.prepare(case)["id"], 5), client


def test_local_answer_is_json_text_validated_and_fenced_json_is_accepted(tmp_path, sdk):
    import json as _json
    job, client = _local_job(tmp_path, sdk, lambda c: "```json\n" + _json.dumps(_answer(c), ensure_ascii=False) + "\n```")
    assert job["status"] == "ready" and job["answer_contract"] == "json_text_validated" and client.closed == 1


@pytest.mark.parametrize("answer", [
    lambda c: "Voici ma synthèse, sans JSON.",
    lambda c: '{"summary": "x"}',
    lambda c: '["not", "an", "object"]',
])
def test_local_answer_that_is_not_the_answer_object_fails_at_check_with_its_session(tmp_path, sdk, answer):
    job, client = _local_job(tmp_path, sdk, answer)
    assert job["status"] == "failed" and not job.get("preparation") and client.closed == 1
    assert job["diagnostic"]["stage"] == "check" and job["provider_session_id"]
    assert "réponse refusée" in job["error"]
