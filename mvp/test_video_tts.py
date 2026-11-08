"""Optional ElevenLabs voice: network mocked, explicit failures, local voice unchanged by default."""
import pytest

from mvp import video


class Response:
    def __init__(self, status, content=b'ID3fake'):
        self.status_code, self.content = status, content


def test_elevenlabs_request_and_conversion(tmp_path, monkeypatch):
    import httpx
    sent, ran = {}, []
    monkeypatch.setattr(httpx, 'post', lambda url, **kw: sent.update(url=url, **kw) or Response(200))
    monkeypatch.setattr(video, 'run', lambda args: ran.append(args))
    video.elevenlabs_speech('Bonjour.', tmp_path / 'out.wav', env={'ELEVENLABS_API_KEY': 'k'})
    assert sent['url'] == 'https://api.elevenlabs.io/v1/text-to-speech/Xb7hH8MSUJpSbSDYk0k2?output_format=mp3_44100_128'
    assert sent['headers'] == {'xi-api-key': 'k'}
    assert sent['json'] == {'text': 'Bonjour.', 'model_id': 'eleven_multilingual_v2', 'language_code': 'fr'}
    assert ran[0][:4] == ['ffmpeg', '-y', '-i', str(tmp_path / 'out.mp3')] and not (tmp_path / 'out.mp3').exists()


def test_elevenlabs_voice_and_model_from_env(tmp_path, monkeypatch):
    import httpx
    sent = {}
    monkeypatch.setattr(httpx, 'post', lambda url, **kw: sent.update(url=url, **kw) or Response(200))
    monkeypatch.setattr(video, 'run', lambda args: None)
    video.elevenlabs_speech('x', tmp_path / 'o.wav', env={'ELEVENLABS_API_KEY': 'k', 'ELEVENLABS_VOICE_ID': 'v1',
                                                          'ELEVENLABS_MODEL_ID': 'eleven_flash_v2_5'})
    assert '/text-to-speech/v1?' in sent['url'] and sent['json']['model_id'] == 'eleven_flash_v2_5'


@pytest.mark.parametrize('env,response,message', [
    ({}, None, 'ELEVENLABS_API_KEY est absent'),
    ({'ELEVENLABS_API_KEY': 'k'}, Response(401), 'HTTP 401'),
    ({'ELEVENLABS_API_KEY': 'k'}, Response(200, b''), 'HTTP 200'),
])
def test_elevenlabs_failures_are_visible(tmp_path, monkeypatch, env, response, message):
    import httpx
    monkeypatch.setattr(httpx, 'post', lambda url, **kw: response)
    with pytest.raises(RuntimeError, match=message):
        video.elevenlabs_speech('x', tmp_path / 'o.wav', env=env)


def test_selected_elevenlabs_never_falls_back_to_local(tmp_path, monkeypatch):
    monkeypatch.setenv('TTS_PROVIDER', 'elevenlabs')
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    monkeypatch.setattr(video, 'run', lambda args: pytest.fail('local voice used'))
    with pytest.raises(RuntimeError, match='ELEVENLABS_API_KEY'):
        video.speech('x', tmp_path / 'o.wav')


def test_unknown_provider_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv('TTS_PROVIDER', 'gradium')
    with pytest.raises(RuntimeError, match='TTS_PROVIDER inconnu'):
        video.speech('x', tmp_path / 'o.wav')
