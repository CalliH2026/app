"""Only simulated outing operations can be requested through the public API."""
from copy import deepcopy
from fastapi.testclient import TestClient

from .app import app
from . import outings
from .test_outings import store, visit
from .test_outings_holo_integration import job_for


def prepared_job(store, monkeypatch):
    job = job_for(store, monkeypatch)
    job.update(status='partial', roster=outings._read_roster(store), visit=visit())
    for task in job['tasks']:
        task['status'] = 'done'
    budget, dossier, warnings = outings._build_dossier(job)
    job.update(budget=budget, dossier=dossier, warnings=warnings)
    outings._persist(job)
    return job


def test_unknown_operations_job_is_not_created(store):
    client = TestClient(app)
    assert client.post('/api/outings/aaaaaaaaaaaa/operations-demo', json={}).status_code == 404
    assert outings.JOBS == {}


def test_live_mode_and_real_recipient_options_are_rejected_before_launch(store, monkeypatch):
    calls = []
    monkeypatch.setattr(outings, 'start_operations_demo', lambda identifier: calls.append(identifier))
    client = TestClient(app)
    for payload in ({'mode':'live'}, {'mode':'simulation', 'recipients':['parent@example.org']},
                    {'mode':'simulation', 'send':True}, {'mode':'simulation', 'transport':'smtp'}):
        response = client.post('/api/outings/aaaaaaaaaaaa/operations-demo', json=payload)
        assert response.status_code == 422
    assert calls == []


def test_operations_require_finished_preparation_and_a_roster(store, monkeypatch):
    job = job_for(store, monkeypatch)
    client = TestClient(app)
    assert client.post('/api/outings/'+job['id']+'/operations-demo', json={}).status_code == 409
    job['status'] = 'partial'
    assert client.post('/api/outings/'+job['id']+'/operations-demo', json={}).status_code == 409
    job['dossier'] = {'text':'Brouillon fictif'}
    assert client.post('/api/outings/'+job['id']+'/operations-demo', json={}).status_code == 409
    assert not job.get('operations')


def test_repeated_launch_reuses_running_demo_and_preserves_preparation(store, monkeypatch):
    job = prepared_job(store, monkeypatch)
    initial_status, dossier = job['status'], deepcopy(job['dossier'])
    launched = []
    class Worker:
        def __init__(self, **kwargs): self.kwargs = kwargs
        def start(self): launched.append(self.kwargs)
    monkeypatch.setattr(outings.threading, 'Thread', Worker)
    client = TestClient(app)
    first = client.post('/api/outings/'+job['id']+'/operations-demo', json={'mode':'simulation'})
    assert first.status_code == 200
    assert first.json()['operations']['status'] == 'running'
    assert first.json()['operations']['mode'] == 'simulation'
    assert first.json()['operations']['external_effects'] is False
    second = client.post('/api/outings/'+job['id']+'/operations-demo', json={})
    assert second.status_code == 200
    assert len(launched) == 1
    assert job['status'] == initial_status and job['dossier'] == dossier
    assert client.post('/api/outings/'+job['id']+'/operations-demo', json={},
                       headers={'Origin':'https://elsewhere.example'}).status_code == 403
