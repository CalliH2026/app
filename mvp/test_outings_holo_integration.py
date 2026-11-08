"""Holo4 chooses the calls; providers begin only through its exposed tools."""
from types import SimpleNamespace
import json
import threading
import time
import pytest
from . import outings
from .test_outings import store, visit

COLLECTORS = ('search_museum_visit', 'prepare_transport_and_calendar', 'read_class_and_template')
TOOL_NAMES = {*COLLECTORS, 'wait_for_outing_results', 'read_outing_evidence', 'fill_administrative_dossier'}
PROOF = {'verified':True, 'urls':['https://www.musee-orsay.fr/fr/'],
         'observations':[{'visual':True}], 'actions':[{'tool':'scroll_web'}]}


def job_for(store, monkeypatch):
    # Obtain the real initial state without starting either H or providers.
    monkeypatch.setattr(outings, '_execute', lambda _: None)
    result = outings.start(store)
    return outings.JOBS[result['id']]


def local_providers(monkeypatch):
    monkeypatch.setattr(outings, '_search_visit', lambda _: visit())
    monkeypatch.setattr(outings, '_route_and_calendar', lambda *_: (None, {'conflicts':[]}))


def install_client(monkeypatch, proof=PROOF, scenario=None):
    import hai_agents
    from . import outings_workstation
    seen = {}
    class Session:
        id = 'test-session'
        def wait_for_completion(self, **kwargs):
            tools = {tool.__name__:tool for tool in seen['tools']}
            seen['tool_map'] = tools
            if scenario:
                scenario(tools, seen)
            else:
                tools['read_outing_evidence']()
                for name in COLLECTORS:
                    tools[name]()
                tools['wait_for_outing_results']()
                tools['read_outing_evidence']()
                tools['fill_administrative_dossier']()
            return SimpleNamespace(answer={'summary':'Brouillon préparé.'}, status='completed')
        def status(self): return {'status':'completed'}
        def cancel(self): seen['cancelled'] = True
    class Client:
        def __init__(self, **kwargs): pass
        def start_session(self, **kwargs):
            seen.update(kwargs)
            return Session()
    monkeypatch.setattr(hai_agents, 'Client', Client)
    monkeypatch.setattr(outings, 'key', lambda _: 'test-only')
    monkeypatch.setattr(outings_workstation, 'workstation_evidence', lambda *args: proof)
    return seen


def test_holo4_has_ephemeral_cloud_workstation_and_real_function_calls(store, monkeypatch):
    local_providers(monkeypatch)
    seen = install_client(monkeypatch)
    job = job_for(store, monkeypatch)
    outings._fill_with_h(job)
    assert seen['agent']['model'] == 'holo4-27b'
    workstation = seen['agent']['environments'][0]
    assert workstation['kind'] == 'workstation'
    assert workstation['host'] == 'cloud'
    assert workstation['storage'] == {'ephemeral': True}
    assert not {'session_id', 'mode', 'start_url', 'volume_id', 'use_default_volume'} & workstation.keys()
    assert seen['idle_timeout_s'] is None
    assert job['agent']['environment'] == 'workstation'
    assert job['agent']['storage'] == 'ephemeral'
    assert job['agent']['host'] == 'cloud'
    assert {tool.__name__ for tool in seen['tools']} == TOOL_NAMES
    assert {c['name'] for c in job['tool_calls']} == TOOL_NAMES
    assert all(c['status']=='succeeded' for c in job['tool_calls'])
    assert {e['tool_name'] for e in job['executions']} == set(COLLECTORS)
    assert all(e['status']=='succeeded' for e in job['executions'])
    assert all(e['requested_by']=='holo4' and e['tool_call_id'] for e in job['executions'])
    assert job['agent']['computer_use_verified'] is True
    assert 'Holo4' in job['dossier']['filled_by']


def test_holo4_dispatches_nonblocking_collectors_that_really_overlap(store, monkeypatch):
    barrier = threading.Barrier(3, timeout=3)
    original_roster = outings._read_roster
    def checked_visit(value):
        barrier.wait()
        return visit()
    def checked_route(value, agenda):
        barrier.wait()
        return None, {'conflicts':[]}
    def checked_roster(value):
        barrier.wait()
        return original_roster(value)
    monkeypatch.setattr(outings, '_search_visit', checked_visit)
    monkeypatch.setattr(outings, '_route_and_calendar', checked_route)
    monkeypatch.setattr(outings, '_read_roster', checked_roster)
    install_client(monkeypatch)
    job = job_for(store, monkeypatch)
    outings._fill_with_h(job)
    executions = job['executions']
    assert len(executions) == 3
    # The barrier can succeed only if all three provider functions overlap.
    assert all(e['status']=='succeeded' for e in executions)
    assert max(e['started_at'] for e in executions) <= min(e['ended_at'] for e in executions)
    assert all(task['status']=='done' for task in job['tasks'] if task['id']!='dossier')


