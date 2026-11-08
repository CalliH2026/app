"""Connection scheduling, private HTTP responses and manual-browser routing."""
import json
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .pilot import PilotConfig, browser_url
from .pronote_connection import ConnectRequest, ConnectionManager, install_routes


class Connector:
    def __init__(self):
        self.connected = False
        self.synced = threading.Event()
        self.resumed = threading.Event()
        self.calls = []

    def status(self):
        return {'state': 'connected' if self.connected else 'disconnected',
                'connected': self.connected, 'message': 'Prêt', 'data': {}}

    def connect(self, value):
        self.calls.append(('connect', value))
        self.connected = True
        return self.status()

    def sync(self):
        self.calls.append(('sync', None))
        self.synced.set()
        return self.status()

    def resume(self):
        self.resumed.set()
        return self.status()

    def disconnect(self):
        self.connected = False
        self.calls.append(('disconnect', None))
        return self.status()

    def close(self):
        self.connected = False


def test_sync_preferences_are_private_and_do_not_store_credentials(tmp_path):
    connector = Connector()
    manager = ConnectionManager(tmp_path, connector)
    try:
        manager.connect(ConnectRequest(web_url='https://school.example/pronote/eleve.html',
                                       password='private-password', username='private-user',
                                       qr_code='private-qr', pin='private-pin',
                                       interval_seconds=900, auto_sync=False))
        file = tmp_path / 'pronote-sync-preferences.json'
        assert json.loads(file.read_text()) == {'auto_sync': False, 'interval_seconds': 900}
        assert file.stat().st_mode & 0o777 == 0o600
        assert 'private-' not in file.read_text()
        assert connector.calls[0][1]['password'] == 'private-password'
        restored = ConnectionManager(tmp_path, Connector())
        assert restored.status()['interval_seconds'] == 900
        assert restored.status()['auto_sync'] is False
    finally:
        manager.close()


def test_background_sync_stops_and_cannot_sync_disconnected_account(tmp_path):
    connector = Connector()
    manager = ConnectionManager(tmp_path, connector)
    connector.connected = True
    manager.interval_seconds = .01
    manager.start(resume=False)
    try:
        assert connector.synced.wait(1), 'Scheduler did not synchronize the connected account'
        manager.disconnect()
        with manager._operation:
            connector.synced.clear()
        assert not connector.synced.wait(.05), 'Disconnected account was synchronized'
    finally:
        manager.close()
    assert not manager._thread.is_alive()


def test_start_resumes_once_without_recreating_worker(tmp_path):
    connector = Connector()
    manager = ConnectionManager(tmp_path, connector)
    try:
        manager.start()
        worker = manager._thread
        assert connector.resumed.wait(1)
        manager.start()
        assert manager._thread is worker
    finally:
        manager.close()


def test_scheduler_retries_transient_errors_but_not_login_failures(tmp_path):
    class Recoverable(Connector):
        state = 'error'

        def status(self):
            return {'state': self.state, 'connected': self.connected,
                    'retryable': self.state == 'error', 'data': {}}

        def sync(self):
            self.state, self.connected = 'connected', True
            return super().sync()

    connector = Recoverable()
    manager = ConnectionManager(tmp_path, connector)
    manager.interval_seconds = .01
    manager.start(resume=False)
    try:
        assert connector.synced.wait(1), 'Transient error was never retried'
        with manager._operation:
            connector.state, connector.connected = 'needs_login', False
            connector.synced.clear()
        assert not connector.synced.wait(.05), 'Rejected credentials were retried automatically'
    finally:
        manager.close()


@pytest.fixture
def connection_http(tmp_path, monkeypatch):
    monkeypatch.delenv('PUBLIC_URL', raising=False)
    manager = ConnectionManager(tmp_path, Connector())
    app = FastAPI()
    install_routes(app, manager)
    yield TestClient(app), manager
    manager.close()


def test_status_is_not_cached_and_validation_never_echoes_secrets(connection_http):
    client, _ = connection_http
    response = client.get('/api/pronote/connection')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    secret = 'do-not-return-this-secret'
    response = client.post('/api/pronote/connection/connect', json={
        'web_url': 'https://school.example/pronote/eleve.html',
        'password': secret, 'pin': secret, 'qr_code': secret, 'account_type': 'invalid',
    })
    assert response.status_code == 422
    assert secret not in response.text
    assert response.headers['cache-control'] == 'no-store'


def test_service_exceptions_are_not_exposed(connection_http):
    client, manager = connection_http
    def fail(value):
        raise ValueError('private-password private-qr private-session')
    manager.connector.connect = fail
    response = client.post('/api/pronote/connection/connect', json={
        'web_url': 'https://school.example/pronote/eleve.html', 'password': 'private-password',
    })
    assert response.status_code == 400
    assert 'private-' not in response.text


def test_hosted_connection_is_blocked_even_without_auth_plugin(connection_http, monkeypatch):
    client, connector = connection_http
    monkeypatch.setenv('PUBLIC_URL', 'https://shared.example')
    assert client.get('/api/pronote/connection').status_code == 409
    assert client.post('/api/pronote/connection/sync', json={}).status_code == 409
    assert client.post('/api/pronote/connection/disconnect', json={}).status_code == 409


def test_browser_direct_access_is_explicit_and_not_saved_as_session_query():
    url = 'https://school.example/pronote/professeur.html'
    direct = PilotConfig(connection_mode='web', web_url=url, auth_route='direct')
    ent = PilotConfig(connection_mode='web', web_url=url, auth_route='ent')
    assert browser_url(direct) == url + '?login=true'
    assert browser_url(ent) == url
    assert direct.model_dump()['web_url'] == url
