from fastapi.testclient import TestClient
from .server import create_app

class Runtime:
    def __init__(self): self.stopped=False
    async def start(self,url): self.url=url
    async def capture(self): return {'visible_text':'Agenda réel'}
    async def stop(self): self.stopped=True


def test_local_session_and_explicit_capture():
    runtime=Runtime()
    client=TestClient(create_app(runtime,'http://127.0.0.1:8765'),base_url='http://127.0.0.1:8765')
    assert client.get('/api/config').status_code==401
    assert client.get('/',headers={'Host':'evil.test'}).status_code==403
    assert client.get('/').status_code==200
    assert client.post('/api/capture',json={'authenticated':True}).status_code==403
    assert client.post('/api/capture',json={'authenticated':True},headers={'Origin':'https://evil.test'}).status_code==403
    headers={'Origin':'http://127.0.0.1:8765'}
    assert client.post('/api/capture',json={},headers=headers).status_code==400
    assert client.post('/api/capture',json={'authenticated':True},headers=headers).json()['visible_text']=='Agenda réel'
    assert client.post('/api/stop',headers=headers).status_code==200
    assert runtime.stopped


def test_connection_api_requires_local_session_and_keeps_secrets_private(tmp_path, monkeypatch):
    from .. import pilot
    monkeypatch.setattr(pilot, 'DATA', tmp_path)
    app = create_app(Runtime(), 'http://127.0.0.1:8766')
    client = TestClient(app, base_url='http://127.0.0.1:8766')
    assert client.get('/api/pronote/connection').status_code == 401
    client.get('/')
    headers = {'Origin': 'http://127.0.0.1:8766'}
    assert client.get('/api/pronote/connection').headers['cache-control'] == 'no-store'
    assert client.post('/api/pronote/connection/disconnect', json={}).status_code == 403
    result = client.post('/api/pronote/connection/connect', headers=headers, json={
        'web_url': 'https://127.0.0.1/pronote/professeur.html',
        'username': 'test-user', 'password': 'never-return-this-password',
    })
    assert result.status_code == 200 and result.json()['state'] == 'error'
    assert 'never-return-this-password' not in result.text
    assert client.post('/api/pronote/connection/disconnect', json={}, headers=headers).json()['data'] == {}
    app.state.pronote_connection.close()
