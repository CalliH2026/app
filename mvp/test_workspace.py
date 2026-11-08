"""Source identity, snapshot and retained-report invariants. No provider calls."""
from copy import deepcopy
import hashlib

from . import engine, workspace


def test_marks_follow_the_copy_and_disagreement_is_visible(monkeypatch, tmp_path):
    fixture = deepcopy(engine.FIXTURE)
    copy = next(d for d in fixture['documents'] if d['id'] == 'copie')
    copy['text'] = copy['text'].replace('calcul 2/2', 'calcul 1/2').replace('3/6', '2/6')
    monkeypatch.setattr(workspace, 'FIXTURE', fixture)
    monkeypatch.setattr(workspace, 'STATE', tmp_path/'workspace.json')
    result = workspace.get_workspace()
    assessment = result['students'][0]['assessment']
    assert assessment['score'] == 2
    assert sum(c['score'] for c in assessment['criteria']) == 2
    assert assessment['consistent'] is True
    assert all(c['quote'] in copy['text'] for c in assessment['criteria'])
    assert all(d['source']['native_synced'] is False for d in result['documents'])
    copy['text'] = copy['text'].replace('2/6', '4/6')
    assert workspace.get_document('copie')['assessment']['consistent'] is False


def test_appointment_message_and_audio_snapshots_are_cache_inputs(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'DATA', tmp_path)
    monkeypatch.setattr(engine, 'JOBS', {})
    class Worker:
        def __init__(self, **kwargs): pass
        def start(self): pass
    monkeypatch.setattr(engine.threading, 'Thread', Worker)
    context = deepcopy(engine.FIXTURE)
    context['appointment']['at'] = '2026-11-07T18:00:00+01:00'
    first = engine.launch('points', 'live', 'http://localhost:8000', input_context=context)
    same = engine.launch('points', 'live', 'http://localhost:8000', input_context=context)
    assert first['id'] == same['id']
    context['appointment']['at'] = '2026-11-08T18:00:00+01:00'
    changed_meeting = engine.launch('points', 'live', 'http://localhost:8000', input_context=context)
    assert first['id'] != changed_meeting['id']
    context['messages'][0]['text'] = 'Une nouvelle consigne à prendre en compte.'
    changed_message = engine.launch('points', 'live', 'http://localhost:8000', input_context=context)
    assert changed_meeting['id'] != changed_message['id']
    frozen = engine.snapshot(first['id'])['input_context']
    assert frozen['appointment']['at'] == '2026-11-07T18:00:00+01:00'
    assert frozen['messages'][0]['text'] != context['messages'][0]['text']
    captured = tmp_path/first['id']/first['captured_audio']
    assert hashlib.sha256(captured.read_bytes()).hexdigest() == frozen['audio']['points']['content_hash']


def test_retained_workspace_report_survives_open_history_rotation(monkeypatch):
    report = {'id':'retained','workspace_origin':'new_pronote','status':'ready','mode':'live',
              'scenario':'points','created_at':'2026-11-07T15:00:00+01:00','kept':True,'events':[]}
    monkeypatch.setattr(workspace, 'JOBS', {'retained': report})
    result = workspace._agent_state({'opens': []})
    assert result['reports'][0]['id'] == 'retained'
    assert result['reports'][0]['kept'] is True
