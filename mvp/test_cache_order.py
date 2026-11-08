"""Restart ordering and retry/dedup contracts; workers never call providers."""
from copy import deepcopy
from itertools import permutations
import pytest

from mvp import engine, workspace


@pytest.fixture
def cached_job(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'DATA', tmp_path)
    monkeypatch.setattr(engine, 'JOBS', {})
    workers = []
    class Worker:
        def __init__(self, **kwargs):
            workers.append(kwargs)
        def start(self):
            pass
    monkeypatch.setattr(engine.threading, 'Thread', Worker)
    seed = engine.launch('points', 'live', 'http://localhost:8000')
    return seed, workers


def test_ready_cache_result_survives_every_restart_load_order(cached_job):
    seed, workers = cached_job
    candidates = [dict(seed, id='ready-old', status='ready', created_at='2026-11-07T08:00:00+01:00'),
                  dict(seed, id='ready-new', status='ready', created_at='2026-11-07T09:00:00Z'),
                  dict(seed, id='in-flight', status='preparing', created_at='2026-11-07T12:00:00+01:00'),
                  dict(seed, id='failed-new', status='failed', created_at='2026-11-07T13:00:00+01:00')]
    for insertion_order in permutations(candidates):
        engine.JOBS.clear()
        engine.JOBS.update((job['id'], deepcopy(job)) for job in insertion_order)
        assert engine.launch('points', 'live', 'http://localhost:8000')['id'] == 'ready-new'
        assert engine.launch('points', 'live', 'http://localhost:8000', retry=True)['id'] == 'ready-new'
    assert len(workers) == 1


def test_inflight_dedup_then_latest_failure_and_explicit_retry(cached_job):
    seed, workers = cached_job
    failure_old = dict(seed, id='failed-old', status='failed', created_at='2026-11-07T08:00:00+01:00')
    failure_new = dict(seed, id='failed-new', status='failed', created_at='2026-11-07T09:00:00+01:00')
    pending = dict(seed, id='in-flight', status='preparing', created_at='2026-11-07T07:00:00+01:00')
    engine.JOBS.clear()
    engine.JOBS.update((job['id'], job) for job in (failure_new, pending, failure_old))
    assert engine.launch('points', 'live', 'http://localhost:8000')['id'] == 'in-flight'
    assert engine.launch('points', 'live', 'http://localhost:8000', retry=True)['id'] == 'in-flight'
    del engine.JOBS['in-flight']
    assert engine.launch('points', 'live', 'http://localhost:8000')['id'] == 'failed-new'
    retried = engine.launch('points', 'live', 'http://localhost:8000', retry=True)
    assert retried['id'] not in ('failed-old', 'failed-new')
    assert engine.launch('points', 'live', 'http://localhost:8000', retry=True)['id'] == retried['id']
    assert len(workers) == 2


def test_workspace_reports_are_chronological_with_mixed_offsets(monkeypatch):
    def report(identifier, created_at):
        return {'id':identifier, 'status':'ready', 'mode':'live', 'scenario':'points',
                'workspace_origin':'new_pronote', 'created_at':created_at, 'events':[]}
    # 10:30 +02 is earlier than 10:00 +01. Lexical timestamp sorting and glob
    # insertion order both give the wrong result for this deliberately mixed set.
    jobs = [report('old', '2026-11-07T10:30:00+02:00'),
            report('newest', '2026-11-07T09:30:00Z'),
            report('middle', '2026-11-07T10:00:00+01:00')]
    monkeypatch.setattr(workspace, 'JOBS', {job['id']:job for job in jobs})
    state = workspace._agent_state({'opens':[]})
    assert [job['id'] for job in state['reports']] == ['newest', 'middle', 'old']
