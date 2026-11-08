"""Gladia live speech-to-text client (official SDK `gladiaio-sdk`), French, roster as custom vocabulary.

`final_utterances()` is the only thing the rest of the pipeline needs: an async generator of
final utterances (text, start, end, confidence) for a stream of 16-bit PCM audio chunks.

The API key is read from GLADIA_API_KEY at runtime and handed to the SDK only; it is never
printed or logged.

    python -m voice.gladia_live --file sample.wav            # streams a WAV at real-time pace
    python -m voice.gladia_live --mic                        # microphone (needs `sounddevice`)
    python -m voice.gladia_live --file a.wav --no-vocab      # A/B arm without the custom vocabulary
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import wave
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from voice.roster import DEFAULT_ROSTER, Student, load_roster, vocabulary_terms

SUPPORTED_SAMPLE_RATES = (8000, 16000, 32000, 44100, 48000)
SUPPORTED_BIT_DEPTHS = (8, 16, 24, 32)

# Dictation sits between "voice agent" (0.05-0.1 s) and "meeting recorder" (0.3-0.5 s) in Gladia's
# recommended parameters: a teacher pauses to think, so we keep the meeting value to avoid cutting
# a comment in two, and cap utterances at 15 s as both profiles recommend.
DEFAULT_ENDPOINTING = 0.5
DEFAULT_MAX_WITHOUT_ENDPOINTING = 15.0
# Gladia suggests 0.4-0.6; moderate to avoid replacing ordinary words with names.
DEFAULT_VOCAB_INTENSITY = 0.5


@dataclass(frozen=True)
class Utterance:
    text: str
    start: float
    end: float
    confidence: float


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int = 16000
    bit_depth: int = 16
    channels: int = 1


def custom_vocabulary_config(students: list[Student], intensity: float = DEFAULT_VOCAB_INTENSITY) -> dict[str, Any]:
    return {"vocabulary": vocabulary_terms(students), "default_intensity": intensity}


def build_init_request(
    audio: AudioFormat,
    students: list[Student] | None = None,
    *,
    endpointing: float = DEFAULT_ENDPOINTING,
    max_without_endpointing: float = DEFAULT_MAX_WITHOUT_ENDPOINTING,
    vocab_intensity: float = DEFAULT_VOCAB_INTENSITY,
) -> dict[str, Any]:
    """Body of POST /v2/live. `students=None` (or empty) disables the custom vocabulary (A/B baseline arm)."""
    if audio.sample_rate not in SUPPORTED_SAMPLE_RATES:
        raise ValueError(f"sample rate {audio.sample_rate} not supported by Gladia live: {SUPPORTED_SAMPLE_RATES}")
    if audio.bit_depth not in SUPPORTED_BIT_DEPTHS:
        raise ValueError(f"bit depth {audio.bit_depth} not supported by Gladia live: {SUPPORTED_BIT_DEPTHS}")
    request: dict[str, Any] = {
        "model": "solaria-1",
        "encoding": "wav/pcm",
        "sample_rate": audio.sample_rate,
        "bit_depth": audio.bit_depth,
        "channels": audio.channels,
        "endpointing": endpointing,
        "maximum_duration_without_endpointing": max_without_endpointing,
        "language_config": {"languages": ["fr"], "code_switching": False},
        "messages_config": {"receive_partial_transcripts": False, "receive_final_transcripts": True},
    }
    if students:
        request["realtime_processing"] = {
            "custom_vocabulary": True,
            "custom_vocabulary_config": custom_vocabulary_config(students, vocab_intensity),
        }
    return request


def _default_session_factory(init_request: dict[str, Any]) -> Any:
    api_key = os.environ.get("GLADIA_API_KEY")
    if not api_key:
        raise RuntimeError("GLADIA_API_KEY is not set")
    from gladiaio_sdk import GladiaClient

    return GladiaClient(api_key=api_key).live_v2_async().start_session(init_request)


def _final_utterance(message: Any) -> Utterance | None:
    if getattr(message, "type", None) != "transcript":
        return None
    data = getattr(message, "data", None)
    if not data or not getattr(data, "is_final", False):
        return None
    u = getattr(data, "utterance", None)
    text = (getattr(u, "text", "") or "").strip() if u else ""
    if not text:
        return None
    return Utterance(text=text, start=float(u.start), end=float(u.end), confidence=float(u.confidence))


_END = object()


async def final_utterances(
    audio_chunks: AsyncIterator[bytes],
    init_request: dict[str, Any],
    session_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> AsyncIterator[Utterance]:
    """Stream `audio_chunks` to Gladia and yield each final utterance as it arrives.

    Ends when the audio is exhausted and Gladia has closed the session. `session_factory` exists
    so tests can substitute a fake session; it must return an object with the SDK's async-session
    surface (`on`, `send_audio`, `stop_recording`, `end_session`).
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()
    errors: list[BaseException] = []
    session = (session_factory or _default_session_factory)(init_request)

    def on_message(message: Any) -> None:
        u = _final_utterance(message)
        if u is not None:
            queue.put_nowait(u)

    def on_error(err: BaseException) -> None:
        # The SDK retries the WebSocket by itself; keep the error in case the session ends abnormally.
        errors.append(err)

    def on_ended(ended: Any) -> None:
        queue.put_nowait((_END, ended))

    session.on("message", on_message)
    session.on("error", on_error)
    session.on("ended", on_ended)

    async def pump() -> None:
        try:
            async for chunk in audio_chunks:
                session.send_audio(chunk)
        finally:
            session.stop_recording()

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            item = await queue.get()
            if isinstance(item, tuple) and item and item[0] is _END:
                code = getattr(item[1], "code", 1000)
                if code != 1000 and errors:
                    raise RuntimeError(f"Gladia live session ended with code {code}") from errors[-1]
                break
            yield item
        await pump_task
    finally:
        if not pump_task.done():
            pump_task.cancel()
        if getattr(session, "status", "ended") != "ended":
            session.end_session()


