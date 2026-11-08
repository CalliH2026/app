import asyncio
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from voice import gladia_live
from voice.gladia_live import (
    AudioFormat,
    Utterance,
    build_init_request,
    final_utterances,
    read_wav_format,
    wav_chunks,
)
from voice.roster import load_roster, vocabulary_terms

ROSTER = Path(__file__).parent / "fixtures" / "roster.csv"


def transcript(text: str, start: float, end: float, conf: float, is_final: bool = True):
    u = SimpleNamespace(text=text, start=start, end=end, confidence=conf)
    return SimpleNamespace(type="transcript", data=SimpleNamespace(id="u", is_final=is_final, utterance=u))


class FakeSession:
    """Mimics the SDK async session surface: events are emitted from the event loop, not inline."""

    def __init__(self, script, end_code=1000, error=None):
        self.script = script
        self.end_code = end_code
        self.error = error
        self.handlers = {}
        self.audio = b""
        self.status = "started"
        self.stopped = False

    def on(self, event, cb):
        self.handlers[event] = cb

    def send_audio(self, chunk):
        self.audio += chunk
        if len(self.audio) == len(chunk):  # first chunk: emit the scripted messages
            loop = asyncio.get_running_loop()
            for msg in self.script:
                loop.call_soon(self.handlers["message"], msg)

    def stop_recording(self):
        self.stopped = True
        loop = asyncio.get_running_loop()
        if self.error:
            loop.call_soon(self.handlers["error"], self.error)
        loop.call_soon(self._end)

    def _end(self):
        self.status = "ended"
        self.handlers["ended"](SimpleNamespace(code=self.end_code, reason=None))

    def end_session(self):
        self.status = "ended"


async def chunks(n=3):
    for _ in range(n):
        yield b"\x00\x00" * 160
        await asyncio.sleep(0)


async def collect(agen):
    return [x async for x in agen]


def test_init_request_french_with_roster_vocabulary():
    students = load_roster(ROSTER)
    req = build_init_request(AudioFormat(), students)
    assert req["language_config"] == {"languages": ["fr"], "code_switching": False}
    assert req["model"] == "solaria-1" and req["encoding"] == "wav/pcm"
    assert req["sample_rate"] == 16000 and req["bit_depth"] == 16 and req["channels"] == 1
    rp = req["realtime_processing"]
    assert rp["custom_vocabulary"] is True
    vocab = rp["custom_vocabulary_config"]["vocabulary"]
    assert {"Léa", "Martin", "Bernard", "Maël", "Maëlle", "Max", "Coco", "Inès"} <= set(vocab)
    assert vocab.count("Léa") == 1  # deduplicated
    assert 0.4 <= rp["custom_vocabulary_config"]["default_intensity"] <= 0.6
    assert req["messages_config"]["receive_final_transcripts"] is True


def test_init_request_without_vocabulary_for_ab_baseline():
    req = build_init_request(AudioFormat(), None)
    assert "realtime_processing" not in req


def test_init_request_rejects_unsupported_audio():
    with pytest.raises(ValueError):
        build_init_request(AudioFormat(sample_rate=22050))


def test_init_request_is_accepted_by_the_sdk_types():
    sdk = pytest.importorskip("gladiaio_sdk")
    req = build_init_request(AudioFormat(), load_roster(ROSTER))
    parsed = sdk.LiveV2InitRequest.from_dict(req)
    assert parsed.language_config.languages == ["fr"]
    assert parsed.realtime_processing.custom_vocabulary_config.vocabulary[0] == "Léa"


def test_vocabulary_terms_cover_names_and_aliases():
    terms = vocabulary_terms(load_roster(ROSTER))
    assert "Maximilien" in terms and "Max" in terms and "Lefèvre" in terms


def test_final_utterances_yields_only_finals():
    session = FakeSession([
        transcript("Léa", 0.1, 0.4, 0.5, is_final=False),
        transcript("Léa Martin, participe bien.", 0.1, 2.0, 0.93),
        SimpleNamespace(type="speech_end", data=None),
        transcript("  ", 2.0, 2.1, 0.9),
        transcript("Stop.", 3.0, 3.4, 0.99),
    ])
    out = asyncio.run(collect(final_utterances(chunks(), {"x": 1}, session_factory=lambda req: session)))
    assert out == [Utterance("Léa Martin, participe bien.", 0.1, 2.0, 0.93), Utterance("Stop.", 3.0, 3.4, 0.99)]
    assert session.stopped and len(session.audio) == 3 * 320


def test_final_utterances_passes_the_init_request():
    seen = {}

    def factory(req):
        seen.update(req)
        return FakeSession([])

    req = build_init_request(AudioFormat(), load_roster(ROSTER))
    asyncio.run(collect(final_utterances(chunks(1), req, session_factory=factory)))
    assert seen == req


def test_final_utterances_raises_on_abnormal_end():
    session = FakeSession([], end_code=1006, error=ConnectionError("boom"))
    with pytest.raises(RuntimeError):
        asyncio.run(collect(final_utterances(chunks(), {}, session_factory=lambda req: session)))


def test_default_factory_requires_key_and_main_does_not_leak(monkeypatch, capsys):
    monkeypatch.delenv("GLADIA_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        gladia_live._default_session_factory({})
    assert gladia_live.main(["--file", "nope.wav"]) == 2
    assert "GLADIA_API_KEY is not set" in capsys.readouterr().err


def write_wav(path: Path, seconds: float, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))


def test_wav_chunks_reads_all_frames_and_format(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, 1.0)
    assert read_wav_format(p) == AudioFormat(16000, 16, 1)
    data = asyncio.run(collect(wav_chunks(p, chunk_ms=100, realtime=False)))
    assert len(data) == 10 and sum(map(len, data)) == 32000


def test_wav_chunks_paces_at_real_time(tmp_path):
    p = tmp_path / "b.wav"
    write_wav(p, 0.3)

    async def timed():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await collect(wav_chunks(p, chunk_ms=100))
        return loop.time() - t0

    assert asyncio.run(timed()) >= 0.28


def test_cli_file_mode_writes_transcript(tmp_path, monkeypatch):
    p = tmp_path / "d01.wav"
    write_wav(p, 0.2)
    out = tmp_path / "t.csv"
    session = FakeSession([transcript("Max, travail irrégulier.", 0.0, 1.5, 0.9)])
    requests = []

    def factory(req):
        requests.append(req)
        return session

    monkeypatch.setenv("GLADIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(gladia_live, "_default_session_factory", factory)
    rc = gladia_live.main(["--file", str(p), "--fast", "--no-vocab", "--roster", str(ROSTER), "--out", str(out)])
    assert rc == 0
    assert "realtime_processing" not in requests[0]
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "item_id,text,start,end,confidence"
    assert lines[1].startswith("d01,\"Max, travail irrégulier.\"")
