"""No PRONOTE account or live network is used by these connector tests."""
import datetime as dt
import io
import json
import logging
import os
import socket
from types import SimpleNamespace as NS

import pytest

from . import pronote_connector as pc


URL = "https://school.example.org/pronote/eleve.html"


def public_dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port))]


class FakeSession:
    closed = False

    def close(self):
        self.closed = True


class FakeClient:
    instances = []
    fail = False
    exports = 0

    def __init__(self, pronote_url, username="", password="", ent=None, mode="normal", uuid="", **kwargs):
        self.pronote_url, self.username, self.password = pronote_url, username, password
        self.login_mode, self.uuid = mode, uuid
        self.client_identifier = "private-device-id"
        self.account_pin = ""
        self.auth_cookie = {"private": "cookie"}
        self.communication = NS(session=FakeSession())
        self.logged_in = not self.fail
        self.calls = []
        self.info = NS(name="Élève test", class_name="4e A", establishment="Collège test")
        self.children = [NS(name="Premier enfant", class_name="4e A"), NS(name="Second enfant", class_name="6e B")]
        self.selected_child = None
        self.__class__.instances.append(self)

    @classmethod
    def qrcode_login(cls, qr_code, pin, uuid, **kwargs):
        return cls(qr_code["url"].replace("/eleve.html", "/mobile.eleve.html"),
                   username="private-qr-login", password="private-token-1", mode="token", uuid=uuid)

    @classmethod
    def token_login(cls, **kwargs):
        kwargs["password"] = kwargs["password"] + "-rotated"
        return cls(mode="token", **kwargs)

    def export_credentials(self):
        self.__class__.exports += 1
        return {"pronote_url": self.pronote_url, "username": self.username, "password": self.password,
                "uuid": self.uuid, "client_identifier": self.client_identifier}

    def session_check(self):
        self.calls.append("session_check")
        return False

    def set_child(self, child):
        self.calls.append("set_child")
        self.selected_child = child

    def lessons(self, start, end):
        self.calls.append(("lessons", start, end))
        return [NS(subject=NS(name="Mathématiques"), start=dt.datetime(2026, 11, 9, 9),
                   end=dt.datetime(2026, 11, 9, 10), classroom="12", teacher_name="Professeur test",
                   canceled=False)] * 300

    def homework(self, start, end):
        self.calls.append(("homework", start, end))
        return [NS(subject=NS(name="Mathématiques"), date=start, description="Exercice 1", done=False)]

    @property
    def current_period(self):
        self.calls.append("grades")
        return NS(grades=[NS(subject=NS(name="Mathématiques"), date=dt.date(2026, 11, 5),
                             grade="15", out_of="20", coefficient="1", comment="Contrôle")])


class TeacherClient(FakeClient):
    def lessons(self, *_):
        raise AssertionError("Student APIs must not be called for teachers")

    def homework(self, *_):
        raise AssertionError("Student APIs must not be called for teachers")

    @property
    def current_period(self):
        raise AssertionError("Student APIs must not be called for teachers")


@pytest.fixture
def module():
    FakeClient.instances = []
    FakeClient.fail = False
    FakeClient.exports = 0
    TeacherClient.instances = []
    TeacherClient.fail = False
    return NS(Client=FakeClient, ParentClient=FakeClient, ClientBase=TeacherClient,
              ent=NS(cas_kosmos=lambda *_: None))


@pytest.fixture
def connector(tmp_path, module):
    return pc.PronoteConnector(tmp_path, client_module=module, resolver=public_dns)


def password_config(**changes):
    return {"web_url": URL, "account_type": "student", "auth_method": "password",
            "username": "private-real-login", "password": "private-real-password", **changes}


def qr_config(**changes):
    return {"web_url": URL, "account_type": "student", "auth_method": "qr", "pin": "4321",
            "qr_code": json.dumps({"url": URL, "login": "ab" * 16, "jeton": "cd" * 32}), **changes}


