"""Cancellation, partial results and objective changes during Holo4 executions."""
import json
import threading
import pytest
import httpx
from . import outings
from .outings_orchestration import OutingExecutionPool
from .test_outings import store, visit
from .test_outings_holo_integration import job_for, local_providers, COLLECTORS


def test_pool_close_cancels_requested_work_and_blocks_late_publication(store, monkeypatch):
    local_providers(monkeypatch)
    started, release = threading.Event(), threading.Event()
    def delayed_visit(value):
        started.set()
        assert release.wait(3)
        return visit()
    monkeypatch.setattr(outings, '_search_visit', delayed_visit)
    job = job_for(store, monkeypatch)
    pool = OutingExecutionPool(job)
    ticket = pool.request('search_museum_visit', tool_call_id='h-call-1')
    assert started.wait(3)
    pool.close()
    assert job['executions'][0]['id'] == ticket['execution_id']
    assert job['executions'][0]['status'] == 'cancelled'
    assert job['executions'][0]['tool_call_id'] == 'h-call-1'
    assert len(job['executions']) == 1
    assert all(task['status']=='failed' for task in job['tasks'] if task['id'] != 'dossier')
    snapshot = json.dumps(job, sort_keys=True)
    release.set()
    pool.futures['search_museum_visit'].result(timeout=3)
    assert job['visit'] is None
    assert json.dumps(job, sort_keys=True) == snapshot
    with pytest.raises(RuntimeError):
        pool.request('prepare_transport_and_calendar')
    pool.close()
    assert json.dumps(job, sort_keys=True) == snapshot


def test_failed_provider_is_visible_and_other_holo4_executions_complete(store, monkeypatch):
    local_providers(monkeypatch)
    monkeypatch.setattr(outings, '_search_visit', lambda _: (_ for _ in ()).throw(httpx.ConnectError('private-test-secret')))
    job = job_for(store, monkeypatch)
    pool = OutingExecutionPool(job)
    try:
        for name in COLLECTORS:
            pool.request(name, tool_call_id='h-'+name)
        result = pool.wait_for_results(timeout=3)
        assert result['ready'] is True
        assert result['pending'] == []
        statuses = {e['task_id']: e['status'] for e in result['executions']}
        assert statuses == {'visit':'failed', 'route':'succeeded', 'roster':'succeeded'}
        assert job['roster']['student_count'] == 28
        assert job['budget']['total'] is None
        assert job['budget']['known_total'] == '180.00'
        assert 'private-test-secret' not in json.dumps(job)
        assert next(t for t in job['tasks'] if t['id']=='visit')['error']
    finally:
        pool.close()


def test_pending_results_do_not_replace_latest_teacher_objective(store, monkeypatch):
    local_providers(monkeypatch)
    started, release = threading.Event(), threading.Event()
    def delayed_visit(value):
        started.set()
        assert release.wait(3)
        return visit()
    monkeypatch.setattr(outings, '_search_visit', delayed_visit)
    job = job_for(store, monkeypatch)
    pool = OutingExecutionPool(job)
    try:
        for name in COLLECTORS:
            pool.request(name)
        assert started.wait(3)
        with pytest.raises(ValueError):
            pool.assert_ready()
        outings.update_objective(job['id'], 'Comparer deux œuvres puis construire un carnet collectif.')
        release.set()
        assert pool.wait_for_results(timeout=3)['ready'] is True
        assert 'carnet collectif' in job['dossier']['text']
        assert 'carnet collectif' in job['dossier']['family_letter']
        assert job['dossier']['revision'] == job['revision'] == 2
    finally:
        release.set()
        pool.close()
