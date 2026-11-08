"""--runtime managed|local for the native writer, offline: the SDK is a recording stand-in (test double only)."""

from __future__ import annotations

import base64
import json
import sys
import types

import pytest

from agent import run_writer
from agent.queue_store import QueueStore

TEXT = "Bon trimestre, des progrès nets à l'écrit."
PNG = base64.b64encode(b"\x89PNG fake bytes").decode()


class Sdk:
    def __init__(self, result=None, error: Exception | None = None, hand_out: bool = False):
        self.local = self.managed = self.closed = 0
        self.kwargs: dict = {}
        sdk = self

        class Client:
            def __init__(self, **kw):
                sdk.managed += 1

            @classmethod
            def local(cls, **kw):
                sdk.local += 1
                c = cls.__new__(cls)
                return c

            def run_session(self, *, tools, **kw):
                sdk.kwargs = kw
                if hand_out:
                    tools[0]()
                if error:
                    raise error
                return result

            def close(self):
                sdk.closed += 1

        self.module = types.SimpleNamespace(Client=Client)


def _result(status="completed", events=(), error_code=None):
    return types.SimpleNamespace(id="sess-local-1", status=status, outcome=None, error=None, error_code=error_code,
                                 answer="done", events=list(events))


def _run(tmp_path, monkeypatch, sdk, *extra, target="pronote"):
    monkeypatch.setitem(sys.modules, "hai_agents", sdk.module)
    monkeypatch.setenv("HAI_API_KEY", "hk-writer-test-only")
    store = QueueStore(tmp_path / "queue.jsonl")
    store.append({"item_id": "q1", "student": "Lucas Bernard", "text": TEXT})
    run_dir = tmp_path / "run"
    code = run_writer.main(["--queue", str(store.path), "--target", target, "--run-dir", str(run_dir),
                            "--idle-timeout", "0", *extra])
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return code, summary, store, run_dir


def test_local_runtime_uses_client_local_inline_desktop_and_closes_after_artifacts(tmp_path, monkeypatch):
    shot = {"type": "observation", "image": {"type": "image", "source": f"data:image/png;base64,{PNG}"},
            "text": "Authorization: Bearer hk-writer-test-only"}
    sdk = Sdk(_result(events=[shot]))
    code, summary, _, run_dir = _run(tmp_path, monkeypatch, sdk, "--runtime", "local")
    assert sdk.local == 1 and sdk.managed == 0 and sdk.closed == 1
    [env] = sdk.kwargs["agent"]["environments"]
    assert env == {"id": "desktop", "kind": "desktop", "host": "user_device"}
    assert summary["runtime"] == "local" and summary["screenshots"] == 1 and summary["provider_ok"] is True
    assert (run_dir / "screenshots" / "0001.png").read_bytes() == b"\x89PNG fake bytes"
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "screenshots/0001.png" in events and "hk-writer-test-only" not in events and PNG not in events
    assert code == 0  # nothing was handed out and the session completed


def test_default_stays_managed_and_does_not_close(tmp_path, monkeypatch):
    sdk = Sdk(_result())
    _, summary, _, _ = _run(tmp_path, monkeypatch, sdk, target="moodle")
    assert sdk.managed == 1 and sdk.local == 0 and sdk.closed == 0 and summary["runtime"] == "managed"


@pytest.mark.parametrize("extra, target", [(["--runtime", "local", "--desktop-session-id", "abc"], "pronote"),
                                           (["--runtime", "local"], "moodle")])
def test_conflicting_runtime_arguments_are_refused_before_any_client(tmp_path, monkeypatch, extra, target):
    sdk = Sdk(_result())
    monkeypatch.setitem(sys.modules, "hai_agents", sdk.module)
    monkeypatch.setenv("HAI_API_KEY", "hk-writer-test-only")
    with pytest.raises(SystemExit) as exc:
        run_writer.main(["--items", str(tmp_path / "x.csv"), "--target", target, *extra])
    assert exc.value.code == 2 and sdk.local == sdk.managed == 0


def test_provider_failure_with_zero_items_is_not_success(tmp_path, monkeypatch):
    sdk = Sdk(_result(status="failed", error_code="internal"))
    code, summary, store, _ = _run(tmp_path, monkeypatch, sdk, "--runtime", "local")
    assert code == 1 and summary["provider_ok"] is False and summary["items"] == {}
    assert store.get("q1")["status"] == "pending" and sdk.closed == 1


