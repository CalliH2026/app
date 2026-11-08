"""Outing API validation, export access, and state transitions; no providers."""
from fastapi.testclient import TestClient

from .app import app


def test_unknown_outings_cannot_be_read_or_written(monkeypatch, tmp_path):
    from . import outings
    monkeypatch.setattr(outings, 'FOLDER', tmp_path)
    client = TestClient(app)
    assert client.get('/api/outings/missing').status_code == 404
    assert client.get('/api/outings/missing/export').status_code == 404
    assert client.post('/api/outings/missing/save').status_code == 404
    assert client.post('/api/outings/missing/objective', json={'objective': 'Observer des œuvres.'}).status_code == 404


def test_request_rejects_invalid_values_before_launch(monkeypatch):
    from . import outings
    calls = []
    monkeypatch.setattr(outings, 'start', lambda payload: calls.append(payload))
    client = TestClient(app)
    for extra in ({'mode': 'demo'}, {'adults': 0}, {'objective': 'x' * 4001}, {'duration_minutes': 0}):
        response = client.post('/api/outings', json={'date': '2026-11-12', **extra})
        assert response.status_code == 422
    assert not calls


def test_export_is_an_attachment_and_save_conflicts(monkeypatch):
    from . import outings
    client = TestClient(app)
    monkeypatch.setattr(outings, 'export_text', lambda identifier: 'Dossier · à relire\nObjectif pédagogique')
    response = client.get('/api/outings/known/export')
    assert response.status_code == 200
    assert response.text.startswith('Dossier · à relire')
    assert response.headers['content-type'].startswith('text/plain')
    assert response.headers['cache-control'] == 'no-store'
    assert 'attachment;' in response.headers['content-disposition']
    def preparing(identifier):
        raise RuntimeError('La préparation est en cours.')
    monkeypatch.setattr(outings, 'save_dossier', preparing)
    assert client.post('/api/outings/known/save').status_code == 409
    assert client.post('/api/outings/known/save', headers={'Origin': 'https://elsewhere.example'}).status_code == 403
