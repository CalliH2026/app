"""The workspace mounted under a prefix inside another ASGI app (e.g. /calli in Francois's shell), and ?embed=1.

The workspace uses page-relative URLs, so the same files work at / and under the mount. Calli's own Host, Origin,
JSON-only POST and WebSocket origin checks still apply inside the mount.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent.queue_store import QueueStore
from ui.app import create_app

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
ORIGIN = {"origin": BASE}


def _mounted(tmp_path):
    queue = tmp_path / "queue.jsonl"
    calli = create_app(queue_path=queue, roster_path=ROOT / "data" / "roster.csv", course="3A, FRANCAIS, Trimestre 1",
                       workspace_dir=tmp_path / "ws")
    shell = FastAPI()

    @shell.get("/")
    def home():
        return {"shell": True}

    shell.mount("/calli", calli)
    return TestClient(shell, base_url=BASE), QueueStore(queue)


def test_workspace_and_its_assets_resolve_under_the_mount(tmp_path):
    client, _ = _mounted(tmp_path)
    assert client.get("/").json() == {"shell": True}
    html = client.get("/calli/workspace?embed=1").text
    for asset in ("static/workspace.css", "static/workspace.js", "static/brand/calli-logo.svg"):
        assert f'"{asset}"' in html
        assert client.get("/calli/" + asset).status_code == 200
    assert client.get("/calli/static/avatars/calli-portraits-fictifs-ia-s01-s10.png").status_code == 200
    assert client.get("/calli/static/fonts/plus-jakarta-sans-latin.woff2").status_code == 200
    assert client.get("/calli/api/state").status_code == 200
    js = client.get("/calli/static/workspace.js").text
    assert 'new URL("ws/dictation", location.href)' in js and 'embedded' in js and "${location.host}/ws" not in js


def test_mounted_guards_are_calli_s_own(tmp_path):
    client, store = _mounted(tmp_path)
    assert client.get("/calli/api/state", headers={"host": "evil.example"}).status_code == 403
    item = {"student_id": "s01", "student_name": "Lucas Bernard", "text": "Bon trimestre."}
    assert client.post("/calli/api/workspace/approve", json=item, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/calli/api/workspace/approve", content=b"{}", headers={"content-type": "text/plain"}).status_code == 415
    assert store.all() == []


def test_mounted_stop_and_resume(tmp_path):
    client, store = _mounted(tmp_path)
    assert client.post("/calli/api/stop", json={}, headers=ORIGIN).status_code == 200
    assert client.get("/calli/api/state").json()["stopped"] is True
    item = {"student_id": "s01", "student_name": "Lucas Bernard", "text": "Bon trimestre."}
    assert client.post("/calli/api/workspace/approve", json=item, headers=ORIGIN).status_code == 409
    assert client.post("/calli/api/resume", json={}, headers=ORIGIN).status_code == 200
    assert client.get("/calli/api/state").json()["stopped"] is False and store.all() == []


def test_mounted_websocket_refuses_foreign_or_missing_origin(tmp_path):
    client, _ = _mounted(tmp_path)
    for headers in ({"origin": "http://evil.example"}, {}, {"origin": "http://127.0.0.1:9999"}):
        with pytest.raises(WebSocketDisconnect), \
                client.websocket_connect("ws://127.0.0.1:8765/calli/ws/dictation", headers=headers) as ws:
            ws.receive_json()


def test_without_speech_factory_mounted_dictation_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("GLADIA_API_KEY", raising=False)
    client, _ = _mounted(tmp_path)
    with client.websocket_connect("ws://127.0.0.1:8765/calli/ws/dictation", headers=ORIGIN) as ws:
        ws.send_json({"type": "start", "turn_id": "turn-ws-000001", "student_id": "s01", "course": "3A, FRANCAIS, Trimestre 1"})
        assert ws.receive_json()["reason"] == "unavailable"


def test_embedded_keeps_relative_avatars_and_the_course_line(tmp_path):
    client, _ = _mounted(tmp_path)
    js = client.get("/calli/static/workspace.js").text
    css = client.get("/calli/static/workspace.css").text
    assert 'src: rel(s.avatar)' in js and "src: s.avatar" not in js
    assert ".embedded .topbar #course-line, .embedded h3, .embedded .label {" in css and "display: block; font-family: var(--mono)" in css
    assert "3A, FRANCAIS, Trimestre 1" in client.get("/calli/api/state").text or client.get("/calli/api/state").status_code == 200


def test_embedded_preselects_only_roster_pupils_and_names_no_env_variable(tmp_path):
    client, _ = _mounted(tmp_path)
    js = client.get("/calli/static/workspace.js").text
    assert 'if (wanted && ui.roster.some((s) => s.student_id === wanted)) await selectPupil(wanted);' in js
    assert '"Dictée vocale non activée sur ce serveur."' in js
