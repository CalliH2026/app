"""Calli's H Parallel adapter: report-only H analysis, semantic checks and harness guards, offline with fakes."""

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("PIL")
pytest.importorskip("dotenv")
pytest.importorskip("hai_agents")

from calli_parallel import checks, loader, report_only


@pytest.fixture(scope="module")
def mods(h_parallel_dir):
    return loader.upstream(h_parallel_dir)


def test_alias_sets_upstream_names_only_when_missing():
    env = {"HAI_API_KEY": "h", "DEVIN_API": "d", "DEVIN_API_KEY": ""}
    assert loader.alias_credentials(env) == ["H_COMPANY_API_KEY", "DEVIN_API_KEY"]
    assert env["H_COMPANY_API_KEY"] == "h" and env["DEVIN_API_KEY"] == "d"
    assert loader.alias_credentials({"H_COMPANY_API_KEY": "x", "HAI_API_KEY": "h"}) == []


def _fake_h(mods, monkeypatch, *, answer_id=None, status="completed", seen=None):
    engine = mods.engine
    monkeypatch.setattr(engine, "transcribe", lambda path: {"provider": "Gladia", "job_id": "g", "text": "Pourquoi 3/6 ?",
                                                             "utterances": []})
    monkeypatch.setattr(engine, "search", lambda topic: {"provider": "Linkup", "query": topic, "sources": [
        {"id": "web-1", "title": "Rédiger", "url": "https://eduscol.education.fr/" + str(abs(hash(topic))),
         "excerpt": "Justifier.", "type": "external"}]})

    class Session:
        id = "h-session-real-shape"

        def __init__(self, tools):
            self.tools = tools

        def wait_for_completion(self, **kw):
            t = {f.__name__: f for f in self.tools}
            t["get_evidence_catalog"]([])
            t["transcribe_audio"]()
            t["search_resources"]("Pythagore justification rédaction", "reference")
            t["search_resources"]("Pythagore exercice rédaction autonome", "exercise")
            dossier = engine.offline_dossier("points")
            catalog = engine.quote_catalog(engine.FIXTURE["documents"])
            dossier["evidence"] = [{"claim": "Le calcul est exact.", "quote_id": next(k for k, v in catalog.items() if v["source_id"] == s)}
                                   for s in ("copie", "bareme")]
            valid = json.loads(t["validate_dossier"](engine.AgentDossier.model_validate(dossier)))
            return SimpleNamespace(status=status, answer={"validated_dossier_id": answer_id or valid["validated_dossier_id"]})

        def status(self):
            return {"status": status}

        def cancel(self):
            pass

    class Client:
        def start_session(self, **kw):
            if seen is not None:
                seen.update(kw)
            return Session(kw["tools"])

    return lambda runtime: Client()


def _audio(tmp_path):
    (tmp_path / "parent-points.wav").write_bytes(b"RIFF-hermetic-test-bytes")  # not audio: Gladia is faked here
    return tmp_path


def test_report_only_job_is_live_h_without_capsule_and_unlocks_live_practice(mods, monkeypatch, tmp_path):
    seen = {}
    job = report_only.run(audio_dir=_audio(tmp_path), client_factory=_fake_h(mods, monkeypatch, seen=seen))
    assert job["status"] == "ready", job.get("error")
    assert checks.report_checks(job) == []
    assert job["report_only"] is True and job["capsule"] is None and job["workflow_version"] == report_only.WORKFLOW
    assert [t.__name__ for t in seen["tools"]] == list(report_only.TOOLS) and seen["agent"]["environments"] == []
    assert mods.practice._source(job["id"])["source_analysis"] == "h"


def test_answer_not_returned_by_validate_dossier_fails_without_a_dossier(mods, monkeypatch, tmp_path):
    job = report_only.run(audio_dir=_audio(tmp_path), client_factory=_fake_h(mods, monkeypatch, answer_id="dossier-forged"))
    assert job["status"] == "failed" and "dossier" not in job and checks.report_checks(job)


