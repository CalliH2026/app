"""Background lifecycle and evidence boundaries; no browser, H API or desktop."""
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from . import background_pronote as background
from . import integrations
from .pronote_routes import DEMO_URL, catalog_for_url, official_catalog


class Browser:
    def __init__(self):
        self.destroyed = False
        self.screenshots = []
        self.driver = SimpleNamespace(save_screenshot=self.capture)

    def capture(self, path):
        self.screenshots.append(path)
        return True

    def destroy(self):
        self.destroyed = True


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Every lifecycle test owns all state, locks, browser and queued workers."""
    folder = tmp_path / 'background'
    monkeypatch.setattr(background, 'FOLDER', folder)
    monkeypatch.setattr(background, 'FILE', folder / 'state.json')
    monkeypatch.setattr(background, 'LOCK', threading.RLock())
    monkeypatch.setattr(background, 'DRIVER_LOCK', threading.Lock())
    monkeypatch.setattr(background, 'RUNNING', threading.Lock())
    monkeypatch.setattr(background, 'STOP', threading.Event())
    monkeypatch.setattr(background, 'BROWSER', None)
    monkeypatch.setattr(background, 'OWNED', False)
    monkeypatch.setattr(background, 'ACTIVE_SESSION', None)
    monkeypatch.setattr(background, 'ACTIVE_CLIENT', None)
    monkeypatch.setattr(background, 'GENERATION', 0)
    monkeypatch.setattr(background, 'CATALOG_VALUE', None)
    queued = []

    class QueuedThread:
        def __init__(self, *, target, name, daemon):
            self.target = target

        def start(self):
            queued.append(self.target)

    # Replace this module's threading facade, not threading.Thread globally.
    monkeypatch.setattr(background, 'threading', SimpleNamespace(Thread=QueuedThread))
    def flush():
        for _ in range(20):
            if not queued:
                return
            queued.pop(0)()
        pytest.fail('Background workers did not settle')

    yield SimpleNamespace(folder=folder, queued=queued, flush=flush)
    assert not background.RUNNING.locked(), 'A worker left the running guard locked'


def ready(browser=None):
    browser = browser or Browser()
    background.BROWSER = browser
    background.OWNED = True
    background.CATALOG_VALUE = official_catalog()
    background.write({'state': 'ready', 'source_kind': 'official_demo',
                      'source_url': DEMO_URL, 'desktop_access': False,
                      'routes': [{'id': 'home', 'title': "Page d'accueil", 'verified': True}],
                      'actions': [], 'snapshots': {}})
    return browser


def fake_h(monkeypatch, wait=None):
    """Capture the exact H contract and run custom tools locally, without H."""
    import hai_agents
    from . import engine
    calls = []
    sessions = []

    class Session:
        id = 'test-session-never-sent'
        cancelled = 0

        def cancel(self):
            self.cancelled += 1

        def wait_for_completion(self, **kwargs):
            if wait:
                return wait(self, calls[-1])
            tools = {tool.__name__: tool for tool in calls[-1]['tools']}
            tools['list_pronote_routes']()
            observed = json.loads(tools['read_pronote_view']('home'))
            quote_id = next(qid for qid, text in observed['quote_catalog'].items()
                            if text == 'Sélectionnez une classe')
            return SimpleNamespace(answer={'summary': 'Lecture de la démo officielle.',
                'facts': [{'claim': 'Une classe doit être choisie.', 'route_id': 'home',
                           'quote_id': quote_id}],
                'unknowns': ['Aucune copie ni aucun barème lus.'], 'next_steps': []})

    class Client:
        def __init__(self, **kwargs):
            pass

        def start_session(self, **kwargs):
            calls.append(kwargs)
            session = Session()
            sessions.append(session)
            return session

    monkeypatch.setattr(hai_agents, 'Client', Client)
    monkeypatch.setattr(integrations, 'key', lambda name: 'never-a-real-key')
    monkeypatch.setattr(engine, 'finish_session_safely', lambda session: None)
    monkeypatch.setattr(engine, 'launch', lambda *args, **kwargs: pytest.fail('Fixture pipeline must stay separate'))
    monkeypatch.setattr(background, 'render_replay', lambda *args: None)
    monkeypatch.setattr(background, 'navigate_route', lambda *args, **kwargs: {
        'route_id': 'home', 'title': "Page d'accueil - PRONOTE", 'source_url': DEMO_URL,
        'source_kind': 'pronote_web', 'visible_text': 'Sélectionnez une classe',
        'content_sha256': 'a' * 64})
    return SimpleNamespace(calls=calls, sessions=sessions)


def test_restart_never_claims_persisted_browser_is_active(isolated):
    background.write({'state': 'ready', 'active': True, 'report': {'summary': 'Existing report'}})
    value = background.status()
    assert value['state'] == 'stopped' and value['active'] is False
    assert value['report']['summary'] == 'Existing report'


def test_concurrent_schedule_deduplicates_and_gives_h_only_read_tools(isolated, monkeypatch):
    browser = ready()
    h = fake_h(monkeypatch)
    first = background.schedule(trigger='document_open')
    second = background.schedule(trigger='document_open')
    assert first['run_id'] == second['run_id']
    assert len(isolated.queued) == 1 and not h.calls
    isolated.queued.pop()()
    value = background.status()
    assert len(h.calls) == 1 and value['state'] == 'ready'
    assert h.calls[0]['agent']['environments'] == []
    assert h.calls[0]['answer_schema'] is background.AgentReport
    assert {tool.__name__ for tool in h.calls[0]['tools']} == {
        'list_pronote_routes', 'read_pronote_view'}
    assert len(browser.screenshots) == 1
    assert value['desktop_access'] is False
    assert set(value['snapshots']) == {'home'}
    assert 'Alex' not in json.dumps(value['report'], ensure_ascii=False)
    assert value['report']['facts'][0]['quote'] == 'Sélectionnez une classe'
    assert 'quote_id' not in value['report']['facts'][0]
    assert background.ACTIVE_SESSION is background.ACTIVE_CLIENT is None


def test_stop_cancels_active_h_and_rejects_late_tool_calls(isolated, monkeypatch):
    browser = ready()

    def wait(session, request):
        background.stop()
        tools = {tool.__name__: tool for tool in request['tools']}
        with pytest.raises(ValueError, match='arrêtée'):
            tools['read_pronote_view']('home')
        with pytest.raises(ValueError, match='arrêtée'):
            tools['list_pronote_routes']()
        return SimpleNamespace(answer={'summary': 'Late answer', 'facts': [],
                                       'unknowns': [], 'next_steps': []})

    h = fake_h(monkeypatch, wait)
    background.schedule()
    isolated.flush()
    value = background.status()
    assert value['state'] == 'stopped' and value['active'] is False
    assert value['report'] is None and not value['snapshots']
    assert h.sessions[0].cancelled == 1
    assert browser.destroyed and not browser.screenshots


def test_completed_automatic_job_is_once_per_connection_but_manual_reread_is_allowed(isolated, monkeypatch):
    ready()
    h = fake_h(monkeypatch)
    first = background.schedule(trigger='document_open')
    isolated.flush()
    again = background.schedule(trigger='document_open')
    assert again['run_id'] == first['run_id']
    assert not isolated.queued and len(h.calls) == 1
    manual = background.schedule(trigger='manual')
    assert manual['run_id'] != first['run_id']
    isolated.flush()
    assert len(h.calls) == 2 and background.status()['state'] == 'ready'


def test_stop_before_worker_starts_does_not_create_an_h_session(isolated, monkeypatch):
    ready()
    h = fake_h(monkeypatch)
    background.schedule()
    background.stop()
    isolated.flush()
    assert not h.calls, 'An already stopped job must not create a billable H session'
    assert background.status()['state'] == 'stopped'


def test_stop_destroys_only_a_browser_owned_by_connector(isolated):
    browser = ready()
    background.OWNED = False
    generation = background.GENERATION
    value = background.stop()
    assert not browser.destroyed
    assert background.GENERATION > generation
    assert value['state'] == 'stopped' and value['active'] is False
    with pytest.raises(ValueError, match='actif'):
        background.open_route('home')


def test_school_request_cannot_reuse_an_existing_demo_browser(isolated):
    browser = ready()
    with pytest.raises(ValueError):
        background.start(source='school')
    assert background.BROWSER is browser and not browser.destroyed
    assert background.status()['source_kind'] == 'official_demo'


def test_demo_start_rejects_a_school_catalog_before_creating_browser(isolated, monkeypatch):
    import hai_drivers.web.selenium
    monkeypatch.setattr(background, '_catalog', lambda: catalog_for_url(
        'https://school.test/pronote/professeur.html', app_version='2026.2.8'))
    monkeypatch.setattr(hai_drivers.web.selenium, 'SeleniumWebDriver',
                        lambda **kwargs: pytest.fail('Wrong-source catalog must fail before a browser starts'))
    with pytest.raises(ValueError):
        background.start(source='official_demo')
    assert background.BROWSER is None


def test_stop_requested_during_navigation_discards_the_observation(isolated, monkeypatch):
    browser = ready()

    def cancelled_navigation(*args, **kwargs):
        # stop() publishes this signal before waiting for the navigation lock.
        background.STOP.set()
        return {'route_id': 'home', 'title': 'Late view', 'source_url': DEMO_URL,
                'visible_text': 'A cancelled observation', 'content_sha256': 'a' * 64}

    monkeypatch.setattr(background, 'navigate_route', cancelled_navigation)
    with pytest.raises(ValueError):
        background.open_route('home')
    assert not background.status()['snapshots']
    assert not browser.screenshots


def test_stop_during_capture_deletes_frame_and_does_not_publish_snapshot(isolated, monkeypatch):
    browser = ready()
    value = background.status()
    value.update(run_id='a' * 32, frames=[])
    background.write(value)

    def capture(path):
        Path(path).write_bytes(b'unit-test fixture, no actual screenshot')
        background.STOP.set()
        return True

    browser.driver.save_screenshot = capture
    monkeypatch.setattr(background, 'navigate_route', lambda *args, **kwargs: {
        'route_id': 'home', 'title': 'Late view', 'source_url': DEMO_URL,
        'visible_text': 'A cancelled observation', 'content_sha256': 'a' * 64})
    with pytest.raises(ValueError, match='arrêtée'):
        background.open_route('home')
    value = background.status()
    assert value['frames'] == [] and value['snapshots'] == {}
    assert not list(isolated.folder.rglob('*.png'))


@pytest.mark.parametrize('report', [
    {'state': 'candidate', 'valid': True, 'catalog': official_catalog()},
    {'state': 'established', 'valid': False, 'catalog': official_catalog()},
])
def test_catalog_needs_authoritative_harness_validation(isolated, tmp_path, report):
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='validé'):
        background._catalog(path)


def test_report_accepts_only_exact_quotes_from_the_cited_route():
    snapshots = {'notes': {'visible_text': 'Notes\nSélectionnez une classe'}}
    report = {'summary': 'Une classe doit être sélectionnée.',
              'facts': [{'claim': 'Le relevé attend une classe.', 'route_id': 'notes',
                         'quote': 'Sélectionnez une classe'}],
              'unknowns': ['Aucune note individuelle lue.'], 'next_steps': []}
    assert background.validate_report(report, snapshots)['facts'][0]['route_id'] == 'notes'
    report['facts'][0]['route_id'] = 'copie'
    with pytest.raises(ValueError, match='citation'):
        background.validate_report(report, snapshots)
    report['facts'][0].update(route_id='notes', quote='Sélectionnez une autre classe')
    with pytest.raises(ValueError, match='citation'):
        background.validate_report(report, snapshots)
    report['facts'][0]['quote'] = ''
    with pytest.raises(ValidationError):
        background.validate_report(report, snapshots)


def test_quote_selection_extracts_the_original_literal_instead_of_model_text():
    literal = 'Résultat juste : 2/2 ; justification absente : 0/2.'
    snapshots = {'notes': {'visible_text': 'Notes\n\n  ' + literal + '  \nClasse 3A'}}
    catalog = background.quote_catalog(snapshots['notes'])
    assert catalog == {'q001': 'Notes', 'q002': literal, 'q003': 'Classe 3A'}
    answer = {'summary': 'Lecture sourcée.', 'facts': [{'claim': 'La justification est évaluée.',
              'route_id': 'notes', 'quote_id': 'q002', 'quote': 'Model typo must never replace the original'}],
              'unknowns': [], 'next_steps': []}
    report = background.resolve_report(answer, snapshots)
    assert report['facts'] == [{'claim': 'La justification est évaluée.',
                               'route_id': 'notes', 'quote': literal}]
    assert report['facts'][0]['quote'] in snapshots['notes']['visible_text']
    assert answer['facts'][0]['quote_id'] == 'q002'  # Input is not mutated.


@pytest.mark.parametrize('route_id,quote_id', [('notes', 'q999'), ('copie', 'q001')])
def test_unknown_or_wrong_route_quote_identifier_is_rejected(route_id, quote_id):
    snapshots = {'notes': {'visible_text': 'Sélectionnez une classe'}}
    answer = {'summary': 'Lecture sourcée.', 'facts': [{'claim': 'Une classe doit être choisie.',
              'route_id': route_id, 'quote_id': quote_id}], 'unknowns': [], 'next_steps': []}
    with pytest.raises(ValueError, match='extrait absent'):
        background.resolve_report(answer, snapshots)


def test_decision_does_not_change_or_publish_the_report(isolated):
    ready()
    background.event('Vue lue.', stage='read')
    before = background.status()
    value = background.decide('dismiss')
    assert value['dismissed'] and not value['kept']
    assert value['snapshots'] == before['snapshots'] and value['actions'] == before['actions']
    value = background.decide('keep')
    assert value['kept'] and not value['dismissed']
    with pytest.raises(ValueError):
        background.decide('publish')


def test_opening_fictional_copy_only_sends_an_independent_trigger(monkeypatch):
    from fastapi.testclient import TestClient
    from . import app as app_module
    from . import workspace
    fixture_result = {'job_id': 'fictional-alex-job', 'source_kind': 'fixture',
                      'report': {'summary': 'Fictional Alex report'}}
    received, opened = [], []

    def open_document(*args, teacher_assessment=None):
        opened.append({'args': args, 'teacher_assessment': teacher_assessment})
        return fixture_result
    monkeypatch.setattr(workspace, 'open_document', open_document)
    monkeypatch.setattr(background, 'schedule', lambda **kwargs: received.append(kwargs))
    # Without context-manager entry, no application lifespan/native bridge runs.
    response = TestClient(app_module.app).post('/api/workspace/documents/copie/open',
                                               json={'mode': 'demo'})
    assert response.status_code == 200 and response.json() == fixture_result
    assert received == [{'trigger': 'document_open'}]
    assert opened == [{'args': ('copie', 'points', 'demo', False, 'local'), 'teacher_assessment': None}]


def test_replay_endpoint_exposes_only_a_valid_run_video(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from . import app as app_module
    monkeypatch.setattr(app_module, 'DATA', tmp_path)
    run_id = 'a' * 32
    video = tmp_path / 'pronote-background/runs' / run_id / 'replay.mp4'
    video.parent.mkdir(parents=True)
    video.write_bytes(b'unit-test bytes, never represented as an actual video')
    client = TestClient(app_module.app)
    assert client.get('/api/pronote/background/replay/not-a-run').status_code == 404
    assert client.get('/api/pronote/background/replay/' + 'b' * 32).status_code == 404
    response = client.get('/api/pronote/background/replay/' + run_id)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'video/mp4'
    assert response.content == video.read_bytes()
