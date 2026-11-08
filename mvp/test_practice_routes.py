"""Practice HTTP contract: explicit mode, local writes, isolated HTML delivery."""
from fastapi.testclient import TestClient

from .app import app


def test_practice_routes_reject_unknown_reports_without_provider_calls(monkeypatch):
    from . import practice

    def missing(*args, **kwargs):
        raise KeyError('missing')

    for name in ('get', 'start', 'approve', 'artifact_path'):
        monkeypatch.setattr(practice, name, missing)
    client = TestClient(app)
    assert client.get('/api/jobs/missing/practice').status_code == 404
    assert client.post('/api/jobs/missing/practice', json={}).status_code == 404
    assert client.post('/api/jobs/missing/practice/approve').status_code == 404
    assert client.get('/api/jobs/missing/practice/preview').status_code == 404
    assert client.get('/api/jobs/missing/practice/download').status_code == 404


def test_practice_launch_is_explicit_and_rejects_extra_parameters(monkeypatch):
    from . import practice

    calls = []
    monkeypatch.setattr(practice, 'start', lambda job_id, **kwargs: calls.append((job_id, kwargs)) or {'status': 'running'})
    client = TestClient(app)
    assert client.post('/api/jobs/known/practice', json={}).status_code == 200
    assert calls == [('known', {'mode': 'simulation', 'retry': False})]
    assert client.post('/api/jobs/known/practice', json={'mode': 'live', 'retry': True}).status_code == 200
    assert calls[-1] == ('known', {'mode': 'live', 'retry': True})
    for body in ({'mode': 'unknown'}, {'prompt': 'Replace the analysis'}, {'html': '<script></script>'}):
        assert client.post('/api/jobs/known/practice', json=body).status_code == 422
    assert len(calls) == 2
    assert client.post('/api/jobs/known/practice', json={}, headers={'Origin': 'https://elsewhere.example'}).status_code == 403
    assert client.post('/api/jobs/known/practice/approve', headers={'Origin': 'https://elsewhere.example'}).status_code == 403


def test_preview_is_sandboxed_and_download_uses_the_approval_guard(monkeypatch, tmp_path):
    from . import practice

    artifact = tmp_path / 'activity.html'
    artifact.write_text('<!doctype html><html lang="fr"><body>Entraînement</body></html>')
    approved = False

    def guarded(job_id, download=False):
        if download and not approved:
            raise ValueError('Validez l’entraînement avant de le télécharger.')
        return artifact

    monkeypatch.setattr(practice, 'artifact_path', guarded)
    client = TestClient(app)
    response = client.get('/api/jobs/known/practice/preview')
    assert response.status_code == 200
    policy = response.headers['content-security-policy']
    assert 'sandbox allow-scripts;' in policy
    assert 'allow-same-origin' not in policy
    for directive in ("default-src 'none'", "connect-src 'none'", "frame-ancestors 'self'", "form-action 'none'"):
        assert directive in policy
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert client.get('/api/jobs/known/practice/download').status_code == 409
    approved = True
    response = client.get('/api/jobs/known/practice/download')
    assert response.status_code == 200
    assert 'attachment;' in response.headers['content-disposition']
    assert 'entrainement-pythagore.html' in response.headers['content-disposition']
    assert 'sandbox allow-scripts;' in response.headers['content-security-policy']


def test_practice_status_does_not_cache_report_state(monkeypatch):
    from . import practice

    monkeypatch.setattr(practice, 'get', lambda _: {'status': 'not_started', 'configured': False})
    response = TestClient(app).get('/api/jobs/known/practice')
    assert response.status_code == 200
    assert response.json()['configured'] is False
    assert response.headers['cache-control'] == 'no-store'
