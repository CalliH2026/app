"""Public replay keeps real call evidence without provider/account metadata."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from . import generate_workspace_demo as film


def source_job():
    return {
        'id': 'abc123abc123', 'mode': 'live', 'scenario': 'points', 'status': 'ready',
        'created_at': '2026-11-07T15:00:00+00:00', 'duration': 63,
        'session_id': 'private-h-session', 'events': [{'time': '2026-11-07T15:00:00+00:00', 'stage': 'h', 'text': 'H démarre.'}],
        'transcription': {'provider': 'Gladia', 'job_id': 'private-gladia-job', 'text': 'Pourquoi ces points ?'},
        'search': {'provider': 'Linkup', 'query': 'Pythagore', 'sources': []},
        'dossier': {'question': 'Pourquoi ces points ?', 'intent': 'points', 'summary': 'Explication sourcée.',
                    'evidence': [], 'unknowns': [], 'scenes': [],
                    'sources': [{'id': 'copie', 'title': 'Copie', 'text': 'Texte fictif.'}]},
        'tool_calls': [
            {'id': 'call-one', 'name': 'transcribe_audio', 'kind': 'custom', 'status': 'succeeded',
             'started_at': '2026-11-07T15:00:04+00:00', 'ended_at': '2026-11-07T15:00:12+00:00',
             'duration_ms': 8000, 'arguments': {}, 'result_summary': 'Gladia private-gladia-job',
             'cached': False, 'session_id': 'private-h-session'},
            {'id': 'call-two', 'name': 'validate_dossier', 'kind': 'custom', 'status': 'failed',
             'started_at': '2026-11-07T15:00:16+00:00', 'ended_at': '2026-11-07T15:00:24+00:00',
             'duration_ms': 8000, 'arguments': {'validated_dossier_id': 'private-dossier-id', 'quote_id': 'q001'},
             'result_summary': 'Dossier private-dossier-id', 'cached': False, 'session_id': 'private-h-session'},
        ],
    }


def test_public_call_trace_preserves_count_and_errors_without_private_ids():
    original = source_job()
    cleaned = film.clean_job(original)
    serialized = json.dumps(cleaned)
    assert cleaned['tool_call_summary']['total'] == 2
    assert cleaned['tool_call_summary']['failed'] == 1
    assert cleaned['tool_call_summary']['succeeded'] == 1
    assert cleaned['id'] == film.FILM_JOB
    assert 'quote_id' in serialized and 'q001' in serialized
    assert all(value not in serialized for value in
               ('private-h-session', 'private-gladia-job', 'private-dossier-id', 'abc123abc123'))
    assert 'session_id' not in serialized and 'job_id' not in serialized
    assert original['tool_calls'][0]['session_id'] == 'private-h-session'


def test_old_job_does_not_acquire_an_invented_zero_call_measurement():
    original = source_job()
    del original['tool_calls']
    cleaned = film.clean_job(original)
    assert 'tool_calls' not in cleaned
    assert 'tool_call_summary' not in cleaned


def test_replay_clock_keeps_starts_results_and_failures_in_recorded_order():
    job = film.clean_job(source_job())
    assert film.replay_tool_calls(job, 0) == []
    active = film.replay_tool_calls(job, 6)
    assert len(active) == 1
    assert active[0]['status'] == 'running'
    assert active[0]['result_summary'] == ''
    assert active[0]['ended_at'] is None and active[0]['duration_ms'] is None
    intermediate = film.replay_tool_calls(job, 18)
    assert [call['status'] for call in intermediate] == ['succeeded', 'running']
    final = film.replay_tool_calls(job, 24)
    assert [call['status'] for call in final] == ['succeeded', 'failed']
    assert job['tool_calls'][1]['status'] == 'failed'


def write_replay(tmp_path, original):
    (tmp_path / 'snapshot-job.json').write_text(json.dumps(original))
    (tmp_path / 'snapshot-workspace.json').write_text(json.dumps({'agent': {}}))
    static = tmp_path / 'snapshot-static'
    static.mkdir()
    (static / 'workspace.html').write_text('<html><body>Démonstration partagée · données fictives · préparations réelles en mode connecté.</body></html>')
    (tmp_path / 'snapshot-media').mkdir()


def test_working_replay_summary_uses_only_visible_calls(monkeypatch, tmp_path):
    write_replay(tmp_path, film.clean_job(source_job()))
    replay = film.Replay(tmp_path)
    monkeypatch.setattr(film.time, 'monotonic', lambda: 100)
    replay.start()
    monkeypatch.setattr(film.time, 'monotonic', lambda: 106)
    visible = replay.job()
    assert visible['tool_call_summary']['total'] == 1
    assert visible['tool_call_summary']['running'] == 1
    assert 'video' not in visible
    replay.phase = 'ready'
    final = replay.job()
    assert final['tool_call_summary']['total'] == 2
    assert final['tool_call_summary']['failed'] == 1
    assert final['video'] == '/outputs/workspace-film/capsule.mp4'


@pytest.mark.parametrize('path,selector', [
    ('/film/tools', '.tool-call-panel'),
    ('/film/errors', '.tool-call-item.failed'),
])
def test_film_checkpoints_show_complete_recorded_trace_without_server_or_network(monkeypatch, tmp_path, path, selector):
    write_replay(tmp_path, film.clean_job(source_job()))
    handlers = []
    class Server:
        server_port = 8766
        def __init__(self, address, handler):
            handlers.append(handler)
        def serve_forever(self):
            pass
        def shutdown(self):
            pass
        def server_close(self):
            pass
    monkeypatch.setattr(film, 'ThreadingHTTPServer', Server)
    with film.snapshot_server(tmp_path):
        handler = object.__new__(handlers[0])
        handler.path = path
        handler.record = lambda: None
        captured = []
        handler.reply = lambda data, **kwargs: captured.append(data)
        handler.do_GET()
        page = captured.pop().decode()
        assert selector in page and "setPanel(true)" in page
        assert "bareme.id='film-bareme-source'" in page
        assert "firstError.id='film-first-error'" in page
        assert 'Temps condensé' in page
        handler.path = '/api/jobs/workspace-film'
        handler.do_GET()
        result = captured.pop()
        assert result['status'] == 'ready'
        assert result['tool_call_summary']['total'] == 2


def test_actual_connected_run_keeps_all_eleven_calls_without_session_ids():
    actual = film.ROOT / 'data/fbe27c818e0a/state.json'
    if not actual.exists():
        pytest.skip('Local verified connected run is not committed to the repository.')
    original = json.loads(actual.read_text())
    cleaned = film.clean_job(original)
    assert cleaned['tool_call_summary']['total'] == 11
    assert cleaned['tool_call_summary']['distinct_tools'] == 6
    assert cleaned['tool_call_summary']['failed'] == 3
    assert cleaned['tool_call_summary']['succeeded'] == 8
    assert original['session_id'] not in json.dumps(cleaned)
    assert all('session_id' not in call for call in cleaned['tool_calls'])
