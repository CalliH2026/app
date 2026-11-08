"""Optional Calli module: off without configuration, clearly unavailable when misconfigured, mounted otherwise."""
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from . import calli_module

FAKE_APP = '''
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

def create_app(queue_path, roster_path, course, **kwargs):
    app = FastAPI()
    seen = {"queue": str(queue_path), "roster": str(roster_path), "course": course, **{k: str(v) for k, v in kwargs.items()}}

    @app.get("/workspace")
    def workspace():
        return HTMLResponse('<script src="static/workspace.js"></script>')

    @app.get("/api/state")
    def state():
        return seen
    return app
'''
FAKE_DICTATION = '''
def speech_availability(factory):
    return {"available": False, "reason": "GLADIA_API_KEY absent"}
'''
ENV = {'CALLI_QUEUE': 'q.jsonl', 'CALLI_ROSTER': 'roster.csv', 'CALLI_COURSE': '3A, FRANCAIS, Trimestre 1'}


@pytest.fixture
def fake_calli(tmp_path):
    # Any real Calli 'ui' package already imported in this process is set aside and restored afterwards.
    saved = {name: sys.modules.pop(name) for name in [m for m in sys.modules if m == 'ui' or m.startswith('ui.')]}
    (tmp_path / 'ui').mkdir()
    (tmp_path / 'ui' / '__init__.py').write_text('')
    (tmp_path / 'ui' / 'app.py').write_text(FAKE_APP)
    (tmp_path / 'ui' / 'dictation.py').write_text(FAKE_DICTATION)
    yield tmp_path
    for name in [m for m in sys.modules if m == 'ui' or m.startswith('ui.')]:
        del sys.modules[name]
    while str(tmp_path.resolve()) in sys.path:
        sys.path.remove(str(tmp_path.resolve()))
    sys.modules.update(saved)


def _client(env):
    app = FastAPI()
    calli_module.install(app, env)
    return TestClient(app)


def test_without_configuration_nothing_is_mounted():
    client = _client({})
    assert client.get('/api/calli/status').json() == {'available': False, 'reason': calli_module.TEACHER_MESSAGE,
                                                       'detail': 'CALLI_SOURCE absent.'}
    assert client.get('/calli/workspace').status_code == 404


@pytest.mark.parametrize('env, reason', [
    ({'CALLI_SOURCE': '/x', 'CALLI_QUEUE': 'q'}, 'Configuration Calli incomplète : CALLI_ROSTER, CALLI_COURSE.'),
    ({'CALLI_SOURCE': '/nonexistent-calli', **ENV}, 'CALLI_SOURCE ne désigne pas une copie de Calli.'),
])
def test_misconfiguration_is_reported_unavailable(env, reason):
    client = _client(env)
    assert client.get('/api/calli/status').json() == {'available': False, 'reason': calli_module.TEACHER_MESSAGE, 'detail': reason}
    assert client.get('/calli/workspace').status_code == 404


def test_configured_module_is_mounted_with_server_paths_only(fake_calli):
    client = _client({'CALLI_SOURCE': str(fake_calli), **ENV, 'CALLI_JOURNAL': 'j.jsonl'})
    info = client.get('/api/calli/status').json()
    assert info == {'available': True, 'url': '/calli/workspace?embed=1', 'course': '3A, FRANCAIS, Trimestre 1',
                    'dictation_available': False, 'dictation_reason': 'GLADIA_API_KEY absent'}
    assert 'writer' not in info and 'verified' not in info and 'connected' not in info
    assert 'static/workspace.js' in client.get('/calli/workspace?embed=1').text
    assert client.get('/calli/api/state').json() == {'queue': 'q.jsonl', 'roster': 'roster.csv',
                                                    'course': '3A, FRANCAIS, Trimestre 1', 'journal_path': 'j.jsonl'}


