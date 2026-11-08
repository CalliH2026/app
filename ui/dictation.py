"""Automatic dictation: one dictation turn -> guards -> live writer queue, no per-comment approval.

Operating policy chosen by the product owner for /workspace (it adapts Liqin's BR-001, see
docs/parallel-workspace.md): the teacher's own dictated words are queued for the writer as soon as a
dictation turn ends, if and only if every guard below passes. The turn boundary is explicit (the teacher
starts and ends the recording); final speech-to-text fragments are aggregated until that end, so a pause
never writes half a sentence, and a partial transcript never reaches the queue.

Guards, enforced here on the server (never trusted from the page):
- the course frozen at the start of the turn is the configured course; the selected pupil is on the roster;
- STOP is not set at the start nor at the end of the turn;
- exactly one comment naming exactly one recognized roster pupil. The selected pupil is only a consistency
  check: no recognized name (including an unknown name such as "Paul Durand"), an ambiguous name, a name
  that differs from the selected pupil, several comments or a spoken correction stop for correction;
- two separate thresholds, both conservative and NOT calibrated, so neither is a correctness guarantee:
  `NAME_MIN_CONFIDENCE` on the roster name match (voice/structurer.py: 0.95 x score for a clear match,
  at most 0.6 with a close runner-up, 0.4 when tied) and `ASR_MIN_CONFIDENCE` on the lowest Gladia
  utterance confidence of the turn. Below either, the turn stops for correction;
- the comment is a non-empty span of what was said, at most 255 characters (refused, never truncated);
- one turn_id queues at most once: the queue item_id is derived from the turn_id and an existing item with
  that id is reconciled whatever its status, so a crash between the queue and the ledger, a retry or a
  restart never writes twice;
- STOP is checked again under the queue lock at append time (agent/queue_store.py), and a STOP pressed just
  after the append drains the item, so no new pending item survives a STOP to resume later.

The typed STOP and cancel controls act at once. A spoken "stop" is only understood when its turn ends.

Queued items carry `source="automatic_dictation"`: teacher-dictated and queued automatically, not
teacher-approved. They carry no previous value, so the PRONOTE target rules make the writer refuse an
occupied cell (agent/targets/pronote.md) instead of overwriting it.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os
import re
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from agent.queue_store import QueueStore, StopRequested
from voice.gladia_live import AudioFormat, Utterance, build_init_request, final_utterances
from voice.roster import Student
from voice.structurer import RuleBasedStructurer, _marker_at, _tokens

SOURCE = "automatic_dictation"
MAX_CHARS = 255
NAME_MIN_CONFIDENCE = 0.8
ASR_MIN_CONFIDENCE = 0.7
CANCEL_REASONS = ("cancelled", "pupil_changed", "stop_pressed")
AUDIO = AudioFormat(sample_rate=16000, bit_depth=16, channels=1)
MAX_CHUNK_BYTES = 64_000
DRAIN_TIMEOUT_S = 20.0
TURN_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
RECENT = 20


@dataclass
class Turn:
    turn_id: str
    student_id: str | None
    course: str
    started_at: float = field(default_factory=time.time)
    fragments: list[Utterance] = field(default_factory=list)
    _seen: set = field(default_factory=set)

    def add(self, u: Utterance) -> bool:
        """Add one FINAL fragment; a repeated final (same span and text) is ignored."""
        key = (round(u.start, 2), round(u.end, 2), u.text.strip())
        if not u.text.strip() or key in self._seen:
            return False
        self._seen.add(key)
        self.fragments.append(u)
        return True

    @property
    def transcript(self) -> str:
        return " ".join(f.text.strip() for f in self.fragments).strip()

    @property
    def confidence(self) -> float | None:
        return min((f.confidence for f in self.fragments), default=None)


class DictationPolicy:
    """Own the turn ledger and decide whether a completed dictation may enter the queue.

    The selected pupil is a consistency check, never a substitute for a recognised name.
    Persisted turn IDs and deterministic queue IDs reconcile repeated commits after a restart.
    This policy queues work; it never performs computer actions itself.
    """

    def __init__(self, students: list[Student], course: str | None, structurer: RuleBasedStructurer,
                 store: QueueStore, state_dir: Path | None, name_min_confidence: float = NAME_MIN_CONFIDENCE,
                 asr_min_confidence: float = ASR_MIN_CONFIDENCE):
        self.name_min, self.asr_min = name_min_confidence, asr_min_confidence
        self.by_id = {s.student_id: s for s in students}
        self.course, self.structurer, self.store = course, structurer, store
        self.path = Path(state_dir) / "dictations.json" if state_dir else None
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, Any]] = {}
        if self.path and self.path.exists():
            self._records = json.loads(self.path.read_text(encoding="utf-8"))

    # ---- ledger -----------------------------------------------------------------------------------------

    def get(self, turn_id: str) -> dict[str, Any] | None:
        with self._lock:
            rec = self._records.get(turn_id)
            return dict(rec) if rec else None

    def recent(self, n: int = RECENT) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in sorted(self._records.values(), key=lambda r: r["at"])[-n:]]

    def _save(self, rec: dict[str, Any]) -> dict[str, Any]:
        self._records[rec["turn_id"]] = rec
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self._records, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        return dict(rec)

    # ---- turn lifecycle ---------------------------------------------------------------------------------

    def start(self, turn_id: str, student_id: str | None, course: str | None) -> Turn:
        """Freeze a valid context for a turn; raise ValueError before recording if it is unsafe."""
        if not TURN_ID.match(turn_id or ""):
            raise ValueError("bad_turn_id")
        if not self.course:
            raise ValueError("no_course")
        if course != self.course:
            raise ValueError("stale_context")
        if student_id is not None and student_id not in self.by_id:
            raise ValueError("unknown_pupil")
        if self.store.stop_requested():
            raise ValueError("stopped")
        return Turn(turn_id, student_id, course)

    def _record(self, turn: Turn, status: str, reason: str | None = None, **extra: Any) -> dict[str, Any]:
        rec = {"turn_id": turn.turn_id, "status": status, "reason": reason, "transcript": turn.transcript,
               "confidence": turn.confidence, "course": turn.course, "selected_student_id": turn.student_id,
               "student_id": None, "student_name": None, "text": None, "item_id": None, "source": SOURCE,
               "at": time.time()}
        rec.update(extra)
        return rec

    def cancel(self, turn: Turn, reason: str) -> dict[str, Any]:
        with self._lock:
            if turn.turn_id in self._records:
                return dict(self._records[turn.turn_id], duplicate=True)
            return self._save(self._record(turn, "cancelled", reason))

    def refuse(self, turn: Turn, reason: str) -> dict[str, Any]:
        with self._lock:
            if turn.turn_id in self._records:
                return dict(self._records[turn.turn_id], duplicate=True)
            return self._save(self._record(turn, "refused", reason))

    def commit(self, turn: Turn) -> dict[str, Any]:
        """Persist one decision and return its status; repeated turn IDs reuse the recorded result.

        A successful decision appends through QueueStore's locked STOP check. Other outcomes
        retain a reason for correction or refusal, without sending an item to the writer.
        """
        with self._lock:
            if turn.turn_id in self._records:
                return dict(self._records[turn.turn_id], duplicate=True)
            return dict(self._save(self._decide(turn)), duplicate=False)

    def _decide(self, turn: Turn) -> dict[str, Any]:
        if self.store.stop_requested():
            return self._record(turn, "refused", "stopped")
        if turn.course != self.course:
            return self._record(turn, "refused", "stale_context")
        text = turn.transcript
        if not text:
            return self._record(turn, "refused", "empty")
        asr = turn.confidence
        items = self.structurer.structure(text)  # a plain string: item confidence is the name match only
        if any(it.kind == "stop" for it in items):
            self.store.stop()
            return self._record(turn, "stopped", "spoken_stop")
        if any(it.kind != "comment" for it in items) or _has_correction(text):
            # "non, plutôt" inside a comment: the structurer would keep only the revision; the teacher checks it
            return self._record(turn, "needs_correction", "correction_command")
        if not items:
            return self._record(turn, "refused", "empty")
        if len(items) > 1:
            return self._record(turn, "needs_correction", "several_comments")
        item = items[0]
        named = [sid for sid in item.student_candidates if sid in self.by_id]
        if len(named) > 1:
            return self._record(turn, "needs_correction", "ambiguous", candidates=named)
        if not named:
            return self._record(turn, "needs_correction", "no_known_name")
        sid = named[0]
        name = self.by_id[sid].display_name
        who = {"student_id": sid, "student_name": name, "name_confidence": item.confidence}
        if turn.student_id is not None and sid != turn.student_id:
            return self._record(turn, "needs_correction", "pupil_mismatch", **who)
        if item.confidence < self.name_min:
            return self._record(turn, "needs_correction", "low_name_confidence", **who)
        if asr is None or asr < self.asr_min:
            return self._record(turn, "needs_correction", "low_asr_confidence", **who)
        comment = item.text.strip()
        if not comment:
            return self._record(turn, "refused", "empty")
        if len(comment) > MAX_CHARS:
            return self._record(turn, "needs_correction", "too_long", text=comment, length=len(comment), **who)
        item_id = "d-" + turn.turn_id
        try:
            # the turn is the only dedupe boundary: no aliasing to another turn's item with the same text
            stored = self.store.append({"item_id": item_id, "student": name, "text": comment, "course": self.course,
                                        "source": SOURCE}, dedupe=False, idempotent=True, refuse_when_stopped=True)
        except StopRequested:
            return self._record(turn, "refused", "stopped", **who)
        if stored.get("duplicate"):
            # an earlier attempt of this turn already queued it: report what is in the queue, not the replay
            sid_stored = next((s.student_id for s in self.by_id.values() if s.display_name == stored["student"]), None)
            return self._record(turn, "queued", None, student_id=sid_stored, student_name=stored["student"],
                                text=stored["text"], course=stored.get("course"), item_id=item_id,
                                reconciled=True, item_status=stored.get("status"))
        return self._record(turn, "queued", None, text=comment, item_id=item_id, reconciled=False, **who)


def _has_correction(text: str) -> bool:
    words = [t.norm for t in _tokens(text)]
    return any(_marker_at(words, i) is not None for i in range(len(words)))


def speech_availability(factory: Callable | None) -> dict[str, Any]:
    if factory is not None:
        return {"available": True, "reason": ""}
    if not os.environ.get("GLADIA_API_KEY"):
        return {"available": False, "reason": "GLADIA_API_KEY absent : relancez le serveur avec la clé Gladia."}
    if importlib.util.find_spec("gladiaio_sdk") is None:
        return {"available": False, "reason": "SDK Gladia absent : pip install -e '.[voice]'."}
    return {"available": True, "reason": ""}


def dictation_router(*, policy: DictationPolicy, students: list[Student], origin_ok: Callable[[Any], bool],
                     session_factory: Callable[[dict[str, Any]], Any] | None) -> APIRouter:
    router = APIRouter()
    init_request = build_init_request(AUDIO, students)

    @router.get("/api/workspace/dictations")
    def recent() -> dict[str, Any]:
        return {"dictations": policy.recent()}

    @router.get("/api/workspace/dictations/{turn_id}")
    def one(turn_id: str) -> dict[str, Any]:
        rec = policy.get(turn_id)
        if rec is None:
            raise HTTPException(404, "unknown dictation")
        return {"dictation": rec}

    @router.websocket("/ws/dictation")
    async def dictation(ws: WebSocket) -> None:
        # the HTTP middleware does not see WebSockets: check Host and Origin here, a browser always sends Origin
        if not origin_ok(ws.headers):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            start = await ws.receive_json()
        except Exception:
            await ws.close(code=1003)
            return
        turn_id = str(start.get("turn_id") or "")
        if start.get("type") != "start":
            await ws.close(code=1003)
            return
        done = policy.get(turn_id)
        if done is not None:
            await _finish(ws, dict(done, duplicate=True))
            return
        try:
            turn = policy.start(turn_id, start.get("student_id"), start.get("course"))
        except ValueError as exc:
            await _finish(ws, {"turn_id": turn_id, "status": "refused", "reason": str(exc), "source": SOURCE})
            return
        if not speech_availability(session_factory)["available"]:
            await _finish(ws, policy.refuse(turn, "unavailable"))
            return

        audio: asyncio.Queue[bytes | None] = asyncio.Queue()

        async def chunks() -> AsyncIterator[bytes]:
            while (chunk := await audio.get()) is not None:
                yield chunk

        async def listen() -> None:
            async for u in final_utterances(chunks(), init_request, session_factory):
                if turn.add(u):
                    await ws.send_json({"type": "final", "text": u.text, "confidence": u.confidence})

        await ws.send_json({"type": "listening", "turn_id": turn_id})
        stt = asyncio.create_task(listen())
        ended, reason = False, "disconnected"
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    if len(msg["bytes"]) <= MAX_CHUNK_BYTES:
                        audio.put_nowait(msg["bytes"])
                    continue
                data = json.loads(msg.get("text") or "{}")
                if data.get("type") == "end":
                    ended = True
                    break
                if data.get("type") == "cancel":
                    reason = _cancel_reason(data)
                    break
        except (WebSocketDisconnect, ValueError):
            pass
        audio.put_nowait(None)
        if not ended:
            stt.cancel()
            await _finish(ws, policy.cancel(turn, reason))
            return

        async def watch() -> str:
            # keep listening while Gladia drains: a cancel or a lost page after "end" still cancels the turn
            while True:
                try:
                    msg = await ws.receive()
                except Exception:
                    return "disconnected"
                if msg["type"] == "websocket.disconnect":
                    return "disconnected"
                try:
                    data = json.loads(msg.get("text") or "{}")
                except ValueError:
                    continue
                if data.get("type") == "cancel":
                    return _cancel_reason(data)

        watcher = asyncio.create_task(watch())
        done, _ = await asyncio.wait({stt, watcher}, timeout=DRAIN_TIMEOUT_S, return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            stt.cancel()
            await _finish(ws, policy.cancel(turn, watcher.result()))
            return
        watcher.cancel()
        if stt not in done:
            stt.cancel()
            await _finish(ws, policy.refuse(turn, "speech_to_text_timeout"))
            return
        if stt.exception() is not None:
            await _finish(ws, policy.refuse(turn, "speech_to_text_failed"))
            return
        await _finish(ws, policy.commit(turn))

    return router


def _cancel_reason(data: dict[str, Any]) -> str:
    reason = data.get("reason")
    return reason if reason in CANCEL_REASONS else "cancelled"


async def _finish(ws: WebSocket, rec: dict[str, Any]) -> None:
    with contextlib.suppress(Exception):  # the page may be gone; the ledger already holds the outcome
        await ws.send_json({"type": "result", **rec})
        await ws.close()