def read_wav_format(path: Path) -> AudioFormat:
    with wave.open(str(path), "rb") as w:
        if w.getcomptype() != "NONE":
            raise ValueError(f"{path}: only uncompressed PCM WAV is supported")
        return AudioFormat(sample_rate=w.getframerate(), bit_depth=w.getsampwidth() * 8, channels=w.getnchannels())


async def wav_chunks(path: Path, chunk_ms: int = 100, realtime: bool = True) -> AsyncIterator[bytes]:
    """Yield raw PCM frames from a WAV file, paced at real time unless `realtime=False`."""
    loop = asyncio.get_running_loop()
    with wave.open(str(path), "rb") as w:
        frames_per_chunk = max(1, w.getframerate() * chunk_ms // 1000)
        t0 = loop.time()
        sent_seconds = 0.0
        while True:
            data = w.readframes(frames_per_chunk)
            if not data:
                return
            yield data
            sent_seconds += (len(data) // (w.getsampwidth() * w.getnchannels())) / w.getframerate()
            if realtime:
                delay = t0 + sent_seconds - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)


async def mic_chunks(audio: AudioFormat, chunk_ms: int = 100) -> AsyncIterator[bytes]:
    """Yield raw 16-bit PCM from the default microphone until cancelled (Ctrl-C)."""
    try:
        import sounddevice as sd
    except ImportError as err:  # optional dependency
        raise SystemExit("--mic needs the `sounddevice` package: pip install -e '.[mic]'") from err
    loop = asyncio.get_running_loop()
    q: asyncio.Queue[bytes] = asyncio.Queue()

    def callback(indata: Any, frames: int, time: Any, status: Any) -> None:
        loop.call_soon_threadsafe(q.put_nowait, bytes(indata))

    with sd.RawInputStream(samplerate=audio.sample_rate, channels=audio.channels, dtype="int16",
                           blocksize=audio.sample_rate * chunk_ms // 1000, callback=callback):
        while True:
            yield await q.get()


def write_transcript(path: Path, rows: list[dict[str, Any]]) -> None:
    """CSV with one row per final utterance: item_id, text, start, end, confidence (input of scripts/voice_ab.py)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["item_id", "text", "start", "end", "confidence"])
        w.writeheader()
        w.writerows(rows)


async def _run(args: argparse.Namespace) -> int:
    students = load_roster(Path(args.roster))
    vocab = None if args.no_vocab else students
    structurer = None
    if args.structure:
        from voice.structurer import RuleBasedStructurer

        structurer = RuleBasedStructurer(students)

    rows: list[dict[str, Any]] = []

    async def consume(item_id: str, chunks: AsyncIterator[bytes], audio: AudioFormat) -> None:
        request = build_init_request(audio, vocab, endpointing=args.endpointing)
        async for u in final_utterances(chunks, request):
            rows.append({"item_id": item_id, **asdict(u)})
            print(json.dumps({"item_id": item_id, **asdict(u)}, ensure_ascii=False), flush=True)
            if structurer:
                for c in structurer.structure(u.text):
                    print("  -> " + json.dumps(c.to_dict(), ensure_ascii=False), flush=True)

    try:
        if args.mic:
            audio = AudioFormat(sample_rate=args.sample_rate)
            await consume("mic", mic_chunks(audio), audio)
        else:
            for path in map(Path, args.file):
                await consume(path.stem, wav_chunks(path, realtime=not args.fast), read_wav_format(path))
    finally:
        if args.out:
            write_transcript(Path(args.out), rows)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--file", nargs="+", help="WAV file(s), PCM; one Gladia session per file, item_id = file stem")
    mode.add_argument("--mic", action="store_true", help="stream the default microphone until Ctrl-C")
    p.add_argument("--roster", default=str(DEFAULT_ROSTER), help="roster CSV (student_id, display_name, aliases)")
    p.add_argument("--no-vocab", action="store_true", help="do not send the roster as custom vocabulary (A/B arm)")
    p.add_argument("--out", help="write final utterances to this CSV (input of scripts/voice_ab.py)")
    p.add_argument("--structure", action="store_true", help="also print the structurer's candidate items")
    p.add_argument("--endpointing", type=float, default=DEFAULT_ENDPOINTING)
    p.add_argument("--sample-rate", type=int, default=16000, help="microphone sample rate (--mic only)")
    p.add_argument("--fast", action="store_true", help="--file: send as fast as possible instead of real time")
    args = p.parse_args(argv)
    if not os.environ.get("GLADIA_API_KEY"):
        print("GLADIA_API_KEY is not set in the environment.", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 0
    except RuntimeError as err:
        print(f"{err}: {err.__cause__ or ''}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
