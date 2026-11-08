"""The one-command launcher: server configuration only, STOP in review mode, and the mounted module (if installed)."""

from pathlib import Path

import pytest

from agent.queue_store import QueueStore
from ui import shell

ROOT = Path(__file__).resolve().parents[1]


def test_shell_env_points_the_module_at_this_checkout(tmp_path):
    env = shell.shell_env(tmp_path / "q.jsonl", ROOT / "data" / "roster.csv", shell.DEFAULT_COURSE, tmp_path / "d", 8123)
    assert env == {"CALLI_SOURCE": str(ROOT), "CALLI_QUEUE": str((tmp_path / "q.jsonl").resolve()),
                   "CALLI_ROSTER": str(ROOT / "data" / "roster.csv"), "CALLI_COURSE": "3A, FRANCAIS, Trimestre 1",
                   "PRONOTE_DATA_DIR": str((tmp_path / "d").resolve()), "H_LOCAL_PREVIEW_PORT": "8123"}


def test_stop_flag_sets_stop_before_serving(tmp_path, monkeypatch):
    import sys
    import types

    calls = {}
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda app, **kw: calls.update(app=app, **kw)))
    for name in ("CALLI_SOURCE", "CALLI_QUEUE", "CALLI_ROSTER", "CALLI_COURSE", "PRONOTE_DATA_DIR", "H_LOCAL_PREVIEW_PORT"):
        monkeypatch.delenv(name, raising=False)
    queue = tmp_path / "runs" / "queue.jsonl"
    assert shell.main(["--queue", str(queue), "--data-dir", str(tmp_path / "d"), "--port", "8124", "--stop"]) == 0
    assert QueueStore(queue).stop_requested() and QueueStore(queue).all() == []
    assert QueueStore(queue).stop_reason() == "preview"
    assert calls == {"app": "mvp.app:app", "host": "127.0.0.1", "port": 8124, "lifespan": "off", "log_level": "warning"}


@pytest.fixture
def isolated_mvp_modules():
    """Drop the mvp/ui modules this test imports, so a Calli-mounted mvp.app never leaks into later tests."""
    import sys

    def owned(name):
        return name in ("mvp", "ui") or name.startswith(("mvp.", "ui."))

    saved = {name: module for name, module in sys.modules.items() if owned(name)}
    yield
    for name in [m for m in sys.modules if owned(m)]:
        del sys.modules[name]
    sys.modules.update(saved)


def test_mounted_shell_serves_calli_with_its_guards(tmp_path, monkeypatch, isolated_mvp_modules):
    pytest.importorskip("hai_agents")
    pytest.importorskip("authlib")
    import importlib
    import sys

    from fastapi.testclient import TestClient

    queue = tmp_path / "queue.jsonl"
    QueueStore(queue).stop()
    for key, value in shell.shell_env(queue, ROOT / "data" / "roster.csv", shell.DEFAULT_COURSE, tmp_path / "d", 8000).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    for name in [m for m in sys.modules if m == "mvp" or m.startswith("mvp.")]:
        del sys.modules[name]
    for name in [m for m in sys.modules if m == "ui" or m.startswith("ui.")]:
        if not str(getattr(sys.modules[name], "__file__", "") or "").startswith(str(ROOT)):
            del sys.modules[name]
    app = importlib.import_module("mvp.app").app
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    status = client.get("/api/calli/status").json()
    assert status["available"] is True and status["course"] == shell.DEFAULT_COURSE
    assert client.get("/calli/api/state").json()["stopped"] is True
    item = {"student_id": "s01", "student_name": "Lucas Bernard", "text": "Bon trimestre."}
    assert client.post("/calli/api/workspace/approve", json=item, headers={"origin": "http://127.0.0.1:8000"}).status_code == 409
    assert client.post("/calli/api/workspace/approve", json=item, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.get("/calli/api/state", headers={"host": "evil.example"}).status_code == 403
    assert QueueStore(queue).all() == []