def test_options_are_offline_and_ui_contract(monkeypatch):
    monkeypatch.setattr(pc.importlib, "import_module", lambda *_: pytest.fail("Options imported a dependency"))
    monkeypatch.setattr(pc.socket, "getaddrinfo", lambda *_: pytest.fail("Options attempted DNS"))
    options = pc.connection_options()
    assert options["available"] and options["read_only"] and options["unofficial"]
    assert {item["id"] for item in options["accounts"]} == {"teacher", "student", "parent"}
    assert {item["id"] for item in options["auth_methods"]} == {"password", "qr"}
    assert len(options["ents"]) > 1


@pytest.mark.parametrize("url", [
    "http://school.example.org/pronote/eleve.html",
    "https://user:secret@school.example.org/pronote/eleve.html",
    "https://school.example.org/pronote/eleve.html?token=private",
    "https://school.example.org/pronote/eleve.html#private",
    "https://school.example.org:8443/pronote/eleve.html",
    "https://127.0.0.1/pronote/eleve.html",
    "https://169.254.169.254/pronote/eleve.html",
    "https://[::1]/pronote/eleve.html",
    "https://localhost/pronote/eleve.html",
    "https://machine.local/pronote/eleve.html",
    "https://metadata.google.internal/pronote/eleve.html",
    "https://school.example.org./pronote/eleve.html",
    "https://school.example.org/pronote/../eleve.html",
    "https://school.example.org/pronote/%2e%2e/eleve.html",
    "https://school.example.org/pronote/%252e%252e/eleve.html",
    "https://school.example.org/pronote/parent.html",
    "https://school.example.org/anything/eleve.html",
    "https://school.example.org/pronote/eleve.html\n",
])
def test_rejects_invalid_url_before_client_or_credentials(connector, url):
    status = connector.connect(password_config(web_url=url))
    assert status["state"] == "error" and not status["connected"]
    assert FakeClient.instances == []
    assert not connector.session_file.exists()
    assert "private-real-password" not in json.dumps(status)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "192.168.1.5", "169.254.169.254", "0.0.0.0", "224.0.0.1", "100.64.0.1"])