def test_local_runtime_sends_no_answer_schema(mods, monkeypatch, tmp_path):
    seen = {}
    report_only.run(runtime="local", audio_dir=_audio(tmp_path), client_factory=_fake_h(mods, monkeypatch, seen=seen))
    assert "answer_schema" not in seen and "validated_dossier_id" in seen["messages"]


def test_practice_checks_need_live_state_and_matching_hash(tmp_path):
    (tmp_path / "activity-live.html").write_bytes(b"<html>")
    import hashlib
    state = {"status": "ready", "mode": "live", "simulated": False, "session_id": "f" * 32,
             "artifact_file": "activity-live.html", "artifact_sha256": hashlib.sha256(b"<html>").hexdigest(),
             "validation": {"html_structure_checked": True, "provider_tests_reported": True, "teacher_review_required": True}}
    assert checks.practice_checks(state, tmp_path) == []
    assert checks.practice_checks({**state, "artifact_sha256": "0" * 64}, tmp_path)
    assert checks.practice_checks({**state, "mode": "simulation", "simulated": True}, tmp_path)


def test_outing_partial_with_unknown_facts_is_not_a_success():
    job = {"status": "partial", "session_id": "h", "agent": {"computer_use_verified": True},
           "browser_evidence": {"verified": True}, "h_summary": "x", "dossier": {}, "budget": {},
           "tool_calls": [{"name": n, "status": "succeeded"} for n in checks.OUTING_TOOLS],
           "executions": [{"tool_name": n, "status": "succeeded"} for n in checks.OUTING_TOOLS[:3]],
           "visit": {"sources": [{"url": "https://www.musee-orsay.fr/fr"}]}, "route": {"provider": "OSRM", "distance_km": 3.1}}
    assert checks.outing_checks(job, "musee-orsay.fr") == ["status is 'partial', not 'ready'", "no administrative dossier or budget"]
    full = {**job, "status": "ready", "dossier": {"text": "x"}, "budget": {"complete": True}}
    assert checks.outing_checks(full, "musee-orsay.fr") == []
    assert checks.outing_checks({**full, "visit": {"sources": [{"url": "https://evil.test/x"}]}}, "musee-orsay.fr")


def test_harness_refuses_a_second_practice_create(mods, monkeypatch, tmp_path):
    from scripts import parallel_live

    job = report_only.run(audio_dir=_audio(tmp_path), client_factory=_fake_h(mods, monkeypatch))
    folder = mods.practice.FOLDER / job["id"]
    folder.mkdir(parents=True)
    (folder / "state-live.json").write_text("{}")
    monkeypatch.setattr(mods.practice, "start", lambda *a, **k: pytest.fail("must not create another Devin session"))
    with pytest.raises(SystemExit, match="reconcile"):
        parallel_live.main(["practice", "--data-dir", str(mods.data_dir), "--report-job", job["id"], "--condition", "cold"])


def test_clean_import_leaves_no_git_visible_file(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if not (root / ".git").exists():
        pytest.skip("not a git checkout")
    before = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--ignored", "vendor"],
                            cwd=root, capture_output=True, text=True, check=True).stdout
    code = ("import sys; from calli_parallel import loader; m = loader.upstream(sys.argv[1]); "
            "import vendor.h_parallel.native_bridge, vendor.h_parallel.workspace as w; w.get_workspace()")
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=root, check=True, capture_output=True)
    after = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--ignored", "vendor"],
                           cwd=root, capture_output=True, text=True, check=True).stdout
    new = set(after.splitlines()) - set(before.splitlines())
    assert not [line for line in new if "__pycache__" not in line], new
    assert not (root / "vendor" / "credentials").exists()


def test_outing_timeout_is_named_in_the_checks():
    job = {"status": "partial", "h_outcome": "timeout", "h_error": "Holo4 n’a pas terminé dans le délai de 300 s.",
           "session_id": "h", "tasks": []}
    assert "Holo4 session ended by timeout: Holo4 n’a pas terminé dans le délai de 300 s." in checks.outing_checks(job, "x.fr")
