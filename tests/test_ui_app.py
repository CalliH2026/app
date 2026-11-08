from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from agent.journal import Event, Journal
from agent.queue_store import QueueStore
from ui.app import create_app
from voice.roster import load_roster

ROSTER = "student_id,display_name,aliases\nm1,Barbara Gardner,\nm2,Brian Franklin,\nm3,Stephanie Adams,\n"


@pytest.fixture()
def env(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    roster.write_text(ROSTER, encoding="utf-8")
    queue = tmp_path / "runs" / "queue.jsonl"
    app = create_app(queue_path=queue, roster_path=roster, course="Mindful Course Creation")
    return TestClient(app, base_url="http://127.0.0.1:8765"), QueueStore(queue), tmp_path


def test_index_and_static_are_served(env):
    client, _, _ = env
    r = client.get("/")
    assert r.status_code == 200 and "<main" in r.text and 'id="stop"' in r.text
    assert client.get("/static/app.js").status_code == 200
    assert "--danger" in client.get("/static/style.css").text


def test_structure_returns_candidates(env):
    client, _, _ = env
    r = client.post("/api/structure", json={"text": "Barbara, participe bien"})
    assert r.status_code == 200
    [item] = r.json()["items"]
    assert item["kind"] == "comment" and item["text"] == "Participe bien"
    assert item["candidates"] == [{"student_id": "m1", "display_name": "Barbara Gardner"}]
    assert item["needs_choice"] is False


def test_structure_tie_forces_a_choice(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    roster.write_text(ROSTER + "m4,Barbara Adams,\n", encoding="utf-8")
    client = TestClient(create_app(queue_path=tmp_path / "queue.jsonl", roster_path=roster),
                        base_url="http://127.0.0.1:8765")
    [item] = client.post("/api/structure", json={"text": "Barbara, participe bien"}).json()["items"]
    assert sorted(c["display_name"] for c in item["candidates"]) == ["Barbara Adams", "Barbara Gardner"]
    assert item["needs_choice"] is True


def test_approve_creates_a_pending_item(env):
    client, store, _ = env
    r = client.post("/api/approve", json={"student": "Barbara Gardner", "text": "Participe bien."})
    assert r.status_code == 201
    [it] = store.all()
    assert it["status"] == "pending" and it["student"] == "Barbara Gardner" and it["text"] == "Participe bien."
    assert it["course"] == "Mindful Course Creation" and it["source"] == "ui"
    assert r.json()["item"]["item_id"] == it["item_id"] and r.json()["duplicate"] is False
    again = client.post("/api/approve", json={"student": "Barbara Gardner", "text": "Participe bien"})
    assert again.json()["duplicate"] is True and len(store.all()) == 1


def test_approve_refuses_unknown_student_and_empty_text(env):
    client, store, _ = env
    assert client.post("/api/approve", json={"student": "Barbara", "text": "x"}).status_code == 422
    assert client.post("/api/approve", json={"student": "Barbara Gardner", "text": "  "}).status_code == 422
    assert store.all() == []


def test_stop_creates_the_stop_file_and_resume_removes_it(env):
    client, store, tmp_path = env
    client.post("/api/approve", json={"student": "Brian Franklin", "text": "Trimestre sérieux."})
    r = client.post("/api/stop", json={})
    assert r.status_code == 200 and r.json()["stopped"] is True and len(r.json()["drained"]) == 1
    assert (tmp_path / "runs" / "STOP").exists()
    assert store.all()[0]["status"] == "aborted"
    assert client.get("/api/state").json()["stopped"] is True
    assert client.post("/api/approve", json={"student": "Brian Franklin", "text": "Autre."}).status_code == 409
    assert client.post("/api/resume", json={}).json() == {"stopped": False}
    assert not (tmp_path / "runs" / "STOP").exists()


def test_state_has_items_and_latest_journal_lines(env):
    client, store, tmp_path = env
    store.append({"item_id": "q1", "student": "Barbara Gardner", "text": "Participe bien."})
    Journal(tmp_path / "runs" / "20261107-140000" / "journal.jsonl").append(
        Event(item_id="q1", student="Barbara Gardner", status="verified", text_read_back="Participe bien.",
              similarity=1.0, seconds=42.0))
    s = client.get("/api/state").json()
    assert [it["item_id"] for it in s["items"]] == ["q1"]
    assert s["journal"][0]["status"] == "verified" and s["journal_path"].endswith("journal.jsonl")
    assert s["summary"] == {"pending": 1} and s["stopped"] is False


def test_other_sites_cannot_drive_the_queue(env):
    client, store, _ = env
    # a page on another site can submit a form (no preflight): refused, nothing stopped
    assert client.post("/api/stop", data={"x": "1"}).status_code == 415
    assert client.post("/api/stop", content=b"", headers={"content-type": "text/plain"}).status_code == 415
    assert client.post("/api/stop", json={}, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/state", headers={"host": "evil.example:8765"}).status_code == 403
    assert not store.stop_requested()
    assert client.post("/api/stop", json={}, headers={"origin": "http://127.0.0.1:8765"}).status_code == 200
    assert client.get("/api/state", headers={"host": "localhost:8765"}).status_code == 200


def test_cli_refuses_a_network_address():
    from ui.app import main

    with pytest.raises(SystemExit) as exc:
        main(["--host", "0.0.0.0"])
    assert exc.value.code == 2


class FakeLinkup:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, **kwargs):
        self.calls += 1
        return {"text": "Avant chaque contrôle, récite le cours de mémoire puis vérifie : c'est ce qui le fixe.",
                "source_name": "Roediger & Karpicke (2006)", "source_url": "https://doi.org/10.1111/j.1467-9280.2006.01693.x"}


def _advised(tmp_path: Path, fake: FakeLinkup) -> tuple[TestClient, QueueStore]:
    from research import advice

    roster = tmp_path / "roster.csv"
    roster.write_text(ROSTER, encoding="utf-8")
    queue = tmp_path / "runs" / "queue.jsonl"
    app = create_app(queue_path=queue, roster_path=roster,
                     advisor=lambda t: advice.suggest(t, client=fake, cache_path=tmp_path / "runs" / "cache.jsonl"))
    return TestClient(app, base_url="http://127.0.0.1:8765"), QueueStore(queue)


def test_suggestion_is_appended_only_on_the_teachers_action(tmp_path: Path):
    fake = FakeLinkup()
    client, store = _advised(tmp_path, fake)
    comment = "Apprend ses leçons de façon irrégulière."
    s = client.post("/api/advice", json={"text": comment}).json()["suggestion"]
    assert s["source_name"] == "Roediger & Karpicke (2006)" and s["source_url"].startswith("https://doi.org/")
    assert store.all() == []  # a suggestion never queues anything
    client.post("/api/approve", json={"student": "Barbara Gardner", "text": comment})
    assert store.all()[0]["text"] == comment  # ignored: the comment is queued as it was
    appended = f"{comment} {s['text']}"  # what "Ajouter" puts in the text field
    client.post("/api/approve", json={"student": "Brian Franklin", "text": appended})
    assert store.all()[1]["text"] == appended
    assert client.post("/api/advice", json={"text": comment}).json()["suggestion"] == s
    assert fake.calls == 1  # second request served from the cache


def test_no_suggestion_without_key_or_on_error(env, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LINKUP_API_KEY", raising=False)
    client, store, _ = env
    assert client.post("/api/advice", json={"text": "Participe peu à l'oral."}).json() == {"suggestion": None}

    def broken(text):
        raise RuntimeError("boom")

    app = create_app(queue_path=tmp_path / "q.jsonl", roster_path=tmp_path / "roster.csv", advisor=broken)
    r = TestClient(app, base_url="http://127.0.0.1:8765").post("/api/advice", json={"text": "x"})
    assert r.status_code == 200 and r.json() == {"suggestion": None}
    assert store.all() == []


def test_page_has_the_hidden_suggestion_block(env):
    client, _, _ = env
    html = client.get("/").text
    assert '<div id="advice" class="advice" hidden>' in html and ">Ajouter</button>" in html
    assert 'rel="noopener noreferrer"' in html



ROOT = Path(__file__).resolve().parent.parent


def test_avatars_are_served_offline_for_the_real_roster(tmp_path: Path):
    client = TestClient(create_app(queue_path=tmp_path / "queue.jsonl", roster_path=ROOT / "data" / "roster.csv"),
                        base_url="http://127.0.0.1:8765")
    roster = client.get("/api/config").json()["roster"]
    assert [s["student_id"] for s in roster] == [s.student_id for s in load_roster(ROOT / "data" / "roster.csv")]
    for s in roster:
        assert s["avatar"] == f"/static/avatars/{s['student_id']}.svg"
        r = client.get(s["avatar"])
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")


def test_missing_avatar_falls_back_to_initials(env):
    client, _, tmp_path = env  # m1, m2, m3 have no avatar file
    roster = client.get("/api/config").json()["roster"]
    assert [(s["avatar"], s["initials"]) for s in roster] == [(None, "BG"), (None, "BF"), (None, "SA")]
    assert all(s["color"].startswith("#") for s in roster)
    avatars = tmp_path / "avatars"
    avatars.mkdir()
    (avatars / "m2.svg").write_text("<svg/>", encoding="utf-8")
    app = create_app(queue_path=tmp_path / "q.jsonl", roster_path=tmp_path / "roster.csv", avatars_dir=avatars)
    client2 = TestClient(app, base_url="http://127.0.0.1:8765")
    roster = client2.get("/api/config").json()["roster"]
    assert [s["avatar"] for s in roster] == [None, "/static/avatars/m2.svg", None]
    assert client2.get("/static/avatars/m2.svg").text == "<svg/>"
    js = client.get("/static/app.js").text
    assert "avatar-initials" in js and '"error"' in js  # the page draws initials when there is no file or it fails


def test_initials():
    from ui.app import initials
    assert initials("Gaëlle Fontaine") == "GF" and initials("Jean Marc Dupont") == "JD" and initials("Inès") == "I"
    assert initials("") == "?"


def test_launch_preview_stop_is_quiet_but_still_refuses_writes_and_a_pressed_stop_is_reported(env):
    client, store, tmp_path = env
    assert client.get("/api/state").json()["stop_mode"] is None
    store.stop(reason="preview")
    s = client.get("/api/state").json()
    assert s["stopped"] is True and s["stop_mode"] == "preview"
    r = client.post("/api/approve", json={"student": "Barbara Gardner", "text": "Bon travail."})
    assert r.status_code == 409 and store.all() == []
    assert client.post("/api/stop", json={}).json()["stopped"] is True
    assert client.get("/api/state").json()["stop_mode"] == "user"
    (tmp_path / "runs" / "STOP").write_text("", encoding="utf-8")
    assert store.stop_reason() == "user"
    (tmp_path / "runs" / "STOP").write_bytes(b"\xff\xfe preview")
    assert store.stop_reason() == "user" and client.get("/api/state").json()["stop_mode"] == "user"
    client.post("/api/resume", json={})
    assert client.get("/api/state").json()["stop_mode"] is None


def test_workspace_page_has_a_separate_quiet_preview_banner(env):
    client, _, _ = env
    html = client.get("/static/workspace.html").text
    assert 'id="preview-banner"' in html and "Mode aperçu" in html and 'id="stop-banner"' in html
    js = client.get("/static/workspace.js").text
    assert 'ui.stopMode === "preview"' in js and '$("stop-banner").hidden = !ui.stopped || preview' in js