def test_repeated_holo4_requests_reuse_one_execution(store, monkeypatch):
    local_providers(monkeypatch)
    started, release = threading.Event(), threading.Event()
    calls = []
    def delayed_visit(value):
        calls.append('visit')
        started.set()
        assert release.wait(3)
        return visit()
    monkeypatch.setattr(outings, '_search_visit', delayed_visit)
    def scenario(tools, seen):
        first = json.loads(tools['search_museum_visit']())
        assert started.wait(3)
        second = json.loads(tools['search_museum_visit']())
        assert first['execution_id'] == second['execution_id']
        assert second['cached'] is True
        assert calls == ['visit']
        release.set()
        tools['prepare_transport_and_calendar']()
        tools['read_class_and_template']()
        tools['wait_for_outing_results']()
        tools['read_outing_evidence']()
        tools['fill_administrative_dossier']()
    install_client(monkeypatch, scenario=scenario)
    job = job_for(store, monkeypatch)
    outings._fill_with_h(job)
    assert calls == ['visit']
    assert len([e for e in job['executions'] if e['task_id']=='visit']) == 1


def test_holo4_cannot_fill_before_requesting_and_finishing_dependencies(store, monkeypatch):
    local_providers(monkeypatch)
    def scenario(tools, seen):
        tools['read_outing_evidence']()
        with pytest.raises(ValueError):
            tools['wait_for_outing_results']()
        with pytest.raises(ValueError):
            tools['fill_administrative_dossier']()
        for name in COLLECTORS:
            tools[name]()
        tools['wait_for_outing_results']()
        tools['read_outing_evidence']()
        tools['fill_administrative_dossier']()
    install_client(monkeypatch, scenario=scenario)
    job = job_for(store, monkeypatch)
    outings._fill_with_h(job)
    assert job.get('dossier')
    assert any(c['status']=='failed' and c['name']=='fill_administrative_dossier' for c in job['tool_calls'])


def test_workstation_configuration_alone_cannot_claim_hybrid_success(store, monkeypatch):
    local_providers(monkeypatch)
    seen = install_client(monkeypatch, {'verified':False,'urls':[],'observations':[], 'actions':[]})
    job = job_for(store, monkeypatch)
    with pytest.raises(ValueError):
        outings._fill_with_h(job)
    assert not job.get('dossier') or 'Holo4' not in job['dossier'].get('filled_by', '')
    assert not job['agent'].get('computer_use_verified')
    assert job['tool_calls'][-1]['status'] == 'failed'
    assert seen['cancelled'] is True


def test_ephemeral_environment_serializes_as_a_real_workstation_in_installed_sdk():
    from pydantic import TypeAdapter
    from hai_agents.types.environment import Environment, Environment_Workstation
    from .outings_workstation import workstation_environment
    environment = TypeAdapter(Environment).validate_python(workstation_environment())
    assert isinstance(environment, Environment_Workstation)
    assert environment.host == 'cloud'
    assert environment.storage.ephemeral is True
    assert environment.storage.volume_id is None
    assert environment.storage.use_default_volume is None
    assert environment.session_id is None
    payload = environment.model_dump(mode='json', exclude_none=True)
    assert payload['storage'] == {'ephemeral': True}
    assert payload['kind'] == 'workstation'
    assert not {'mode', 'start_url', 'session_id'} & payload.keys()


def timeout_client(monkeypatch, cancel_error=None):
    import hai_agents
    seen = {'cancelled': 0}

    class Session:
        id = 'timeout-session'

        def wait_for_completion(self, **kwargs):
            raise TimeoutError('Session timeout-session did not settle within 300s')

        def status(self):
            return {'status': 'running'}

        def cancel(self):
            seen['cancelled'] += 1
            if cancel_error:
                raise cancel_error

    class Client:
        def __init__(self, **kwargs): pass

        def start_session(self, **kwargs):
            return Session()

    monkeypatch.setattr(hai_agents, 'Client', Client)
    monkeypatch.setattr(outings, 'key', lambda _: 'test-only')
    return seen


def test_timeout_without_tool_call_is_reported_as_timeout_with_an_unconfirmed_cancel(store, monkeypatch):
    execute = outings._execute
    local_providers(monkeypatch)
    seen = timeout_client(monkeypatch)
    job = job_for(store, monkeypatch)
    execute(job)
    assert seen['cancelled'] == 1
    assert job['session_cancel']['state'] == 'cancel_requested'
    assert job['session_cleanup']['provider_status_before'] == 'running'
    assert job['session_cleanup']['release_requested'] is False
    assert job['h_outcome'] == 'timeout' and 'délai de 300 s' in job['h_error']
    assert not job.get('tool_calls') and not job.get('executions')
    assert not any(t['status'] == 'done' for t in job['tasks'])
    assert job['status'] == 'partial'


def test_failed_cancel_request_is_recorded(store, monkeypatch):
    execute = outings._execute
    local_providers(monkeypatch)
    seen = timeout_client(monkeypatch, cancel_error=RuntimeError('provider refused'))
    job = job_for(store, monkeypatch)
    execute(job)
    assert seen['cancelled'] == 1
    assert job['session_cancel'] == {'requested_at': job['session_cancel']['requested_at'], 'state': 'cancel_failed',
                                     'error': 'RuntimeError'}
    assert job['h_outcome'] == 'timeout'