def test_upstream_app_starts_without_calli(monkeypatch):
    for name in list(os.environ):
        if name.startswith('CALLI_'):
            monkeypatch.delenv(name)
    import importlib

    import mvp
    previous = sys.modules.pop('mvp.app', None), getattr(mvp, 'app', None)
    try:
        app_module = importlib.import_module('mvp.app')
        client = TestClient(app_module.app)
        assert client.get('/').status_code == 200
        assert client.get('/api/calli/status').json()['available'] is False
        assert client.get('/calli/workspace').status_code == 404
    finally:
        sys.modules.pop('mvp.app', None)
        if previous[0] is not None:
            sys.modules['mvp.app'] = previous[0]
        if previous[1] is not None:
            mvp.app = previous[1]
        elif hasattr(mvp, 'app'):
            del mvp.app


@pytest.mark.skipif(not os.environ.get('CALLI_TEST_SOURCE'), reason='set CALLI_TEST_SOURCE to a Calli checkout')
def test_real_calli_keeps_its_own_guards(tmp_path):
    source = Path(os.environ['CALLI_TEST_SOURCE'])
    env = {'CALLI_SOURCE': str(source), 'CALLI_QUEUE': str(tmp_path / 'queue.jsonl'),
           'CALLI_ROSTER': str(source / 'data' / 'roster.csv'), 'CALLI_COURSE': '3A, FRANCAIS, Trimestre 1'}
    app = FastAPI()
    calli_module.install(app, env)
    client = TestClient(app, base_url='http://127.0.0.1:8000')
    assert client.get('/api/calli/status').json()['available'] is True
    state = client.get('/calli/api/state').json()
    assert state['stopped'] is False
    assert client.get('/calli/api/state', headers={'host': 'evil.example'}).status_code == 403
    item = {'student_id': 's01', 'student_name': 'Lucas Bernard', 'text': 'Bon trimestre.'}
    assert client.post('/calli/api/workspace/approve', json=item, headers={'origin': 'https://evil.example'}).status_code == 403
    assert client.post('/calli/api/stop', json={}, headers={'origin': 'http://127.0.0.1:8000'}).status_code == 200
    assert client.post('/calli/api/workspace/approve', json=item, headers={'origin': 'http://127.0.0.1:8000'}).status_code == 409
    assert not (tmp_path / 'queue.jsonl').exists() or (tmp_path / 'queue.jsonl').read_text().strip() == ''


def test_never_mounted_on_shared_hosting(fake_calli):
    client = _client({'CALLI_SOURCE': str(fake_calli), **ENV, 'PUBLIC_URL': 'https://demo.example'})
    assert client.get('/api/calli/status').json() == {
        'available': False, 'reason': calli_module.TEACHER_MESSAGE,
        'detail': 'Module Calli désactivé : ce serveur est publié (PUBLIC_URL).'}
    assert client.get('/calli/workspace').status_code == 404


def test_teacher_message_names_no_environment_variable():
    assert 'CALLI' not in calli_module.TEACHER_MESSAGE and '_' not in calli_module.TEACHER_MESSAGE


def test_native_roster_rows_are_read_only_and_never_stored():
    from pathlib import Path
    static = Path(__file__).parent / 'static'
    shell, management = (static / 'calli-shell.js').read_text(), (static / 'management.js').read_text()
    assert 'function managementView()' in management and 'structuredClone(getManagement())' in management
    assert 'structuredClone(managementView())' not in management and 'saveManagement(managementView' not in management
    assert "fetch('/calli/api/config'" in shell and "native: true" in shell
    assert 'native.roster.some(s => s.student_id === id)' in shell


def test_new_pronote_is_the_interface_and_calli_the_assistant():
    import re
    from pathlib import Path
    static = Path(__file__).parent / 'static'
    html = (static / 'workspace.html').read_text()
    assert '<title>New PRONOTE · Calli</title>' in html and 'aria-label="New Pronote, accueil"' in html
    assert 'calli-logo' not in html
    for path in [*static.glob('*.html'), *static.glob('*.js')]:
        text = path.read_text()
        assert not re.search(r'Parallèle|H Parallel|parallel-logo[-a-z]*\.svg', text), path.name
    shell = html + (static / 'workspace.js').read_text()
    assert 'Assistant Calli' in shell and 'class="calli-symbol' in shell and 'alt="Calli, votre assistant"' in shell
    assert 'M12 3v3M8 6h8' not in shell
