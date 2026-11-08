import hashlib
import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / 'fixtures'
PROVENANCE = json.loads((FIXTURES / 'parent-voices-elevenlabs.json').read_text())
AUDIO = json.loads((FIXTURES / 'alex.json').read_text())['audio']


def test_fixture_voices_match_their_provenance():
    assert {f['scenario'] for f in PROVENANCE['files']} == set(AUDIO) == {'points', 'progress'}
    assert PROVENANCE['voice_id'] == 'Xb7hH8MSUJpSbSDYk0k2' and PROVENANCE['model_id'] == 'eleven_multilingual_v2'
    for entry in PROVENANCE['files']:
        path = FIXTURES / entry['file']
        assert AUDIO[entry['scenario']] == {'file': entry['file'], 'text': entry['text']}
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']
        with wave.open(str(path)) as audio:
            assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (24000, 1, 2)
            assert audio.getnframes() / 24000 == pytest.approx(entry['duration_seconds'], abs=0.01)


def test_fixture_voices_are_committed_not_ignored():
    if not shutil.which('git') or not (FIXTURES.parents[1] / '.git').exists():
        pytest.skip('not a git checkout')
    names = [str(FIXTURES / f['file']) for f in PROVENANCE['files']]
    ignored = subprocess.run(['git', 'check-ignore', '--no-index', *names], check=False, cwd=FIXTURES, capture_output=True, text=True)
    assert ignored.stdout == ''
    assert subprocess.run(['git', 'check-ignore', '--no-index', str(FIXTURES / 'other.wav')], check=False, cwd=FIXTURES).returncode == 0


def test_audio_routes_serve_the_committed_voices():
    from .app import app
    client = TestClient(app)
    for scenario, item in AUDIO.items():
        response = client.get('/audio/' + scenario)
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('audio/')
        assert response.content == (FIXTURES / item['file']).read_bytes() and response.content[:4] == b'RIFF'
