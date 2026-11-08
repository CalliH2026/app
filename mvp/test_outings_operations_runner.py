"""Holo4 has only local simulation tools during the operations demonstration."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from . import outings, outings_operations as simulation
from . import outings_operations_runner as runner
from .test_outings import store
from .test_outings_operations_routes import prepared_job

ORDER = ('prepare_parent_messages_demo', 'prepare_photo_permissions_demo', 'check_equipment_demo',
         'simulate_parent_responses_demo', 'reserve_equipment_demo',
         'prepare_targeted_reminders_demo', 'prepare_administration_demo')
RECEIPT_INPUTS = {
    'simulate_parent_responses_demo': {'message_receipt':'prepare_parent_messages_demo'},
    'reserve_equipment_demo': {'inventory_receipt':'check_equipment_demo'},
    'prepare_targeted_reminders_demo': {'responses_receipt':'simulate_parent_responses_demo'},
    'prepare_administration_demo': {
        'reminders_receipt':'prepare_targeted_reminders_demo',
        'equipment_receipt':'reserve_equipment_demo',
        'photo_receipt':'prepare_photo_permissions_demo',
    },
}


def running_job(store, monkeypatch):
    job = prepared_job(store, monkeypatch)
    job['session_id'] = 'original-preparation-session'
    job['operations'] = {'run_id':'c'*12, 'mode':'simulation', 'simulated':True, 'external_effects':False,
                         'status':'running', 'snapshot_revision':job['revision'], 'stale':False,
                         'started_at':outings.now(), 'session_id':None, 'h_tools_completed':[]}
    simulation.ensure(job)
    return job


def fake_client(monkeypatch, scenario=None):
    import hai_agents
    seen = {}
    class Session:
        id = 'operations-only-session'
        def wait_for_completion(self, **kwargs):
            tools = {tool.__name__: tool for tool in seen['tools']}
            if scenario is not None:
                scenario(tools)
            else:
                tools['read_outing_evidence']()
                receipts = {}
                for name in ORDER:
                    arguments = {argument:receipts[previous] for argument,previous in RECEIPT_INPUTS.get(name, {}).items()}
                    result = json.loads(tools[name](**arguments))
                    assert result['mode']=='simulation' and result['external_effects'] is False
                    receipts[name] = result['receipt_id']
                    if name == 'prepare_parent_messages_demo':
                        repeated = json.loads(tools[name]())
                        assert repeated['cached'] is True
                        assert repeated['receipt_id'] == receipts[name]
            return SimpleNamespace(status='completed', answer={'summary':'Simulation locale terminée, aucun envoi réel.'})
        def status(self): return {'status':'completed'}
        def cancel(self): seen['cancelled'] = True
    class Client:
        def __init__(self, **kwargs): pass
        def start_session(self, **kwargs):
            seen.update(kwargs)
            return Session()
    monkeypatch.setattr(hai_agents, 'Client', Client)
    monkeypatch.setattr('mvp.integrations.key', lambda name:'test-only')
    return seen


def test_all_operations_run_through_holo4_without_external_capabilities(store, monkeypatch):
    job = running_job(store, monkeypatch)
    before = deepcopy({key:job.get(key) for key in ('session_id','status','dossier','browser_evidence')})
    seen = fake_client(monkeypatch)
    runner.execute(job, job['operations']['run_id'])
    ops = job['operations']
    assert seen['agent']['environments'] == []
    assert seen['agent']['model'].startswith('holo4')
    assert 'idle_timeout_s' in seen and seen['idle_timeout_s'] is None
    assert {tool.__name__ for tool in seen['tools']} == {'read_outing_evidence', *ORDER}
    assert ops['status']=='ready' and len(ops['h_tools_completed'])==7
    assert ops['session_id']=='operations-only-session'
    assert {key:job.get(key) for key in before} == before
    assert ops['counts']['confirmed']==20 and ops['counts']['declined']==2 and ops['counts']['pending']==6
    assert ops['counts']['initial_messages']==28 and ops['counts']['confirmation_messages']==20
    assert ops['counts']['reminders']==6
    assert all(message['actual_sent'] is False and message['recipient'].endswith('.invalid') for message in ops['messages'])
    assert all(reservation['actual_reserved'] is False for reservation in ops['equipment']['reservations'])
    assert ops['admin']['actual_approved'] is False and ops['admin']['actual_signatures']==0
    calls = [call for call in job['tool_calls'] if call.get('session_id')=='operations-only-session']
    assert {call['name'] for call in calls} == {'read_outing_evidence', *ORDER}
    assert all(call['status']=='succeeded' for call in calls)
    assert any(call['name']=='prepare_parent_messages_demo' and call['cached'] for call in calls)


def test_objective_revision_change_stops_the_old_operations_run(store, monkeypatch):
    job = running_job(store, monkeypatch)
    def changed_after_read(tools):
        tools['read_outing_evidence']()
        outings.update_objective(job['id'], 'Un objectif modifié pendant la démonstration.')
        tools['prepare_parent_messages_demo']()
    seen = fake_client(monkeypatch, changed_after_read)
    runner.execute(job, job['operations']['run_id'])
    assert job['operations']['status']=='failed'
    assert job['operations']['stale'] is True
    assert not job['operations']['messages']
    assert seen['cancelled'] is True
    assert job['session_id']=='original-preparation-session'


def test_holo4_cannot_finish_without_calling_all_demo_steps(store, monkeypatch):
    job = running_job(store, monkeypatch)
    def incomplete(tools):
        tools['read_outing_evidence']()
        tools['prepare_parent_messages_demo']()
    seen = fake_client(monkeypatch, incomplete)
    runner.execute(job, job['operations']['run_id'])
    assert job['operations']['status']=='failed'
    assert job['operations']['completed_steps']==['parent_messages']
    assert job['operations']['photo']=={} and job['operations']['equipment']=={}
    assert seen['cancelled'] is True


def test_holo4_cannot_skip_dependencies_with_a_forged_receipt(store, monkeypatch):
    job = running_job(store, monkeypatch)
    def forged_receipt(tools):
        tools['read_outing_evidence']()
        result = json.loads(tools['prepare_parent_messages_demo']())
        assert result['receipt_id']
        tools['simulate_parent_responses_demo'](message_receipt='invented-before-reading-the-response')
    seen = fake_client(monkeypatch, forged_receipt)
    runner.execute(job, job['operations']['run_id'])
    assert job['operations']['status']=='failed'
    assert job['operations']['completed_steps']==['parent_messages']
    assert all(family['response']=='pending' for family in job['operations']['families'])
    assert job['operations']['counts']['confirmation_messages']==0
    assert seen['cancelled'] is True


def test_old_holo4_callbacks_cannot_mutate_a_replacement_run(store, monkeypatch):
    job = running_job(store, monkeypatch)
    old_run_id = job['operations']['run_id']
    replacement = None
    def replaced_after_read(tools):
        nonlocal replacement
        tools['read_outing_evidence']()
        replacement = deepcopy(job['operations'])
        replacement.update(run_id='d'*12, session_id='newer-operations-session')
        job['operations'] = replacement
        tools['prepare_parent_messages_demo']()
    seen = fake_client(monkeypatch, replaced_after_read)
    runner.execute(job, old_run_id)
    assert job['operations'] is replacement
    assert replacement['status']=='running' and replacement['session_id']=='newer-operations-session'
    assert not replacement['messages'] and replacement['h_tools_completed']==[]
    assert 'error' not in replacement and 'session_cleanup' not in replacement
    assert seen['cancelled'] is True


def test_demo_mutations_have_no_network_mail_or_reservation_transport_imports():
    tree = ast.parse(Path(simulation.__file__).read_text())
    forbidden = {'smtplib','imaplib','socket','httpx','requests','urllib','subprocess'}
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imports.extend(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom): imports.append((node.module or '').split('.')[0])
    assert not forbidden.intersection(imports)


def test_models_api_orchestrates_same_simulation_without_an_agents_session(store, monkeypatch):
    import httpx
    import hai_agents
    from . import outings_models as models
    job = running_job(store, monkeypatch)
    job['operations']['execution_mode'] = 'models_api'
    monkeypatch.setattr('mvp.integrations.key', lambda name: 'test-model-key')
    class ForbiddenAgentsClient:
        def __init__(self, **kwargs):
            raise AssertionError('Models transport must not create an Agents client/session')
    monkeypatch.setattr(hai_agents, 'Client', ForbiddenAgentsClient)
    rounds = []

    def handler(request):
        payload = json.loads(request.content)
        rounds.append(payload)
        names_by_id = {call['id']:call['function']['name']
                       for message in payload['messages'] for call in message.get('tool_calls', [])}
        receipts = {names_by_id[message['tool_call_id']]:json.loads(message['content']).get('receipt_id')
                    for message in payload['messages'] if message['role']=='tool'}
        groups = [
            ['read_outing_evidence'],
            list(ORDER[:3]),
            list(ORDER[3:5]),
            ['prepare_targeted_reminders_demo'],
            ['prepare_administration_demo'],
        ]
        calls = []
        for name in groups[len(rounds)-1]:
            arguments = {argument:receipts[previous] for argument,previous in RECEIPT_INPUTS.get(name, {}).items()}
            calls.append({'id':f'call-{len(rounds)}-{name}', 'type':'function',
                          'function':{'name':name, 'arguments':json.dumps(arguments)}})
        return httpx.Response(200, json={'id':f'real-provider-response-{len(rounds)}', 'model':'holo4-27b',
                                        'choices':[{'message':{'role':'assistant','content':None,'tool_calls':calls}}]})

    original = models.run_function_calls
    def fake_transport(**kwargs):
        kwargs['client_factory'] = lambda **options:httpx.Client(transport=httpx.MockTransport(handler), **options)
        return original(**kwargs)
    monkeypatch.setattr(models, 'run_function_calls', fake_transport)
    runner.execute(job, job['operations']['run_id'])
    ops = job['operations']
    assert ops['status']=='ready' and ops['provider_status']=='completed'
    assert ops['session_id'] is None and ops['trace_id']=='holo4-models:'+'c'*12
    assert len(ops['model_requests'])==5 and len(ops['h_tools_completed'])==7
    calls = [call for call in job['tool_calls'] if call.get('session_id')==ops['trace_id']]
    assert len(calls)==8 and all(call['status']=='succeeded' for call in calls)
    assert ops['counts']['confirmed']==20 and ops['counts']['reminders']==6
    assert len(ops['messages'])==74 and all(message['actual_sent'] is False for message in ops['messages'])
    assert all(reservation['actual_reserved'] is False for reservation in ops['equipment']['reservations'])
    assert job['session_id']=='original-preparation-session'
