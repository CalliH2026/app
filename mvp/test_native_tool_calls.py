"""Real native callback counts and multi-query provenance, without paid calls."""
import copy
import json
from types import SimpleNamespace

from . import engine, native_pipeline as pipeline
from .test_native_pipeline import EXTERNAL, answer, case, isolated, services


def test_native_trace_counts_callbacks_not_activity_messages(case, isolated):
    calls = []
    first = pipeline.schedule(case, services=services(calls), background=False)
    assert first['status'] == 'ready'
    trace = first['tool_calls']
    assert [call['name'] for call in trace] == [
        'read_native_documents', 'transcribe_audio', 'search_resources']
    assert all(call['status'] == 'succeeded' and call['session_id'] == 'h-test-session' for call in trace)
    assert len(first['events']) > len(trace)
    reopened = pipeline.schedule(case, services=services(calls), background=False)
    assert reopened['tool_calls'] == trace


def test_native_searches_are_distinct_cached_and_have_stable_merged_ids(case, isolated):
    calls, results = [], []
    service = services(calls)

    class Client:
        def start_session(self, **kwargs):
            tools = {tool.__name__: tool for tool in kwargs['tools']}
            tools['read_native_documents']()
            tools['transcribe_audio']()
            for topic, purpose in [('Justifier Pythagore au collège', 'reference'),
                                   ('Exercice de rédaction Pythagore', 'exercise'),
                                   ('  EXERCICE de rédaction Pythagore  ', 'exercise')]:
                results.append(json.loads(tools['search_resources'](topic, purpose)))
            return SimpleNamespace(id='multi-query-session', wait_for_completion=lambda **_: SimpleNamespace(
                status='idle', answer=answer(), error=None))

    def search(topic):
        calls.append(('linkup', topic))
        sources = copy.deepcopy(EXTERNAL)
        if topic.startswith('Exercice'):
            sources.append({**sources[0], 'id': 'web-2', 'url': 'https://eduscol.education.fr/exercise'})
        return {'provider': 'Linkup', 'query': topic, 'sources': sources}

    service.client_factory = Client
    service.search = search
    result = pipeline.schedule(case, services=service, background=False)
    assert result['status'] == 'ready'
    assert len([name for name, _ in calls if name == 'linkup']) == 2
    assert [source['id'] for source in results[0]['sources']] == ['web-1']
    assert [source['id'] for source in results[1]['sources']] == ['web-1', 'web-2']
    assert results[2]['cached'] is True
    assert results[2]['sources'] == results[1]['sources']
    assert [source['id'] for source in result['search']['sources']] == ['web-1', 'web-2']
    assert [call['cached'] for call in result['tool_calls'][-3:]] == [False, False, True]


def test_native_resume_preserves_trace_and_marks_reused_provider_evidence(case, isolated):
    calls = []
    service = services(calls)
    service.render = lambda *_: (_ for _ in ()).throw(RuntimeError('interrupted render'))
    failed = pipeline.schedule(case, services=service, background=False)
    assert failed['status'] == 'failed'
    resumed = services(calls)
    def forbidden(*_):
        raise AssertionError('Resuming must not repeat provider calls')
    resumed.transcribe = resumed.search = forbidden
    result = pipeline.resume_failed(failed['id'], services=resumed, background=False)
    assert result['status'] == 'ready'
    assert len(result['tool_calls']) == 6
    assert [call['cached'] for call in result['tool_calls'][-3:]] == [False, True, True]


def test_native_repair_has_its_own_record_and_session(case, isolated):
    captured = {}
    class Client:
        def start_session(self, **kwargs):
            tool = kwargs['tools'][0]
            captured.update(json.loads(tool()))
            return SimpleNamespace(id='repair-session')
    case = pipeline.NativeCase.model_validate(case)
    job = {'id': 'b' * 12, 'events': [], 'tool_calls': []}
    memo = {'transcription': {'text': 'Pourquoi perd-il un point ?', 'utterances': []},
            'search': {'provider': 'Linkup', 'query': 'Pythagore', 'sources': EXTERNAL}}
    _, was_read = pipeline._repair_session(Client(), job, case, memo, answer(), ValueError('missing quote'))
    assert was_read()
    assert captured['validation_error'] == 'missing quote'
    assert len(job['tool_calls']) == 1
    assert job['tool_calls'][0]['name'] == 'read_native_repair_context'
    assert job['tool_calls'][0]['session_id'] == 'repair-session'
    assert job['tool_calls'][0]['cached'] is True

