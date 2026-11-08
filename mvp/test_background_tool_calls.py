"""Background call journal survives observation writes and resets per run."""
import json
from types import SimpleNamespace

import pytest

from . import background_pronote as background
from .test_background_pronote import fake_h, isolated, ready


def test_background_trace_merges_with_observations_and_is_per_run(isolated, monkeypatch):
    ready()
    fake_h(monkeypatch)
    first = background.schedule(trigger='document_open')
    isolated.flush()
    result = background.status()
    assert [call['name'] for call in result['tool_calls']] == ['list_pronote_routes', 'read_pronote_view']
    assert all(call['status'] == 'succeeded' and call['session_id'] == 'test-session-never-sent'
               for call in result['tool_calls'])
    assert set(result['snapshots']) == {'home'}
    assert result['actions'] and result['report']
    archived = json.loads((isolated.folder / 'runs' / first['run_id'] / 'state.json').read_text())
    assert archived['tool_calls'] == result['tool_calls']
    manual = background.schedule(trigger='manual')
    assert manual['tool_calls'] == []
    isolated.flush()
    assert len(background.status()['tool_calls']) == 2
    assert manual['run_id'] != first['run_id']


def test_rejected_late_call_is_recorded_without_reopening_stopped_run(isolated, monkeypatch):
    ready()
    def wait(session, request):
        background.stop()
        tool = next(tool for tool in request['tools'] if tool.__name__ == 'read_pronote_view')
        with pytest.raises(ValueError, match='arrêtée'):
            tool('home')
        return SimpleNamespace(answer={'summary': 'Late', 'facts': [], 'unknowns': [], 'next_steps': []})
    fake_h(monkeypatch, wait)
    background.schedule()
    isolated.flush()
    result = background.status()
    assert result['state'] == 'stopped'
    assert not result['snapshots'] and result['report'] is None
    assert len(result['tool_calls']) == 1
    assert result['tool_calls'][0]['status'] == 'failed'

