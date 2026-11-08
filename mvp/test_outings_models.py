"""Models transport executes model-selected calls, with no Agents session."""
import json

import httpx
import pytest

from . import outings_models as models


def tool_call(name, arguments=None, identifier=None):
    return {'id': identifier or 'call-' + name, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments or {})}}


def response(calls, identifier='completion-real-id'):
    return {'id': identifier, 'model': 'holo4-27b', 'usage': {'total_tokens': 20},
            'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': calls}}]}


def factory(handler):
    return lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs)


def run(functions, handler, missing, **kwargs):
    records = []
    models.run_function_calls(api_key='test-key', model='holo4-27b', functions=functions,
                             prompt='Simulation sans effets externes.', missing=missing,
                             guard=kwargs.pop('guard', lambda: None), on_response=records.append,
                             client_factory=factory(handler), **kwargs)
    return records


def test_holo4_chooses_calls_and_actual_receipts_are_returned_between_rounds():
    used, executed, requests = set(), [], []

    def read_context() -> str:
        executed.append('read_context')
        return '{"mode":"simulation"}'

    def prepare() -> str:
        executed.append('prepare')
        used.add('prepare')
        return '{"receipt_id":"actual-opaque-receipt"}'

    def follow_up(receipt: str) -> str:
        assert receipt == 'actual-opaque-receipt'
        executed.append('follow_up')
        used.add('follow_up')
        return '{"simulated":true}'

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url == models.ENDPOINT
        assert request.headers['authorization'] == 'Bearer test-key'
        assert payload['model'] == 'holo4-27b' and payload['tool_choice'] == 'required'
        if len(requests) == 1:
            return httpx.Response(200, json=response([tool_call('read_context'), tool_call('prepare')]))
        tools = [message for message in payload['messages'] if message['role'] == 'tool']
        assert json.loads(tools[-1]['content'])['receipt_id'] == 'actual-opaque-receipt'
        return httpx.Response(200, json=response([tool_call('follow_up', {'receipt':'actual-opaque-receipt'})], 'completion-second-id'))

    records = run([read_context, prepare, follow_up], handler, lambda: {'prepare','follow_up'} - used)
    assert executed == ['read_context','prepare','follow_up']
    assert len(requests) == 2
    assert [record['id'] for record in records] == ['completion-real-id','completion-second-id']


def test_unknown_and_invalid_arguments_never_execute_handlers():
    executed, requests = [], []

    def allowed(receipt: str) -> str:
        executed.append(receipt)
        return '{}'

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(200, json=response([
                tool_call('send_real_mail', identifier='unknown'),
                tool_call('allowed', {'receipt': True}, identifier='bad-type'),
                tool_call('allowed', {'receipt':'x', 'extra':'forbidden'}, identifier='extra-field'),
            ]))
        errors = [json.loads(message['content']) for message in payload['messages'] if message['role'] == 'tool']
        assert len(errors) == 3 and all(item['external_effects'] is False and item['error'] for item in errors)
        return httpx.Response(200, json=response([tool_call('allowed', {'receipt':'model-selected'})]))

    run([allowed], handler, lambda: set() if executed else {'allowed'})
    assert executed == ['model-selected']


def test_stale_guard_after_response_prevents_local_mutation():
    checks, executed = [], []

    def allowed() -> str:
        executed.append(True)
        return '{}'

    def guard():
        checks.append(True)
        if len(checks) == 2:
            raise RuntimeError('newer run replaced this one')

    with pytest.raises(RuntimeError, match='newer run'):
        run([allowed], lambda request: httpx.Response(200, json=response([tool_call('allowed')])),
            lambda: {'allowed'}, guard=guard)
    assert executed == []


def test_missing_tools_are_never_started_by_the_driver():
    executed, requests = [], []

    def allowed() -> str:
        executed.append(True)
        return '{}'

    def handler(request):
        requests.append(True)
        return httpx.Response(200, json=response([]))

    with pytest.raises(models.ModelsError, match='limite de tours'):
        run([allowed], handler, lambda: {'allowed'}, max_rounds=2)
    assert len(requests) == 2 and executed == []


def test_provider_error_never_exposes_response_body_or_executes_tools():
    def handler(request):
        return httpx.Response(403, text='private provider body and credentials')

    with pytest.raises(models.ModelsError, match=r'HTTP 403') as error:
        run([], handler, lambda: {'missing'})
    assert 'private' not in str(error.value) and 'credentials' not in str(error.value)


def test_duplicate_tool_call_ids_are_rejected_before_dispatch():
    executed = []

    def allowed() -> str:
        executed.append(True)
        return '{}'

    with pytest.raises(models.ModelsError, match='identifiants'):
        run([allowed], lambda request: httpx.Response(200, json=response([
            tool_call('allowed', identifier='same'), tool_call('allowed', identifier='same')])), lambda: {'allowed'})
    assert executed == []


def test_schema_requires_only_declared_string_arguments():
    def allowed(receipt: str) -> str:
        return receipt

    parameters = models.tool_schema(allowed)['function']['parameters']
    assert parameters == {'type':'object', 'properties':{'receipt':{'type':'string'}},
                          'required':['receipt'], 'additionalProperties':False}
