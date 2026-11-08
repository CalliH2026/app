"""Practice state transitions and a mocked Devin v3 flow; no paid API calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import httpx
import pytest

from . import engine, practice

JOB_ID = 'a' * 12
HTML = b'''<!doctype html><html lang="fr"><head><title>Pythagore</title></head>
<body><h1>Pythagore</h1><button>Recommencer</button><script>let step = 1;</script></body></html>'''


@pytest.fixture
def store(monkeypatch, tmp_path):
    job = {'id': JOB_ID, 'status': 'ready', 'mode': 'live', 'session_id': 'h-verified',
           'dossier': {'summary': 'Alex Martin doit identifier l’hypoténuse et justifier le théorème, puis rédiger une conclusion.',
                       'evidence': [{'claim': 'La conclusion avec unité manque.', 'quote': 'Nom et secret privé', 'source_ids': ['copy']}],
                       'sources': [{'id': 'copy', 'type': 'school', 'title': 'Copie de Pythagore', 'text': 'Copie privée de Alex Martin.'}]}}
    monkeypatch.setattr(engine, 'JOBS', {JOB_ID: job})
    monkeypatch.setattr(practice, 'FOLDER', tmp_path / 'practice')
    monkeypatch.setattr(practice, 'STATES', {})
    monkeypatch.setattr(practice, 'WORKERS', {})
    monkeypatch.setattr(practice, '_settings', lambda: {'token': 'secret-api-key', 'org': 'org-test', 'max_acu_limit': 2})
    sample = tmp_path / 'sample.html'
    sample.write_bytes(HTML)
    monkeypatch.setattr(practice, 'SIMULATION_FILE', sample)
    return job


def finished():
    for _ in range(200):
        value = practice.get(JOB_ID)
        if value['status'] != 'running':
            return value
        time.sleep(.01)
    raise AssertionError('Worker did not complete')


def test_simulation_works_without_credentials_and_never_uses_devin(store, monkeypatch):
    monkeypatch.setattr(practice, '_settings', lambda: None)
    monkeypatch.setattr(practice, '_client', lambda: pytest.fail('Simulation called Devin'))
    value = practice.get(JOB_ID)
    assert value['available'] is True and value['configured'] is False
    practice.start(JOB_ID)
    value = finished()
    assert value['status'] == 'ready'
    assert value['mode'] == 'simulation' and value['simulated'] is True
    assert 'aucun appel Devin' in value['message']
    assert value['validation']['provider_tests_reported'] is False
    assert 'session_url' not in value
    assert 'preview_url' in value and 'download_url' not in value
    assert 'Content-Security-Policy' in practice.artifact_path(JOB_ID).read_text()
    with pytest.raises(ValueError, match='validez'):
        practice.artifact_path(JOB_ID, download=True)
    approved = practice.approve(JOB_ID)
    assert approved['approved'] and approved['download_url'].endswith('/download')
    assert practice.artifact_path(JOB_ID, download=True).is_file()


def test_live_requires_configuration_and_h_analysis_but_simulation_accepts_demo(store, monkeypatch):
    monkeypatch.setattr(practice, '_settings', lambda: None)
    with pytest.raises(RuntimeError, match='configurée'):
        practice.start(JOB_ID, mode='live')
    assert practice.STATES == {}
    store['mode'] = 'demo'
    store.pop('session_id')
    assert practice.get(JOB_ID)['source_analysis'] == 'scenario'
    with pytest.raises(ValueError, match='réellement préparé par H'):
        practice.start(JOB_ID, mode='live')
    practice.start(JOB_ID, mode='simulation')
    assert finished()['status'] == 'ready'


@pytest.mark.parametrize('change', ['not_ready', 'other_topic', 'unverified_h'])
def test_incompatible_reports_are_not_eligible(store, change):
    if change == 'not_ready':
        store['status'] = 'rendering'
    elif change == 'other_topic':
        store['dossier']['sources'][0]['title'] = 'Fractions'
    else:
        store.pop('session_id')
    assert practice.get(JOB_ID)['available'] is False
    with pytest.raises(ValueError):
        practice.start(JOB_ID)


def test_deduplication_approval_and_source_change(store):
    practice.start(JOB_ID)
    first = finished()
    practice.approve(JOB_ID)
    token = practice.STATES[JOB_ID]['generation_id']
    repeated = practice.start(JOB_ID)
    assert practice.STATES[JOB_ID]['generation_id'] == token
    assert repeated['approved'] is True
    assert repeated['created_at'] == first['created_at']
    store['dossier']['summary'] = 'L’analyse H a été corrigée.'
    assert practice.get(JOB_ID)['status'] == 'not_started'
    assert practice.get(JOB_ID)['approved'] is False
    with pytest.raises(ValueError, match='version du rapport'):
        practice.artifact_path(JOB_ID)
    practice.start(JOB_ID)
    assert finished()['status'] == 'ready'
    assert practice.STATES[JOB_ID]['generation_id'] != token


def test_modified_artifact_and_symlinks_cannot_be_approved_or_downloaded(store, tmp_path):
    practice.start(JOB_ID)
    assert finished()['status'] == 'ready'
    path = practice.artifact_path(JOB_ID)
    original = path.read_bytes()
    path.write_text('tampered')
    with pytest.raises(ValueError, match='changé'):
        practice.approve(JOB_ID)
    path.unlink()
    target = tmp_path / 'other.html'
    target.write_bytes(original)
    path.symlink_to(target)
    with pytest.raises(ValueError):
        practice.artifact_path(JOB_ID)


def test_changed_analysis_scene_invalidates_activity_and_approval(store):
    store['dossier']['scenes'] = [{'title': 'Piste de travail', 'body': 'Repérer l’hypoténuse.', 'source_ids': ['copy']}]
    practice.start(JOB_ID, mode='simulation')
    assert finished()['status'] == 'ready'
    practice.approve(JOB_ID)
    fingerprint = practice.STATES[JOB_ID]['fingerprint']
    store['dossier']['scenes'][0]['body'] = 'Justifier le théorème et compléter une conclusion avec unité.'
    value = practice.get(JOB_ID)
    assert value['status'] == 'not_started'
    assert value['approved'] is False
    assert 'preview_url' not in value and 'download_url' not in value
    with pytest.raises(ValueError, match='version du rapport'):
        practice.artifact_path(JOB_ID, download=True)
    practice.start(JOB_ID, mode='simulation')
    assert finished()['status'] == 'ready'
    assert practice.STATES[JOB_ID]['fingerprint'] != fingerprint


def test_restart_does_not_recreate_an_uncertain_provider_session(store, monkeypatch):
    source = practice._source(JOB_ID)
    state = {'source_job_id': JOB_ID, 'fingerprint': source['fingerprint'], 'mode': 'live', 'simulated': False,
             'status': 'running', 'creation_requested': True, 'generation_id': 'old', 'approved': False}
    practice._persist(state)
    value = practice.get(JOB_ID)
    assert value['status'] == 'failed' and value['retryable'] is False
    monkeypatch.setattr(practice, '_client', lambda: pytest.fail('Must not create duplicate session'))
    with pytest.raises(RuntimeError, match='incertaine'):
        practice.start(JOB_ID, retry=True, mode='live')


ATTACHMENT_ID = 'a5e0469f-1def-4f1b-a98a-0ede95ad40a1'


def mock_devin(monkeypatch, *, status_code=200, attachment_body=HTML, provider_tests=True, existing=False, redirect=False,
               session_id='devin-' + 'b' * 32, url=None, status='running', detail='finished', acus=.4, report=None,
               attachments=None, location='https://storage.googleapis.com/devin-files/activity.html?secret=SIGNED'):
    requests = []
    def handle(request):
        requests.append(request)
        if request.url.host == 'app.devin.ai':
            return httpx.Response(401, json={'detail': 'browser session required'})
        if request.url.host == 'storage.googleapis.com':
            assert 'authorization' not in request.headers
            if redirect:
                return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
            return httpx.Response(200, content=attachment_body)
        assert request.headers['authorization'] == 'Bearer secret-api-key'
        if request.method == 'POST':
            if status_code != 200:
                return httpx.Response(status_code, json={'detail': 'secret-api-key private provider detail'})
            return httpx.Response(200, json={'session_id': session_id, 'status': 'new', **({'url': url} if url else {})})
        if request.url.path.endswith('/attachments/' + ATTACHMENT_ID + '/activity.html'):
            return httpx.Response(307, headers={'location': location})
        if request.url.path.endswith('/attachments'):
            return httpx.Response(200, json=attachments if attachments is not None else [{'attachment_id': ATTACHMENT_ID,
                'name': 'activity.html', 'source': 'devin',
                'url': 'https://app.devin.ai/attachments/' + ATTACHMENT_ID + '/activity.html'}])
        return httpx.Response(200, json={'session_id': session_id, 'status': status, 'status_detail': detail,
            'acus_consumed': acus, 'structured_output': report if report is not None else {'artifact_name': 'activity.html',
                'math_tests_passed': provider_tests, 'browser_tested': provider_tests, 'test_summary': 'Tests effectués.'}})
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(practice, '_client', lambda: httpx.Client(transport=transport, follow_redirects=False))
    monkeypatch.setattr(practice.socket, 'getaddrinfo', lambda *args, **kwargs: [(2, 1, 6, '', ('8.8.8.8', 443))])
    return requests


def test_real_v3_flow_sends_only_whitelisted_skills_and_retrieves_code(store, monkeypatch):
    requests = mock_devin(monkeypatch)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'ready'
    assert value['simulated'] is False and value['mode'] == 'live'
    assert value['validation']['provider_tests_reported'] is True
    assert value['validation']['runtime_verified_locally'] is False
    assert value['session_url'] == 'https://app.devin.ai/sessions/' + 'b' * 32
    create = [r for r in requests if r.method == 'POST']
    assert len(create) == 1
    payload = json.loads(create[0].content)
    assert payload['max_acu_limit'] == 2
    assert payload['memory_enabled'] is False and payload['resumable'] is False
    assert payload['repos'] == [] and payload['secret_ids'] == []
    assert 'Alex' not in payload['prompt'] and 'privé' not in payload['prompt'] and 'Copie privée' not in payload['prompt']
    assert 'SPÉCIFICATION' in payload['prompt']
    assert practice.artifact_path(JOB_ID).read_bytes().startswith(b'<!doctype html>')


def test_resume_known_session_does_not_issue_another_post(store, monkeypatch):
    source = practice._source(JOB_ID)
    state = {'source_job_id': JOB_ID, 'fingerprint': source['fingerprint'], 'mode': 'live', 'simulated': False,
             'status': 'running', 'creation_requested': True, 'generation_id': 'old', 'approved': False,
             'session_id': 'devin-' + 'b' * 32, 'session_url': 'https://app.devin.ai/sessions/' + 'b' * 32, 'org_id': 'org-test'}
    practice._persist(state)
    assert practice.get(JOB_ID)['retryable'] is True
    requests = mock_devin(monkeypatch)
    practice.start(JOB_ID, retry=True, mode='live')
    assert finished()['status'] == 'ready'
    assert not any(request.method == 'POST' for request in requests)


def test_switching_modes_keeps_both_artifacts_and_reuses_paid_generation(store, monkeypatch):
    practice.start(JOB_ID, mode='simulation')
    assert finished()['status'] == 'ready'
    practice.approve(JOB_ID)
    simulation_path = practice.artifact_path(JOB_ID, download=True)
    requests = mock_devin(monkeypatch)
    practice.start(JOB_ID, mode='live')
    assert finished()['status'] == 'ready'
    live_path = practice.artifact_path(JOB_ID)
    assert simulation_path != live_path
    assert practice.start(JOB_ID, mode='simulation')['approved'] is True
    assert practice.artifact_path(JOB_ID, download=True) == simulation_path
    practice.start(JOB_ID, mode='live')
    assert practice.artifact_path(JOB_ID) == live_path
    assert len([request for request in requests if request.method == 'POST']) == 1


def test_simulation_does_not_erase_an_uncertain_live_creation(store):
    source = practice._source(JOB_ID)
    state = {'source_job_id': JOB_ID, 'fingerprint': source['fingerprint'], 'mode': 'live', 'simulated': False,
             'status': 'running', 'creation_requested': True, 'generation_id': 'old', 'approved': False}
    practice._persist(state)
    assert practice.get(JOB_ID)['retryable'] is False
    practice.start(JOB_ID, mode='simulation')
    assert finished()['status'] == 'ready'
    with pytest.raises(RuntimeError, match='incertaine'):
        practice.start(JOB_ID, retry=True, mode='live')


def test_arbitrary_library_errors_cannot_expose_credentials(store, monkeypatch):
    def fail():
        raise ValueError('Illegal header value Bearer secret-api-key')
    monkeypatch.setattr(practice, '_client', fail)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'failed'
    assert 'secret-api-key' not in json.dumps(value)


def test_provider_errors_do_not_leak_response_bodies(store, monkeypatch):
    mock_devin(monkeypatch, status_code=401)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'failed'
    assert value['retryable'] is True
    assert 'HTTP 401' in value['message']
    assert 'secret-api-key' not in json.dumps(value)


def test_creation_502_is_uncertain_and_cannot_create_a_duplicate_on_retry(store, monkeypatch):
    requests = mock_devin(monkeypatch, status_code=502)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'failed'
    assert value['retryable'] is False
    assert 'HTTP 502' in value['message']
    assert 'secret-api-key' not in json.dumps(value)
    assert len([request for request in requests if request.method == 'POST']) == 1
    with pytest.raises(RuntimeError, match='incertaine'):
        practice.start(JOB_ID, retry=True, mode='live')
    assert len([request for request in requests if request.method == 'POST']) == 1


def test_provider_tests_must_not_be_invented(store, monkeypatch):
    mock_devin(monkeypatch, provider_tests=False)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'failed' and 'compte rendu' in value['message']
    assert 'preview_url' not in value


def test_attachment_redirects_are_not_followed(store, monkeypatch):
    requests = mock_devin(monkeypatch, redirect=True)
    practice.start(JOB_ID, mode='live')
    assert finished()['status'] == 'failed'
    assert not any(r.url.host == '127.0.0.1' for r in requests)


@pytest.mark.parametrize('url', ['http://storage.googleapis.com/a', 'https://127.0.0.1/a',
    'https://storage.googleapis.com.evil.test/a', 'https://user:password@storage.googleapis.com/a',
    'https://storage.googleapis.com:8443/a'])
def test_attachment_urls_are_constrained(url):
    with pytest.raises(ValueError):
        practice._safe_attachment_url(url)


def test_private_dns_addresses_are_rejected(monkeypatch):
    monkeypatch.setattr(practice.socket, 'getaddrinfo', lambda *args, **kwargs: [(2, 1, 6, '', ('10.0.0.1', 443))])
    with pytest.raises(ValueError, match='publique'):
        practice._safe_attachment_url('https://storage.googleapis.com/file')


@pytest.mark.parametrize('extra', ['<script src="https://evil.test/code.js"></script>',
    '<iframe srcdoc="attack"></iframe>', '<script>fetch("https://evil.test")</script>',
    '<meta http-equiv="refresh" content="0;url=https://evil.test">',
    '<style>body{background:url(https://evil.test/pixel)}</style>'])
def test_generated_html_has_no_active_external_capabilities(extra):
    with pytest.raises(ValueError):
        practice._validate_html(HTML.replace(b'</body>', extra.encode() + b'</body>'))


def test_invalid_identifiers_and_missing_reports():
    for value in ('../secret', 'A' * 12, 'g' * 12, ''):
        with pytest.raises(KeyError):
            practice.get(value)


# Shape of an actual Create Session v3 response: a bare 32-hex session_id and the app URL.
BARE_ID = 'f89a13b65d3a40f0a6698b30d3bffef9'


def test_v3_bare_session_id_is_accepted_and_used_for_polling(store, monkeypatch):
    requests = mock_devin(monkeypatch, session_id=BARE_ID, url='https://app.devin.ai/sessions/' + BARE_ID)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'ready' and value['session_url'] == 'https://app.devin.ai/sessions/' + BARE_ID
    assert len([r for r in requests if r.method == 'POST']) == 1
    assert all(r.url.path.split('/sessions/')[1].startswith(BARE_ID)
               for r in requests if r.method == 'GET' and '/sessions/' in r.url.path)


def test_returned_url_is_kept_only_for_this_session_on_app_devin_ai(store, monkeypatch):
    mock_devin(monkeypatch, session_id=BARE_ID, url='https://evil.example/sessions/' + BARE_ID)
    practice.start(JOB_ID, mode='live')
    assert finished()['session_url'] == 'https://app.devin.ai/sessions/' + BARE_ID
    assert practice.session_url('devin-' + BARE_ID) == 'https://app.devin.ai/sessions/' + BARE_ID
    for url in ('http://app.devin.ai/sessions/' + BARE_ID, 'https://user@app.devin.ai/sessions/' + BARE_ID,
                'https://app.devin.ai:8443/sessions/' + BARE_ID, 'https://app.devin.ai/sessions/' + 'a' * 32,
                'https://app.devin.ai/sessions/' + BARE_ID + '?next=/x'):
        assert practice.session_url(BARE_ID, url) == 'https://app.devin.ai/sessions/' + BARE_ID


@pytest.mark.parametrize('url', [
    'https://app.devin.ai:bad/sessions/' + BARE_ID,
    'https://app.devin.ai:65536/sessions/' + BARE_ID,
    'https://[app.devin.ai/sessions/' + BARE_ID,
])
def test_malformed_optional_session_url_does_not_lose_a_created_session(store, monkeypatch, url):
    requests = mock_devin(monkeypatch, session_id=BARE_ID, url=url)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'ready'
    assert value['session_url'] == 'https://app.devin.ai/sessions/' + BARE_ID
    saved = json.loads((practice.FOLDER / JOB_ID / 'state-live.json').read_text())
    assert saved['session_id'] == BARE_ID
    assert len([r for r in requests if r.method == 'POST']) == 1


@pytest.mark.parametrize('bad', ['devin-test', 'session-123', 'F' * 32, 'f' * 31, '', None])
def test_unexpected_session_id_is_persisted_and_blocks_a_duplicate_create(store, monkeypatch, bad):
    mock_devin(monkeypatch, session_id=bad)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'failed' and value['retryable'] is False
    saved = json.loads((practice.FOLDER / JOB_ID / 'state-live.json').read_text())
    assert saved['created_session_id'] == (bad if isinstance(bad, str) else None) and 'session_id' not in saved
    monkeypatch.setattr(practice, '_client', lambda: pytest.fail('Must not create duplicate session'))
    with pytest.raises(RuntimeError, match='incertaine'):
        practice.start(JOB_ID, retry=True, mode='live')


# Shape observed on a real v3 session: work done, activity attached, session still running and waiting for a reply.
DONE_REPORT = {'artifact_name': 'activity.html', 'math_tests_passed': True, 'browser_tested': True,
               'test_summary': '25 tests Chrome et interaction manuelle effectués.'}


def test_waiting_for_user_with_final_report_and_attachment_is_retrieved(store, monkeypatch):
    mock_devin(monkeypatch, session_id=BARE_ID, detail='waiting_for_user', acus=0, report=DONE_REPORT)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'ready', value['message']
    assert value['validation']['provider_state'] == 'running/waiting_for_user'
    assert value['validation']['provider_tests_reported'] is True and value['validation']['runtime_verified_locally'] is False
    assert 'acus_consumed' not in value
    saved = json.loads((practice.FOLDER / JOB_ID / 'state-live.json').read_text())
    assert saved['acus_reported'] == {'value': 0, 'status': 'running', 'status_detail': 'waiting_for_user'}


@pytest.mark.parametrize('detail, report, attachments, message', [
    ('waiting_for_user', {}, None, 'intervention'),
    ('waiting_for_user', {**DONE_REPORT, 'browser_tested': False}, None, 'intervention'),
    ('waiting_for_approval', DONE_REPORT, None, 'intervention'),
    ('waiting_for_user', DONE_REPORT, [], 'pas joint'),
    ('waiting_for_user', DONE_REPORT, [{'attachment_id': ATTACHMENT_ID, 'name': 'activity.html', 'source': 'devin'},
                                       {'attachment_id': ATTACHMENT_ID, 'name': 'activity.html', 'source': 'devin'}],
     'plusieurs'),
])
def test_waiting_session_without_a_complete_result_still_fails(store, monkeypatch, detail, report, attachments, message):
    mock_devin(monkeypatch, session_id=BARE_ID, detail=detail, acus=0, report=report, attachments=attachments)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'failed' and message in value['message']


PROVIDER_CSP = ("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; img-src data:\">")


def _activity(head=''):
    return ('<!doctype html><html lang="fr"><head>' + head + '<title>Pythagore</title></head>'
            '<body><h1>Pythagore</h1><button type="button">Recommencer</button><script>let step = 1;</script></body></html>').encode()


@pytest.mark.parametrize('head', [PROVIDER_CSP, PROVIDER_CSP.replace('">', '" />'),
                                  "<META CONTENT=\"default-src 'none'\" HTTP-EQUIV=\"content-security-policy\" />"])
def test_generator_csp_meta_is_replaced_by_the_application_policy(head):
    raw = _activity(head)
    transform = {}
    checked = practice._validate_html(raw, transform).decode()
    assert checked.count('Content-Security-Policy') == 1 and practice.HTML_CSP in checked
    assert transform['raw_sha256'] == hashlib.sha256(raw).hexdigest() and transform['provider_csp_removed']


@pytest.mark.parametrize('head', [
    PROVIDER_CSP * 2,
    '<meta http-equiv="Content-Security-Policy" content="default-src *" data-x="1">',
    '<meta http-equiv="Content-Security-Policy">',
    '<meta http-equiv=Content-Security-Policy content="default-src *">',
    PROVIDER_CSP.replace('"', "'"),
    '<meta http-equiv="refresh" content="0;url=https://evil.test">',
    PROVIDER_CSP + '<link rel="stylesheet" href="https://evil.test/a.css">',
    PROVIDER_CSP + '<script>fetch("https://evil.test")</script>',
    PROVIDER_CSP + '<iframe src="https://evil.test"></iframe>',
    PROVIDER_CSP + '<script>localStorage.x = 1</script>',
])
def test_malformed_multiple_or_unsafe_html_is_still_rejected(head):
    with pytest.raises(practice.PracticeError):
        practice._validate_html(_activity(head))


def test_retrieved_activity_records_raw_and_derived_hashes(store, monkeypatch):
    raw = _activity(PROVIDER_CSP)
    mock_devin(monkeypatch, session_id=BARE_ID, attachment_body=raw)
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'ready', value['message']
    assert value['validation']['raw_sha256'] == hashlib.sha256(raw).hexdigest()
    assert value['validation']['provider_csp_removed'].startswith("default-src 'none'")
    derived = practice.artifact_path(JOB_ID).read_bytes()
    assert hashlib.sha256(derived).hexdigest() != value['validation']['raw_sha256']


def test_attachment_is_downloaded_through_the_documented_v3_endpoint(store, monkeypatch):
    requests = mock_devin(monkeypatch, session_id=BARE_ID)
    practice.start(JOB_ID, mode='live')
    assert finished()['status'] == 'ready'
    official = [r for r in requests if r.url.path.endswith('/attachments/' + ATTACHMENT_ID + '/activity.html')]
    assert len(official) == 1 and official[0].url.host == 'api.devin.ai'
    assert official[0].headers['authorization'] == 'Bearer secret-api-key'
    assert not any(r.url.host == 'app.devin.ai' for r in requests)
    assert all('authorization' not in r.headers for r in requests if r.url.host != 'api.devin.ai')


@pytest.mark.parametrize('location, addresses', [
    ('https://evil.test/activity.html', [(2, 1, 6, '', ('8.8.8.8', 443))]),
    ('http://storage.googleapis.com/activity.html', [(2, 1, 6, '', ('8.8.8.8', 443))]),
    ('https://storage.googleapis.com/activity.html', [(2, 1, 6, '', ('10.0.0.5', 443))]),
    ('', [(2, 1, 6, '', ('8.8.8.8', 443))]),
])
def test_redirect_outside_the_allowlist_is_refused_without_forwarding_the_key(store, monkeypatch, location, addresses):
    requests = mock_devin(monkeypatch, session_id=BARE_ID, location=location)
    monkeypatch.setattr(practice.socket, 'getaddrinfo', lambda *args, **kwargs: addresses)
    practice.start(JOB_ID, mode='live')
    assert finished()['status'] == 'failed'
    assert not any(r.url.host not in ('api.devin.ai',) for r in requests)


@pytest.mark.parametrize('item', [
    {'name': 'activity.html', 'source': 'devin', 'url': 'https://storage.googleapis.com/x'},
    {'attachment_id': 'file-1', 'name': 'activity.html', 'source': 'devin'},
    {'name': 'activity.html', 'source': 'devin', 'url': 'https://app.devin.ai/attachments/' + ATTACHMENT_ID + '/other.html'},
])
def test_attachment_without_a_recognised_uuid_fails(store, monkeypatch, item):
    mock_devin(monkeypatch, session_id=BARE_ID, attachments=[item])
    practice.start(JOB_ID, mode='live')
    value = finished()
    assert value['status'] == 'failed' and 'identifiant' in value['message']


def test_uuid_from_the_app_link_when_metadata_lacks_it(store, monkeypatch):
    requests = mock_devin(monkeypatch, session_id=BARE_ID, attachments=[
        {'name': 'activity.html', 'source': 'devin', 'url': 'https://app.devin.ai/attachments/' + ATTACHMENT_ID + '/activity.html'}])
    practice.start(JOB_ID, mode='live')
    assert finished()['status'] == 'ready'
    assert not any(r.url.host == 'app.devin.ai' for r in requests)
