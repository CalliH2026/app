"""Real invocation accounting, no H/provider requests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import inspect
import json
import threading

import pytest

from .tool_calls import ToolCallTracker, summarize_tool_calls


def test_one_invocation_not_activity_events_or_provider_messages():
    job = {'events': [{'stage': 'gladia'}, {'stage': 'gladia'}, {'stage': 'ready'}]}
    saved = []
    tracker = ToolCallTracker(job, lambda: saved.append(deepcopy(job)), threading.RLock())

    @tracker.tool
    def transcribe_audio() -> str:
        """Transcrire le vocal."""
        return json.dumps({'provider': 'Gladia', 'text': 'Bonjour'})

    assert summarize_tool_calls(job)['total'] == 0
    assert json.loads(transcribe_audio())['text'] == 'Bonjour'
    assert len(saved) == 2
    assert saved[0]['tool_calls'][0]['status'] == 'running'
    call = job['tool_calls'][0]
    assert call['status'] == 'succeeded' and call['duration_ms'] >= 0
    assert call['started_at'] and call['ended_at']
    assert summarize_tool_calls(job) == {
        'total': 1, 'succeeded': 1, 'failed': 0, 'running': 0,
        'cached': 0, 'distinct_tools': 1, 'tool_names': ['transcribe_audio'],
        'custom_total': 1, 'navigation_total': 0, 'coverage': 'custom',
    }


def test_preserves_sdk_signature_and_session_id_for_early_callbacks():
    job = {}
    tracker = ToolCallTracker(job, lambda: None, threading.RLock())

    def search_resources(topic: str, purpose: str = 'reference') -> str:
        """Chercher une référence publique."""
        return topic

    wrapped = tracker.tool(search_resources)
    assert inspect.signature(wrapped) == inspect.signature(search_resources)
    assert wrapped.__annotations__ == search_resources.__annotations__
    assert wrapped.__name__ == search_resources.__name__
    assert wrapped.__doc__ == search_resources.__doc__
    wrapped('Pythagore')
    tracker.set_session_id('session-h-1')
    wrapped('Triangles', purpose='exercise')
    assert all(call['session_id'] == 'session-h-1' for call in job['tool_calls'])
    assert job['tool_calls'][0]['arguments']['purpose'] == 'reference'


def test_cache_is_counted_as_invocation_and_separated_from_provider_work():
    job = {}
    tracker = ToolCallTracker(job, lambda: None, threading.RLock())
    memo = {}
    provider_calls = []

    @tracker.tool
    def search_resources(topic: str) -> str:
        if topic in memo:
            tracker.mark_cached()
        else:
            provider_calls.append(topic)
            memo[topic] = topic
        return memo[topic]

    search_resources('Pythagore')
    search_resources('Pythagore')
    search_resources('Exercice')
    summary = summarize_tool_calls(job)
    assert summary['total'] == 3 and summary['cached'] == 1
    assert summary['distinct_tools'] == 1 and len(provider_calls) == 2


def test_failure_recorded_once_and_original_exception_preserved():
    job = {}
    tracker = ToolCallTracker(job, lambda: None, threading.RLock())
    error = ValueError('secret data that must not enter trace')

    @tracker.tool
    def validate_dossier() -> str:
        raise error

    with pytest.raises(ValueError) as caught:
        validate_dossier()
    assert caught.value is error
    assert summarize_tool_calls(job)['failed'] == 1
    assert 'secret data' not in job['tool_calls'][0]['result_summary']


def test_credentials_redacted_and_large_results_bounded(monkeypatch):
    monkeypatch.setenv('H_COMPANY_API_KEY', 'very-private-api-value')
    job = {}
    tracker = ToolCallTracker(job, lambda: None, threading.RLock())

    @tracker.tool
    def inspect_result(api_key: str, topic: str) -> str:
        return json.dumps({'authorization': 'Bearer abcdefgh', 'text': topic, 'data': 'x' * 1000})

    inspect_result('very-private-api-value', 'token=another-secret very-private-api-value')
    serialized = json.dumps(job)
    assert 'very-private-api-value' not in serialized
    assert 'another-secret' not in serialized
    assert 'abcdefgh' not in serialized
    assert len(job['tool_calls'][0]['result_summary']) <= 600


def test_parallel_calls_do_not_share_cache_markers():
    job = {}
    tracker = ToolCallTracker(job, lambda: None, threading.RLock())
    barrier = threading.Barrier(2)

    @tracker.tool
    def read_document(document_id: str) -> str:
        barrier.wait(timeout=3)
        if document_id == 'cached':
            tracker.mark_cached()
        return document_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(read_document, ['cached', 'fresh'])) == ['cached', 'fresh']
    cached = {call['arguments']['document_id']: call['cached'] for call in job['tool_calls']}
    assert cached == {'cached': True, 'fresh': False}
    assert summarize_tool_calls(job)['succeeded'] == 2
    assert len({call['id'] for call in job['tool_calls']}) == 2


def test_reloaded_job_keeps_counts_and_other_trackers_session_ids():
    job = {'tool_calls': [{'id': 'old', 'name': 'read_document', 'kind': 'custom',
                          'status': 'succeeded', 'cached': False, 'session_id': 'old-session'}]}
    job = json.loads(json.dumps(job))
    tracker = ToolCallTracker(job, lambda: None, threading.RLock())

    @tracker.tool
    def validate_dossier() -> str:
        return 'OK'

    validate_dossier()
    tracker.set_session_id('new-session')
    assert job['tool_calls'][0]['session_id'] == 'old-session'
    assert job['tool_calls'][1]['session_id'] == 'new-session'
    assert summarize_tool_calls(job)['total'] == 2


def test_persistence_failure_does_not_repeat_or_hide_successful_action():
    job = {}

    def persist():
        raise OSError('disk full')

    tracker = ToolCallTracker(job, persist, threading.RLock())
    actions = []

    @tracker.tool
    def render_capsule() -> str:
        actions.append('rendered')
        return 'capsule.mp4'

    assert render_capsule() == 'capsule.mp4'
    assert actions == ['rendered']
    assert job['tool_calls'][0]['status'] == 'succeeded'
    assert job['tool_call_tracking_error']


def test_unrenderable_preview_cannot_turn_success_into_failure():
    job = {}
    tracker = ToolCallTracker(job, lambda: None, threading.RLock())

    class Unpreviewable:
        def model_dump(self, **kwargs):
            raise ValueError('preview not supported')

    result = Unpreviewable()

    @tracker.tool
    def read_result():
        return result

    assert read_result() is result
    assert job['tool_calls'][0]['status'] == 'succeeded'
    assert 'aperçu indisponible' in job['tool_calls'][0]['result_summary']