def test_session_exception_settles_the_handed_out_item_as_unknown_and_still_closes(tmp_path, monkeypatch):
    sdk = Sdk(error=RuntimeError("bridge lost, token=hk-writer-test-only"), hand_out=True)
    code, summary, store, run_dir = _run(tmp_path, monkeypatch, sdk, "--runtime", "local")
    assert code == 1 and summary["status"] == "client_error" and summary["session_id"] is None
    assert summary["client_error"]["error_type"] == "RuntimeError"
    assert "hk-writer-test-only" not in (run_dir / "summary.json").read_text(encoding="utf-8")
    assert store.get("q1")["status"] == "unknown" and summary["items"] == {"unknown": 1} and sdk.closed == 1


class FakeHttp:
    def __init__(self, status=200, kind="image/png"):
        self.calls: list[tuple[str, dict]] = []
        self.status, self.kind = status, kind

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return types.SimpleNamespace(status_code=self.status, headers={"content-type": self.kind}, content=b"img")


def _fetcher(base="http://127.0.0.1:5123", **http):
    fake = FakeHttp(**http)
    client = types.SimpleNamespace(local_runtime=types.SimpleNamespace(base_url=base),
                                   _client_wrapper=types.SimpleNamespace(httpx_client=types.SimpleNamespace(httpx_client=fake)))
    return run_writer.local_fetcher(client), fake


def test_local_fetcher_fetches_same_origin_images_without_redirects():
    fetch, http = _fetcher()
    assert fetch("http://127.0.0.1:5123/v1/sessions/s/screenshots/1.png") == b"img"
    assert http.calls[0][1] == {"follow_redirects": False}


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:5123.evil.test/1.png",      # lookalike host
    "http://127.0.0.1:5123@evil.test/1.png",      # userinfo: real host is evil.test
    "http://user:pw@127.0.0.1:5123/1.png",        # credentials in the URL
    "http://127.0.0.1:5124/1.png",                # other port
    "https://127.0.0.1:5123/1.png",               # other scheme
    "http://127.0.0.1/1.png",                     # default port 80 is not 5123
    "http://localhost:5123/1.png",                # other host name
    "ftp://127.0.0.1:5123/1.png",
])
def test_local_fetcher_never_sends_runtime_credentials_off_origin(url):
    fetch, http = _fetcher()
    assert fetch(url) is None and http.calls == []


def test_local_fetcher_respects_the_base_path_boundary():
    fetch, http = _fetcher(base="http://127.0.0.1:5123/rt/")
    assert fetch("http://127.0.0.1:5123/rtx/1.png") is None and http.calls == []
    assert fetch("http://127.0.0.1:5123/rt/1.png") == b"img"


@pytest.mark.parametrize("status, kind", [(302, "image/png"), (200, "text/html"), (200, "application/json")])
def test_local_fetcher_keeps_only_direct_image_responses(status, kind):
    fetch, _ = _fetcher(status=status, kind=kind)
    assert fetch("http://127.0.0.1:5123/1.png") is None


def test_local_fetcher_without_a_local_runtime_fetches_nothing():
    fetch = run_writer.local_fetcher(types.SimpleNamespace())
    assert fetch("http://127.0.0.1:5123/1.png") is None


def test_raw_base64_image_source_is_saved_as_a_screenshot(tmp_path):
    events = [{"type": "observation", "image": {"type": "base64", "media_type": "image/png", "source": PNG}}]
    assert run_writer.save_events(events, tmp_path, lambda url: None) == 1
    assert (tmp_path / "screenshots" / "0001.png").read_bytes() == b"\x89PNG fake bytes"
    row = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert PNG not in row and "screenshots/0001.png" in row and "image/png" in row


@pytest.mark.parametrize("path", ["/rt/../other.png", "/rt/%2e%2e/other.png", "/rt/./../x.png", "/rt/..%2fx.png",
                                  "/rt/%2E%2E/x.png", "/rt\\..\\x.png"])
def test_local_fetcher_rejects_dot_segments_that_escape_the_base_path(path):
    fetch, http = _fetcher(base="http://127.0.0.1:5123/rt")
    assert fetch("http://127.0.0.1:5123" + path) is None and http.calls == []
