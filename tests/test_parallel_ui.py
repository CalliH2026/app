"""Calli's /sortie and /entrainement views over the vendored H Parallel, offline (no provider is called)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ui.app import create_app

HOST = {"host": "127.0.0.1:8765"}


def _client(tmp_path, parallel_dir=None):
    app = create_app(queue_path=tmp_path / "queue.jsonl", workspace_dir=tmp_path / "ws", parallel_dir=parallel_dir)
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_pages_are_served_and_say_when_off(tmp_path):
    client = _client(tmp_path)
    for page in ("/sortie", "/entrainement"):
        response = client.get(page)
        assert response.status_code == 200 and "--parallel-dir" in response.text
    assert client.get("/api/parallel/config").json() == {"enabled": False}
    assert client.get("/api/parallel/outings/options").status_code == 404


def test_workspace_links_the_two_views_and_keeps_dictation(tmp_path):
    html = _client(tmp_path).get("/workspace").text
    assert 'href="sortie"' in html and 'href="entrainement"' in html and 'href="#dictee"' in html


@pytest.fixture
def enabled(tmp_path, h_parallel_dir):
    pytest.importorskip("PIL")
    pytest.importorskip("dotenv")
    pytest.importorskip("hai_agents")
    return _client(tmp_path, h_parallel_dir)


def test_enabled_views_map_to_upstream(enabled):
    assert enabled.get("/api/parallel/config").json() == {"enabled": True}
    options = enabled.get("/api/parallel/outings/options").json()
    assert {"classes", "destinations", "defaults"} <= set(options)
    assert enabled.get("/api/parallel/outings/unknown").status_code == 404
    assert enabled.post("/api/parallel/outings", json={"date": "2026-11-20", "mode": "demo"}).status_code == 422
    assert enabled.post("/api/parallel/outings", json={"date": "2026-11-20", "extra": 1}).status_code == 422
    assert enabled.get("/api/parallel/practice/unknown").status_code in (404, 409)
    assert enabled.post("/api/parallel/practice/unknown", json={"mode": "sneaky"}).status_code == 422


def test_preview_and_download_are_sandboxed(enabled, tmp_path, monkeypatch):
    from calli_parallel import loader

    page = tmp_path / "activity.html"
    page.write_text("<!doctype html><title>x</title>")
    monkeypatch.setattr(loader.upstream().practice, "artifact_path", lambda job, download=False: page)
    preview = enabled.get("/api/parallel/practice/job/preview")
    assert preview.status_code == 200 and preview.headers["content-security-policy"].startswith("sandbox allow-scripts;")
    assert "connect-src 'none'" in preview.headers["content-security-policy"]
    download = enabled.get("/api/parallel/practice/job/download")
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["content-security-policy"].startswith("sandbox allow-scripts;")


def test_download_before_review_is_refused(enabled, monkeypatch):
    from calli_parallel import loader

    def refuse(job, download=False):
        raise RuntimeError("Relisez l’activité avant de la télécharger.")
    monkeypatch.setattr(loader.upstream().practice, "artifact_path", refuse)
    assert enabled.get("/api/parallel/practice/job/download").status_code == 409


def test_brand_logo_is_the_original_file_on_every_page(tmp_path):
    import hashlib
    from pathlib import Path

    logo = Path(__file__).resolve().parents[1] / "ui/static/brand/calli-logo.svg"
    assert hashlib.sha256(logo.read_bytes()).hexdigest() == \
        "264bca7de716858d01132c0c59d9253bc982b89db3caafe7268311cf9c362cd0"
    client = _client(tmp_path)
    for page in ("/", "/workspace", "/sortie", "/entrainement"):
        html = client.get(page).text
        logo_src = "static/brand/calli-logo.svg" if page == "/workspace" else "/static/brand/calli-logo.svg"
        assert f'src="{logo_src}" alt="Calli"' in html and 'class="wordmark"' not in html, page
    served = client.get("/static/brand/calli-logo.svg")
    assert served.status_code == 200 and served.content == logo.read_bytes()


def test_saved_activities_are_read_without_starting_and_keyed_by_hash(enabled, tmp_path, monkeypatch):
    import hashlib

    from calli_parallel import loader

    practice = loader.upstream().practice
    files = {"job-a": tmp_path / "a.html", "job-b": tmp_path / "b.html"}
    files["job-a"].write_text("<!doctype html><title>A</title>")
    files["job-b"].write_text("<!doctype html><title>B</title>")
    states = {job: {"status": "ready", "mode": "simulation", "simulated": True, "approved": False,
                    "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for job, path in files.items()}
    monkeypatch.setattr(practice, "get", lambda job: {k: v for k, v in states[job].items() if k != "artifact_sha256"})
    monkeypatch.setattr(practice, "_load", lambda job: states[job])
    monkeypatch.setattr(practice, "artifact_path", lambda job, download=False: files[job])
    monkeypatch.setattr(practice, "start", lambda *a, **k: pytest.fail("opening a saved activity must not start one"))
    a, b = (enabled.get(f"/api/parallel/practice/{job}").json() for job in ("job-a", "job-b"))
    assert a["artifact_sha256"] != b["artifact_sha256"]
    assert enabled.get("/api/parallel/practice/job-a/preview?v=" + a["artifact_sha256"]).text.endswith("<title>A</title>")
    assert enabled.get("/api/parallel/practice/job-b/preview?v=" + b["artifact_sha256"]).text.endswith("<title>B</title>")
    # The same job regenerated in live mode: a new mode and hash, so the page reloads its frame.
    files["job-a"].write_text("<!doctype html><title>A live</title>")
    states["job-a"].update(mode="live", simulated=False, artifact_sha256=hashlib.sha256(files["job-a"].read_bytes()).hexdigest())
    live = enabled.get("/api/parallel/practice/job-a").json()
    assert live["mode"] == "live" and live["artifact_sha256"] not in (a["artifact_sha256"], b["artifact_sha256"])
    states["job-b"].update(status="failed")
    assert "artifact_sha256" not in enabled.get("/api/parallel/practice/job-b").json()


def test_practice_page_reloads_or_clears_its_frame_on_each_render():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "ui/static/parallel.js").read_text()
    assert "frame.dataset.key !== key" in js and "${job}|${state.mode}|${state.artifact_sha256}" in js
    assert "if (!ready) clearFrame();" in js and 'frame.removeAttribute("src")' in js
    assert "if (ready && !frame.src)" not in js


LEGACY_TIMEOUT = {  # shape of a real outing saved before patch 0009: timed out, nothing collected, no h_outcome
    "id": "bbbbbbbbbbb1", "status": "partial", "agent": {"model": "holo4-27b", "provider_status": "running"},
    "tasks": [{"id": i, "label": i, "status": "failed", "error": "Holo4 n’a pas terminé cet outil."}
              for i in ("visit", "route", "class", "dossier")],
    "tool_calls": [], "executions": [], "warnings": [], "error": None, "h_outcome": None, "h_error": None,
    "session_cancel": None, "visit": {"opening_time": None, "closing_time": None, "closed_on_date": None,
                                      "student_unit_price": None, "adult_unit_price": None, "group_fee": None,
                                      "max_group_size": None, "sources": []},
    "budget": {"lines": [], "complete": False, "missing": ["visite"]}, "dossier": {"text": "modèle"},
    "input": {"objective": ""}, "created_at": "2026-11-07T18:00:00+01:00"}


def test_legacy_outing_with_nothing_collected_is_shown_as_failed_and_left_unchanged(enabled):
    import json

    from calli_parallel import loader

    outings = loader.upstream().outings
    outings.FOLDER.mkdir(parents=True, exist_ok=True)
    path = outings.FOLDER / "bbbbbbbbbbb1.json"
    path.write_text(json.dumps(LEGACY_TIMEOUT, ensure_ascii=False))
    raw = path.read_bytes()
    value = enabled.get("/api/parallel/outings/bbbbbbbbbbb1").json()
    assert value["calli_view"] == {"nothing_prepared": True}
    assert value["status"] == "partial" and value["h_outcome"] is None and value["session_cancel"] is None
    assert path.read_bytes() == raw and "calli_view" not in outings.get("bbbbbbbbbbb1")
    js = (Path(__file__).resolve().parents[1] / "ui/static/parallel.js").read_text()
    assert "job.calli_view && job.calli_view.nothing_prepared" in js and "|| nothing ||" in js


def test_nothing_prepared_needs_every_collection_failed_and_no_success():
    from ui.parallel import nothing_prepared

    assert nothing_prepared(LEGACY_TIMEOUT)
    done = {**LEGACY_TIMEOUT, "tasks": [{**t, "status": "done"} if t["id"] == "visit" else t for t in LEGACY_TIMEOUT["tasks"]]}
    assert not nothing_prepared(done)
    assert not nothing_prepared({**LEGACY_TIMEOUT, "executions": [{"status": "succeeded"}]})
    assert not nothing_prepared({**LEGACY_TIMEOUT, "tool_calls": [{"name": "search_museum_visit", "status": "succeeded"}]})
    assert not nothing_prepared({**LEGACY_TIMEOUT, "status": "preparing"})
    assert not nothing_prepared({**LEGACY_TIMEOUT, "tasks": []})
