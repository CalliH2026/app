"""Teacher dictation: real provider boundary, deterministic parsing, no API spend."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from . import grading_voice


@pytest.mark.parametrize(('text', 'score', 'maximum'), [
    ('Note Alex pour le devoir et mets lui 12/20', 12, 20),
    ('Mets-lui douze sur vingt.', 12, 20),
    ('Mets-lui zéro sur vingt.', 0, 20),
    ('Note de 12,5 sur 20.', 12.5, 20),
    ('Mets-lui douze virgule cinq sur vingt.', 12.5, 20),
    ('Note Alex dix-huit sur vingt.', 18, 20),
    ('Mets-lui quatre-vingts sur cent.', 80, 100),
])
def test_french_marks(text, score, maximum):
    command = grading_voice.parse_command(text)
    assert command['score'] == score
    assert command['maximum'] == maximum


def test_explicit_targets_and_appreciation_are_preserved():
    result = grading_voice.parse_command('Note Léa Durand pour le devoir de géométrie et mets lui 12/20. Ajoute comme appréciation : Calcul juste, explique le raisonnement.')
    assert result == {
        'score': 12, 'maximum': 20, 'student_name': 'Léa Durand',
        'evaluation_title': 'devoir de géométrie',
        'appreciation': 'Calcul juste, explique le raisonnement.',
    }
    assert grading_voice.parse_command('Mets 12/20 à Alex Martin pour le devoir.')['student_name'] == 'Alex Martin'
    assert grading_voice.parse_command('Mets 12/20 pour Alex Martin.')['student_name'] == 'Alex Martin'
    assert grading_voice.parse_command('Mets 12/20 pour le devoir de géométrie.')['evaluation_title'] == 'devoir de géométrie'
    assert grading_voice.parse_command('Léa Durand, mets-lui 12/20.')['student_name'] == 'Léa Durand'
    focused = grading_voice.parse_command('Mets-lui douze sur vingt, appréciation : Viser 15 sur 20 au prochain devoir.')
    assert focused['appreciation'] == 'Viser 15 sur 20 au prochain devoir.'
    assert focused['student_name'] is None
    assert focused['evaluation_title'] is None


@pytest.mark.parametrize('text', [
    '', 'Bravo, bon travail.', 'Mets-lui 12.', 'Mets 12/20 ou 14/20.',
    'Mets-lui -1/20.', 'Mets-lui moins un sur vingt.', 'Mets-lui 21/20.',
    'Mets-lui 0/0.', 'Mets-lui 12/-20.', 'Mets 1/' + '9' * 400,
    'Mets-lui douze virgule sur vingt.', 'a' * 10_001,
])
def test_ambiguous_missing_and_invalid_marks_are_rejected(text):
    with pytest.raises(ValueError):
        grading_voice.parse_command(text)


def client():
    app = FastAPI()
    grading_voice.install_routes(app)
    return TestClient(app)


def test_upload_uses_gladia_and_removes_temporary_audio(monkeypatch):
    paths = []

    def transcribe(path):
        paths.append(path)
        assert path.suffix == '.webm'
        assert path.read_bytes() == b'example audio bytes'
        return {'provider': 'Gladia', 'job_id': 'gladia-job', 'text': 'Note Alex pour le devoir et mets lui 12/20', 'utterances': []}

    monkeypatch.setattr(grading_voice, 'transcribe', transcribe)
    response = client().post('/api/workspace/grading/transcribe', files={'audio': ('../../teacher.webm', b'example audio bytes', 'audio/webm')})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['provider'] == 'Gladia'
    assert response.json()['command']['score'] == 12
    assert response.json()['command']['student_name'] == 'Alex'
    assert response.json()['transcription']['job_id'] == 'gladia-job'
    assert paths and all(not path.exists() and not path.parent.exists() for path in paths)


@pytest.mark.parametrize(('filename', 'content', 'mime', 'status'), [
    ('audio.exe', b'data', 'audio/wav', 415),
    ('audio.webm', b'data', 'text/plain', 415),
    ('audio.wav', b'', 'audio/wav', 400),
    ('audio.wav', b'x' * 21, 'audio/wav', 413),
])
def test_invalid_upload_never_calls_gladia(monkeypatch, filename, content, mime, status):
    monkeypatch.setattr(grading_voice, 'MAX_AUDIO_BYTES', 20)
    calls = []
    monkeypatch.setattr(grading_voice, 'transcribe', lambda path: calls.append(path))
    response = client().post('/api/workspace/grading/transcribe', files={'audio': (filename, content, mime)})
    assert response.status_code == status
    assert calls == []


def test_unknown_command_returns_transcript_for_manual_correction(monkeypatch):
    transcription = {'provider': 'Gladia', 'text': 'douze ou quatorze, je ne sais pas', 'utterances': []}
    monkeypatch.setattr(grading_voice, 'transcribe', lambda path: transcription)
    response = client().post('/api/workspace/grading/transcribe', files={'audio': ('audio.mp4', b'data', 'video/mp4')})
    assert response.status_code == 422
    assert response.json()['detail']['transcription'] == transcription
    assert 'une seule note' in response.json()['detail']['message']


@pytest.mark.parametrize(('error', 'status'), [
    (RuntimeError('Clé manquante : GLADIA_API_KEY'), 503),
    (RuntimeError('provider refused secret-api-key'), 502),
    (httpx.ConnectError('private endpoint'), 502),
    (TimeoutError('private endpoint'), 502),
])
def test_provider_failures_do_not_leak_secrets_and_cleanup(monkeypatch, error, status):
    paths = []

    def failure(path):
        paths.append(path)
        raise error

    monkeypatch.setattr(grading_voice, 'transcribe', failure)
    response = client().post('/api/workspace/grading/transcribe', files={'audio': ('audio.ogg', b'data', 'audio/ogg')})
    assert response.status_code == status
    assert 'secret-api-key' not in response.text
    assert 'private endpoint' not in response.text
    assert paths and not paths[0].exists()