def test_private_dns_answers_are_refused(tmp_path, module, ip):
    def resolver(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    service = pc.PronoteConnector(tmp_path, client_module=module, resolver=resolver)
    assert service.connect(password_config())["state"] == "error"
    assert FakeClient.instances == []


def test_any_private_dns_answer_is_refused():
    def mixed(host, port, **kw):
        return public_dns(host, port) + [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", port, 0, 0))]
    with pytest.raises(pc.ConnectorError):
        pc.validate_web_url(URL, "student", mixed)


def test_password_login_sync_is_bounded_without_secret_persistence(connector):
    status = connector.connect(password_config(remember_session=True))
    assert status["connected"] and status["state"] == "connected"
    assert status["capabilities"] == ["profile", "lessons", "homework", "grades"]
    assert status["data"]["counts"]["lessons"] == pc.MAX_ITEMS
    assert status["last_sync_at"]
    assert "4321" not in json.dumps(status)
    assert "private-real-password" not in json.dumps(status)
    assert "private-real-login" not in json.dumps(status)
    assert "private-device-id" not in json.dumps(status)
    assert not connector.session_file.exists()
    assert FakeClient.exports == 0  # Normal export would contain the real password.
    client = FakeClient.instances[-1]
    assert client.pronote_url == URL + "?login=true"
    for call in client.calls:
        if isinstance(call, tuple):
            assert (call[2] - call[1]).days == 14
    status["data"]["profile"]["name"] = "mutated"
    assert connector.status()["data"]["profile"]["name"] == "Élève test"
    assert connector.sync()["connected"]
    assert "session_check" in client.calls


def test_teacher_uses_base_auth_profile_only_and_checks_session(connector):
    status = connector.connect(password_config(account_type="teacher", web_url=URL.replace("eleve", "professeur")))
    assert status["connected"] and status["capabilities"] == ["profile"]
    assert not status["data"]["lessons"] and not status["data"]["grades"]
    assert "professeur" in status["message"] and status["warnings"]
    assert FakeClient.instances == []
    assert connector.sync()["connected"]
    assert "session_check" in TeacherClient.instances[-1].calls


def test_parent_snapshot_reselects_only_first_child(connector):
    status = connector.connect(password_config(account_type="parent", web_url=URL.replace("eleve", "parent")))
    assert status["connected"] and status["data"]["selected_child"] == "Premier enfant"
    assert len(status["data"]["children"]) == 2
    client = FakeClient.instances[-1]
    assert client.selected_child is client.children[0]
    client.selected_child = client.children[1]
    connector.sync()
    assert client.selected_child is client.children[0]


def test_qr_is_not_remembered_by_default_and_never_exposed(connector):
    status = connector.connect(qr_config())
    assert status["connected"] and not status["remembered_session"]
    assert "private-token" not in json.dumps(status)
    assert "ab" * 16 not in json.dumps(status)
    assert not connector.session_file.exists()


def test_qr_remember_resume_rotates_token_close_preserves_disconnect_forgets(connector, tmp_path, module):
    assert connector.connect(qr_config(remember_session=True))["connected"]
    assert connector.session_file.stat().st_mode & 0o777 == 0o600
    first = json.loads(connector.session_file.read_text())
    assert first["token"] == "private-token-1" and "password" not in first
    assert first["token_url"].endswith("?" + pc._TOKEN_QUERY)
    connector.close()
    assert connector.status()["data"] == {} and connector.session_file.exists()
    restored = pc.PronoteConnector(tmp_path, client_module=module, resolver=public_dns)
    status = restored.resume()
    assert status["connected"] and status["remembered_session"]
    second = json.loads(restored.session_file.read_text())
    assert second["token"] == "private-token-1-rotated"
    assert second["uuid"] == first["uuid"]
    assert "private-token" not in json.dumps(status)
    restored.disconnect()
    assert not restored.session_file.exists() and restored.status()["data"] == {}
    assert restored.resume()["state"] == "disconnected"


def test_token_rotation_during_periodic_sync_is_saved(connector):
    connector.connect(qr_config(remember_session=True))
    client = FakeClient.instances[-1]
    client.session_check = lambda: setattr(client, "password", "replacement-mobile-token")
    assert connector.sync()["connected"]
    assert json.loads(connector.session_file.read_text())["token"] == "replacement-mobile-token"


def test_qr_for_another_account_or_host_never_authenticates(connector):
    qr = {"url": "https://another.example.org/pronote/eleve.html", "login": "ab" * 16, "jeton": "cd" * 32}
    status = connector.connect(qr_config(qr_code=qr))
    assert status["state"] == "error" and FakeClient.instances == []


def test_account_switch_clears_old_snapshot_and_saved_token_even_when_new_login_fails(connector):
    connector.connect(qr_config(remember_session=True))
    previous = FakeClient.instances[-1]
    FakeClient.fail = True
    status = connector.connect(password_config())
    assert status["state"] == "needs_login" and not status["connected"]
    assert status["data"] == {} and status["last_sync_at"] is None
    assert previous.communication.session.closed and previous.password == ""
    assert not connector.session_file.exists()


def test_errors_never_return_remote_exception_text(connector, module):
    class Broken(FakeClient):
        def __init__(self, *args, **kwargs):
            raise RuntimeError("private-real-password private-token https://user:secret@host/")
    module.Client = Broken
    status = connector.connect(password_config())
    assert status["state"] == "needs_login"
    for forbidden in ("private-real-password", "private-token", "user:secret"):
        assert forbidden not in json.dumps(status)


def test_optional_read_failure_reports_actual_capabilities_without_secret_error(connector):
    connector.connect(password_config())
    client = FakeClient.instances[-1]

    UnsupportedOperation = type("UnsupportedOperation", (Exception,), {})
    def denied(*_):
        raise UnsupportedOperation("server exception containing private token")
    client.homework = denied
    status = connector.sync()
    assert status["connected"] and "homework" not in status["capabilities"]
    assert status["data"]["homework"] == [] and status["warnings"]
    assert "private token" not in json.dumps(status)


def test_expired_auth_requests_login_and_never_reports_success(connector):
    connector.connect(password_config())
    client = FakeClient.instances[-1]
    CryptoError = type("CryptoError", (Exception,), {})

    def expired():
        raise CryptoError("private-real-password")
    client.session_check = expired
    status = connector.sync()
    assert status["state"] == "needs_login" and not status["connected"]
    assert "private-real-password" not in json.dumps(status)


def test_saved_file_permissions_and_symlink_are_rejected(connector, tmp_path):
    connector.session_file.write_text('{"version": 1}')
    connector.session_file.chmod(0o644)
    assert connector.resume()["state"] == "needs_login"
    connector.session_file.unlink()
    outside = tmp_path / "other.json"
    outside.write_text("secret")
    outside.chmod(0o600)
    connector.session_file.symlink_to(outside)
    assert connector.resume()["state"] == "needs_login"
    assert outside.read_text() == "secret"


def test_saved_token_foreign_host_cannot_receive_credentials(connector, module):
    connector.connect(qr_config(remember_session=True))
    saved = json.loads(connector.session_file.read_text())
    connector.close()
    FakeClient.instances.clear()
    saved["token_url"] = "https://attacker.example.org/pronote/mobile.eleve.html"
    connector.session_file.write_text(json.dumps(saved))
    connector.session_file.chmod(0o600)
    assert connector.resume()["state"] == "needs_login"
    assert FakeClient.instances == []


def test_controlled_ent_adapter_and_unknown_ent(connector):
    assert connector.connect(password_config(ent="cas_kosmos"))["connected"]
    assert FakeClient.instances[-1].pronote_url == URL
    before = len(FakeClient.instances)
    assert connector.connect(password_config(ent="https://arbitrary.example.org"))["state"] == "error"
    assert len(FakeClient.instances) == before


def test_network_policy_rejects_redirects_before_request_and_enforces_budget():
    policy = pc._NetworkPolicy(URL, "cas_kosmos", public_dns)
    policy.check_url(URL + "?login=true")
    policy.check_url("https://cas.kosmoseducation.com/login?service=" + URL)
    for target in ("https://attacker.example.org/", "http://school.example.org/pronote/eleve.html",
                   "https://school.example.org/secret", "https://school.example.org/pronote/../secret",
                   "https://localhost/pronote/eleve.html"):
        with pytest.raises(pc.ConnectorError):
            policy.check_url(target)
    policy.requests = pc.MAX_REQUESTS
    with pytest.raises(pc.ConnectorError):
        policy.check_url(URL)


def test_actual_tcp_connection_pins_public_answer_and_rechecks_dns(monkeypatch):
    connected = []

    class FakeSocket:
        def __init__(self, *args):
            pass
        def setsockopt(self, *args):
            pass
        def settimeout(self, timeout):
            assert 0 < timeout <= 5
        def connect(self, addr):
            connected.append(addr)
        def close(self):
            pass

    monkeypatch.setattr(pc.socket, "socket", FakeSocket)
    policy = pc._NetworkPolicy(URL, "", public_dns)
    policy.connect_socket(("school.example.org", 443), 5, None, None)
    assert connected == [("93.184.216.34", 443)]  # No hostname is passed to connect.
    policy.resolver = lambda *args, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    with pytest.raises(pc.ConnectorError):
        policy.connect_socket(("school.example.org", 443), 5, None, None)
    assert len(connected) == 1


def test_transport_guards_each_redirect_disables_env_and_bounds_body(monkeypatch):
    import requests
    from urllib3.util import connection as urllib_connection

    # Reinstall against a fake underlying adapter, and restore global wrappers
    # afterwards. No real socket or external request can be opened by this test.
    pc._install_transport_guard()
    original_send = requests.adapters.HTTPAdapter.send
    original_init = requests.sessions.Session.__init__
    original_connect = urllib_connection.create_connection
    calls = []

    def adapter_send(adapter, request, **kwargs):
        calls.append((request.url, kwargs))
        response = requests.Response()
        response.url, response.request = request.url, request
        response.status_code = 302 if len(calls) == 1 else 200
        response.headers["location"] = "https://127.0.0.1/pronote/eleve.html" if len(calls) == 1 else ""
        response.raw = io.BytesIO(b"safe body")
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", adapter_send)
    monkeypatch.setattr(pc, "_TRANSPORT_INSTALLED", False)
    try:
        policy = pc._NetworkPolicy(URL, "", public_dns)
        with pc._network(policy):
            session = requests.Session()
            assert session.trust_env is False and session.max_redirects == 5
            with pytest.raises(pc.ConnectorError):
                session.get(URL)
        assert len(calls) == 1  # Redirect target was never sent to the adapter.
        assert calls[0][1]["timeout"] == (5, 10)
        assert calls[0][1]["proxies"] == {} and calls[0][1]["verify"] is True
        calls.clear()
        monkeypatch.setattr(pc, "MAX_BODY_BYTES", 2)
        with pc._network(pc._NetworkPolicy(URL, "", public_dns)):
            with pytest.raises(pc.ConnectorError, match="volumineuse"):
                requests.Session().get(URL, allow_redirects=False)
    finally:
        requests.adapters.HTTPAdapter.send = original_send
        requests.sessions.Session.__init__ = original_init
        urllib_connection.create_connection = original_connect
        pc._TRANSPORT_INSTALLED = True


def test_library_logging_is_disabled_without_contacting_account():
    pytest.importorskip("pronotepy")
    module = pc._load_pronotepy()
    assert module.ClientBase and module.ParentClient
    for name in ("pronotepy.pronoteAPI", "pronotepy.ent.generic_func"):
        assert logging.getLogger(name).disabled


def test_transient_network_failure_preserves_snapshot_and_allows_retry(connector):
    previous = connector.connect(password_config())
    client = FakeClient.instances[-1]
    original = client.lessons

    def offline(*_):
        raise OSError("private-real-password network failure")
    client.lessons = offline
    failed = connector.sync()
    assert failed["state"] == "error" and failed["retryable"] and not failed["connected"]
    assert failed["last_sync_at"] == previous["last_sync_at"]
    assert failed["data"] == previous["data"]
    assert not client.communication.session.closed
    assert "private-real-password" not in json.dumps(failed)
    client.lessons = original
    recovered = connector.sync()
    assert recovered["state"] == "connected" and not recovered["retryable"]


def test_resume_network_failure_retries_saved_token_on_next_sync(connector, module):
    connector.connect(qr_config(remember_session=True))
    connector.close()
    original = module.Client

    class Offline(FakeClient):
        @classmethod
        def token_login(cls, **kwargs):
            raise OSError("network unavailable private-token")
    module.Client = Offline
    failed = connector.resume()
    assert failed["state"] == "error" and failed["retryable"] and not failed["connected"]
    assert failed["remembered_session"] and "private-token" not in json.dumps(failed)
    module.Client = original
    assert connector.sync()["connected"]


def test_disconnect_releases_upstream_global_period_references(connector, module):
    module.Period = NS(instances=set())
    connector.connect(password_config())
    client = FakeClient.instances[-1]
    period = type("Period", (), {})()
    period._client = client
    other = type("Period", (), {})()
    other._client = object()
    module.Period.instances.update((period, other))
    connector.disconnect()
    assert module.Period.instances == {other}
    assert client.password == "" and client.auth_cookie == {}


def test_failed_constructor_releases_leaked_upstream_period_client(connector, module):
    module.Period = NS(instances=set())

    class Broken(FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            period = type("Period", (), {})()
            period._client = self
            module.Period.instances.add(period)
            raise RuntimeError("private-real-password")
    module.Client = Broken
    result = connector.connect(password_config())
    assert result["state"] == "needs_login"
    assert module.Period.instances == set()
    assert Broken.instances[-1].password == ""
    assert Broken.instances[-1].communication.session.closed


def test_resume_dns_outage_is_retryable_without_requesting_new_credentials(connector):
    connector.connect(qr_config(remember_session=True))
    connector.close()
    def offline_dns(*args, **kwargs):
        raise socket.gaierror("temporary name resolution failure")
    connector._resolver = offline_dns
    status = connector.resume()
    assert status["state"] == "error" and status["retryable"]
    assert status["remembered_session"] and not status["connected"]
