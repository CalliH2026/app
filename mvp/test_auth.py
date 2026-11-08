import importlib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from .auth import install_auth

@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://pronote.example.com')
    monkeypatch.setenv('SESSION_SECRET', 'x' * 48)
    monkeypatch.setenv('ALLOWED_EMAILS', 'teacher@example.com')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'test-client')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'test-secret')
    app = FastAPI()
    @app.get('/')
    def home(): return {'private': True}
    @app.get('/api/workspace')
    def data(): return {'private': True}
    install_auth(app)
    return TestClient(app, base_url='https://pronote.example.com')

def test_private_pages_require_login(hosted):
    assert hosted.get('/', follow_redirects=False).headers['location'] == '/login'
    assert hosted.get('/api/workspace').status_code == 401
    assert hosted.get('/healthz').json() == {'status': 'ok'}
    assert hosted.get('/login').status_code == 200

def test_oauth_sets_secure_state_cookie(hosted, monkeypatch):
    from authlib.integrations.starlette_client.apps import StarletteOAuth2App
    async def metadata(self):
        return {'authorization_endpoint': 'https://accounts.google.com/o/oauth2/v2/auth'}
    monkeypatch.setattr(StarletteOAuth2App, 'load_server_metadata', metadata)
    response = hosted.get('/auth/google', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'].startswith('https://accounts.google.com/')
    cookie = response.headers['set-cookie']
    assert 'httponly' in cookie.lower() and 'secure' in cookie.lower()
    assert 'state=' in response.headers['location']

def test_reject_unknown_host_and_cross_origin_logout(hosted):
    assert hosted.get('/healthz', headers={'host': 'evil.example'}).status_code == 403
    assert hosted.post('/auth/logout', headers={'origin': 'https://evil.example'}).status_code == 403

def test_callback_rejects_missing_state(hosted):
    assert hosted.get('/auth/callback?code=invalid').status_code == 400

def test_hosted_config_fails_closed(monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://pronote.example.com')
    monkeypatch.delenv('SESSION_SECRET', raising=False)
    with pytest.raises(RuntimeError): install_auth(FastAPI())


def test_sites_proxy_access_is_scoped_and_does_not_create_a_session(hosted, monkeypatch):
    monkeypatch.setenv('SITES_PROXY_TOKEN', 's' * 48)
    app = FastAPI()
    @app.get('/api/workspace')
    def data(): return {'fictional': True}
    install_auth(app)
    client = TestClient(app, base_url='https://pronote.example.com')
    assert client.get('/api/workspace').status_code == 401
    assert client.get('/api/workspace', headers={'x-pronote-sites-token':'wrong'}).status_code == 401
    headers = {'x-pronote-sites-token':'s' * 48}
    response = client.get('/api/workspace', headers=headers)
    assert response.status_code == 200
    assert 'set-cookie' not in response.headers
    assert client.get('/api/workspace').status_code == 401
    assert client.get('/api/auth/me', headers=headers).json()['required'] is False
    assert client.get('/api/pronote/connection', headers=headers).status_code == 409
    assert client.post('/auth/logout', headers={**headers, 'origin':'https://evil.example'}).status_code == 403

@pytest.mark.parametrize('email,verified,expected', [
    ('teacher@example.com', True, 303),
    ('teacher@example.com', False, 403),
    ('other@example.com', True, 403),
])
def test_callback_identity_and_email_allowlist(hosted, monkeypatch, email, verified, expected):
    from authlib.integrations.starlette_client.apps import StarletteOAuth2App
    async def token(self, request):
        return {'userinfo': {'sub': 'google-user', 'email': email, 'email_verified': verified, 'name': 'Teacher'}}
    monkeypatch.setattr(StarletteOAuth2App, 'authorize_access_token', token)
    response = hosted.get('/auth/callback?code=test', follow_redirects=False)
    assert response.status_code == expected
    assert hosted.get('/api/workspace').status_code == (200 if expected == 303 else 401)
    if expected == 303:
        hosted.post('/auth/logout', headers={'origin': 'https://pronote.example.com'}, follow_redirects=False)
        assert hosted.get('/api/workspace').status_code == 401


@pytest.mark.parametrize('path,method', [
    ('/api/pronote/connection', 'GET'),
    ('/api/pronote/connection/options', 'GET'),
    ('/api/pronote/connection/connect', 'POST'),
    ('/api/pronote/connection/sync', 'POST'),
    ('/api/pronote/connection/disconnect', 'POST'),
])
def test_real_pronote_connection_stays_local_after_hosted_login(hosted, monkeypatch, path, method):
    from authlib.integrations.starlette_client.apps import StarletteOAuth2App

    async def token(self, request):
        return {'userinfo': {'sub': 'google-user', 'email': 'teacher@example.com',
                             'email_verified': True, 'name': 'Teacher'}}

    monkeypatch.setattr(StarletteOAuth2App, 'authorize_access_token', token)
    assert hosted.get('/auth/callback?code=test', follow_redirects=False).status_code == 303
    response = hosted.request(method, path, headers={'origin': 'https://pronote.example.com'})
    assert response.status_code == 409
    assert response.json()['detail'] == 'Cette fonction nécessite le compagnon local.'
