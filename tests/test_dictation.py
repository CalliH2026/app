"""Automatic dictation (ui/dictation.py): one dictation turn -> guards -> live queue, offline.

Gladia is replaced by a fake live session with the SDK's surface (on, send_audio, stop_recording,
end_session) that replays scripted transcript messages; it is a test double only. The policy, the
ledger, the QueueStore, the WebSocket route and its Host/Origin guard are the real code.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent.queue_store import QueueStore, StopRequested
from ui.app import create_app
from ui.dictation import DictationPolicy, Turn
from voice.gladia_live import Utterance
from voice.roster import load_roster
from voice.structurer import RuleBasedStructurer

ROOT = Path(__file__).resolve().parents[1]
COURSE = "3A, FRANCAIS, Trimestre 1"
BASE = "http://127.0.0.1:8765"
ORIGIN = {"origin": "http://127.0.0.1:8765"}
STUDENTS = load_roster(ROOT / "data" / "roster.csv")


def _policy(tmp_path: Path, course: str | None = COURSE) -> tuple[DictationPolicy, QueueStore]:
    store = QueueStore(tmp_path / "runs" / "queue.jsonl")
    return DictationPolicy(STUDENTS, course, RuleBasedStructurer(STUDENTS), store, tmp_path / "workspace"), store


def _turn(policy: DictationPolicy, *texts: str, selected: str | None = "s01", conf: float = 0.95,
          turn_id: str = "turn-0000000001") -> Turn:
    turn = policy.start(turn_id, selected, COURSE)
    for i, t in enumerate(texts):
        turn.add(Utterance(t, float(i), float(i) + 0.9, conf))
    return turn


# ---- policy: what reaches the queue ----------------------------------------------------------------------

def test_clear_dictation_is_queued_as_automatic_dictation(tmp_path):
    policy, store = _policy(tmp_path)
    rec = policy.commit(_turn(policy, "Lucas Bernard, ton récit est vivant, mais découpe-le en paragraphes."))
    assert rec["status"] == "queued" and rec["student_id"] == "s01"
    [item] = store.all()
    assert item["student"] == "Lucas Bernard" and item["course"] == COURSE
    assert item["text"] == "Ton récit est vivant, mais découpe-le en paragraphes."
    assert item["source"] == "automatic_dictation" and item["previous_value"] is None
    assert rec["item_id"] == item["item_id"]


def test_fragments_of_one_turn_are_aggregated_into_one_item(tmp_path):
    policy, store = _policy(tmp_path)
    rec = policy.commit(_turn(policy, "Lucas Bernard, ton récit est vivant,", "mais relis-toi davantage."))
    assert rec["status"] == "queued"
    assert [it["text"] for it in store.all()] == ["Ton récit est vivant, mais relis-toi davantage."]


def test_duplicate_final_fragment_is_counted_once(tmp_path):
    policy, store = _policy(tmp_path)
    turn = policy.start("turn-dup-final-1", "s01", COURSE)
    u = Utterance("Lucas Bernard, bon trimestre.", 0.0, 1.2, 0.95)
    turn.add(u)
    turn.add(u)
    assert turn.transcript == "Lucas Bernard, bon trimestre."
    policy.commit(turn)
    assert [it["text"] for it in store.all()] == ["Bon trimestre."]


def test_same_turn_committed_twice_queues_one_item(tmp_path):  # ledger replay
    policy, store = _policy(tmp_path)
    first = policy.commit(_turn(policy, "Lucas Bernard, bon trimestre."))
    again = policy.commit(_turn(policy, "Lucas Bernard, bon trimestre."))
    assert again["item_id"] == first["item_id"] and again["duplicate"] is True
    assert len(store.all()) == 1


def test_unnamed_or_unknown_name_never_falls_back_to_the_selected_pupil(tmp_path):
    policy, store = _policy(tmp_path)
    for i, text in enumerate(["Ton récit est vivant. Relis-toi davantage.", "Paul Durand, travail sérieux."]):
        rec = policy.commit(_turn(policy, text, selected="s01", turn_id=f"turn-noname-{i:04d}"))
        assert rec["status"] == "needs_correction" and rec["reason"] == "no_known_name"
        assert rec["student_id"] is None
    assert store.all() == []


def test_named_pupil_wins_when_nobody_is_selected(tmp_path):
    policy, store = _policy(tmp_path)
    rec = policy.commit(_turn(policy, "Léa Girard, très bon trimestre.", selected=None))
    assert rec["status"] == "queued" and store.all()[0]["student"] == "Léa Girard"


@pytest.mark.parametrize("texts, selected, conf, reason", [
    (("Ton récit est vivant.",), None, 0.95, "no_known_name"),
    (("Paul Durand, travail sérieux.",), "s01", 0.95, "no_known_name"),
    (("Léa Girard, très bon trimestre.",), "s01", 0.95, "pupil_mismatch"),
    (("Lucas, bon trimestre.",), None, 0.95, "ambiguous"),
    (("Lucas, bon trimestre.",), "s01", 0.95, "ambiguous"),
    (("Lucas Bernard, bon trimestre.",), "s01", 0.4, "low_asr_confidence"),
    (("Lucas Bernard, bon trimestre.",), "s01", 0.69, "low_asr_confidence"),
    (("Lucas Bernard, bon travail. Léa Girard, continue.",), None, 0.95, "several_comments"),
    (("Non, plutôt : travail régulier.",), "s01", 0.95, "correction_command"),
    (("Lucas Bernard, travail sérieux, non plutôt travail régulier.",), "s01", 0.95, "correction_command"),
    (("Lucas Bernard, " + "très bien " * 40,), "s01", 0.95, "too_long"),
])
def test_unclear_dictation_stops_for_correction(tmp_path, texts, selected, conf, reason):
    policy, store = _policy(tmp_path)
    rec = policy.commit(_turn(policy, *texts, selected=selected, conf=conf))
    assert rec["status"] == "needs_correction" and rec["reason"] == reason
    assert rec["transcript"]  # kept for the teacher's correction, nothing truncated
    assert store.all() == []


def test_name_confidence_is_checked_separately_from_speech_confidence(tmp_path):
    store = QueueStore(tmp_path / "runs" / "queue.jsonl")
    real = RuleBasedStructurer(STUDENTS)

    class CloseRunnerUp:
        def structure(self, text):
            items = real.structure(text)
            for it in items:
                it.confidence = 0.6  # what voice/structurer.py gives a match with a close runner-up
            return items

    policy = DictationPolicy(STUDENTS, COURSE, CloseRunnerUp(), store, tmp_path / "workspace")
    rec = policy.commit(_turn(policy, "Lucas Bernard, bon trimestre.", conf=0.99))
    assert rec["status"] == "needs_correction" and rec["reason"] == "low_name_confidence"
    assert store.all() == []


def test_stop_pressed_while_the_turn_is_decided_queues_nothing(tmp_path):
    store = QueueStore(tmp_path / "runs" / "queue.jsonl")
    real = RuleBasedStructurer(STUDENTS)

    class StopDuringDecision:
        def structure(self, text):
            store.stop()  # after the first STOP check, before the append
            return real.structure(text)

    policy = DictationPolicy(STUDENTS, COURSE, StopDuringDecision(), store, tmp_path / "workspace")
    rec = policy.commit(_turn(policy, "Lucas Bernard, bon trimestre."))
    assert rec["status"] == "refused" and rec["reason"] == "stopped"
    store.resume()
    assert store.all() == [] and store.next_pending() is None


def test_stop_right_after_the_append_leaves_nothing_pending_for_resume(tmp_path):
    policy, store = _policy(tmp_path)
    assert policy.commit(_turn(policy, "Lucas Bernard, bon trimestre."))["status"] == "queued"
    store.stop()
    store.resume()
    assert [it["status"] for it in store.all()] == ["aborted"] and store.next_pending() is None


def test_crash_between_queue_append_and_ledger_never_writes_twice(tmp_path, monkeypatch):
    policy, store = _policy(tmp_path)

    def power_cut(rec):
        raise OSError("power cut")

    monkeypatch.setattr(policy, "_save", power_cut)
    with pytest.raises(OSError):
        policy.commit(_turn(policy, "Lucas Bernard, bon trimestre."))
    [item] = store.all()
    store.update(item["item_id"], status="verified")  # the writer finished before the retry
    policy2, _ = _policy(tmp_path)
    rec = policy2.commit(_turn(policy2, "Lucas Bernard, bon trimestre."))
    assert rec["item_id"] == item["item_id"] == "d-turn-0000000001" and rec["reconciled"] is True
    assert [it["status"] for it in store.all()] == ["verified"]


def test_two_turns_with_the_same_text_never_alias_across_a_crash(tmp_path, monkeypatch):
    policy, store = _policy(tmp_path)
    a = policy.commit(_turn(policy, "Lucas Bernard, bon trimestre.", turn_id="turn-aaaaaaaaaa"))
    real_save = policy._save

    def power_cut(rec):
        raise OSError("power cut")

    monkeypatch.setattr(policy, "_save", power_cut)
    with pytest.raises(OSError):
        policy.commit(_turn(policy, "Lucas Bernard, bon trimestre.", turn_id="turn-bbbbbbbbbb"))
    monkeypatch.setattr(policy, "_save", real_save)
    assert [it["item_id"] for it in store.all()] == ["d-turn-aaaaaaaaaa", "d-turn-bbbbbbbbbb"]
    store.update(a["item_id"], status="verified")  # A completes before B is retried
    policy2, _ = _policy(tmp_path)
    b = policy2.commit(_turn(policy2, "Lucas Bernard, bon trimestre.", turn_id="turn-bbbbbbbbbb"))
    assert b["item_id"] == "d-turn-bbbbbbbbbb" and b["reconciled"] is True
    assert [it["item_id"] for it in store.all()] == ["d-turn-aaaaaaaaaa", "d-turn-bbbbbbbbbb"]


def test_reconciliation_reports_the_queued_item_not_the_replayed_content(tmp_path, monkeypatch):
    policy, store = _policy(tmp_path)

    def power_cut(rec):
        raise OSError("power cut")

    monkeypatch.setattr(policy, "_save", power_cut)
    with pytest.raises(OSError):
        policy.commit(_turn(policy, "Lucas Bernard, bon trimestre."))
    policy2, _ = _policy(tmp_path)
    rec = policy2.commit(_turn(policy2, "Lucas Bernard, très bon trimestre, bravo."))
    assert rec["reconciled"] is True and rec["text"] == "Bon trimestre." and rec["student_name"] == "Lucas Bernard"
    assert rec["course"] == COURSE and rec["item_status"] == "pending" and len(store.all()) == 1


def test_queue_append_refuses_under_stop_and_reconciles_any_status(tmp_path):
    store = QueueStore(tmp_path / "queue.jsonl")
    first = store.append({"item_id": "d-x", "student": "Lucas Bernard", "text": "Bien.", "course": COURSE},
                         idempotent=True, refuse_when_stopped=True)
    store.update("d-x", status="mismatch")
    again = store.append({"item_id": "d-x", "student": "Lucas Bernard", "text": "Bien.", "course": COURSE},
                         idempotent=True, refuse_when_stopped=True)
    assert again["duplicate"] is True and again["status"] == "mismatch" and len(store.all()) == 1
    store.stop()
    with pytest.raises(StopRequested):
        store.append({"item_id": "d-y", "student": "Lucas Bernard", "text": "Bien.", "course": COURSE},
                     idempotent=True, refuse_when_stopped=True)
    assert first["item_id"] == "d-x" and len(store.all()) == 1


def test_empty_turn_is_refused(tmp_path):
    policy, store = _policy(tmp_path)
    rec = policy.commit(_turn(policy))
    assert rec["status"] == "refused" and rec["reason"] == "empty" and store.all() == []


def test_stop_set_before_the_end_refuses_the_turn(tmp_path):
    policy, store = _policy(tmp_path)
    turn = _turn(policy, "Lucas Bernard, bon trimestre.")
    store.stop()
    rec = policy.commit(turn)
    assert rec["status"] == "refused" and rec["reason"] == "stopped" and store.all() == []


def test_spoken_stop_sets_stop(tmp_path):
    policy, store = _policy(tmp_path)
    rec = policy.commit(_turn(policy, "Stop."))
    assert rec["status"] == "stopped" and store.stop_requested() and store.all() == []


def test_start_refuses_stale_course_unknown_pupil_and_stop(tmp_path):
    policy, store = _policy(tmp_path)
    with pytest.raises(ValueError, match="stale_context"):
        policy.start("turn-stale-0001", "s01", "3A, FRANCAIS, Trimestre 2")
    with pytest.raises(ValueError, match="unknown_pupil"):
        policy.start("turn-unknown-01", "s99", COURSE)
    store.stop()
    with pytest.raises(ValueError, match="stopped"):
        policy.start("turn-stopped-01", "s01", COURSE)


def test_no_configured_course_refuses_dictation(tmp_path):
    policy, _ = _policy(tmp_path, course=None)
    with pytest.raises(ValueError, match="no_course"):
        policy.start("turn-nocourse-1", "s01", None)


def test_cancelled_turn_queues_nothing_and_is_final(tmp_path):
    policy, store = _policy(tmp_path)
    turn = _turn(policy, "Lucas Bernard, bon trimestre.")
    rec = policy.cancel(turn, "disconnected")
    assert rec["status"] == "cancelled" and rec["reason"] == "disconnected"
    assert policy.commit(turn)["status"] == "cancelled"  # a late end never resurrects a cancelled turn
    assert store.all() == []


def test_ledger_survives_restart(tmp_path):
    policy, store = _policy(tmp_path)
    first = policy.commit(_turn(policy, "Lucas Bernard, bon trimestre."))
    policy2, _ = _policy(tmp_path)
    assert policy2.get("turn-0000000001")["item_id"] == first["item_id"]
    assert policy2.commit(_turn(policy2, "Lucas Bernard, bon trimestre."))["duplicate"] is True
    assert len(store.all()) == 1


# ---- WebSocket route with a fake Gladia live session ------------------------------------------------------

def _msg(text: str, final: bool = True, start: float = 0.0, conf: float = 0.95):
    u = SimpleNamespace(text=text, start=start, end=start + 1.0, confidence=conf)
    return SimpleNamespace(type="transcript", data=SimpleNamespace(is_final=final, utterance=u))


class FakeLiveSession:
    """Test double with the gladiaio-sdk async live session surface; replays `script` when recording stops."""

    def __init__(self, script, code: int = 1000, delay: float = 0.0):
        self.script, self.code, self.handlers, self.audio, self.status = script, code, {}, [], "started"
        self.delay = delay

    def on(self, event, cb):
        self.handlers[event] = cb

    def send_audio(self, chunk):
        self.audio.append(chunk)

    def stop_recording(self):
        if self.delay:
            import asyncio

            asyncio.get_running_loop().call_later(self.delay, self._emit)
        else:
            self._emit()

    def _emit(self):
        for m in self.script:
            self.handlers["message"](m)
        if self.code != 1000:
            self.handlers["error"](RuntimeError("socket"))
        self.status = "ended"
        self.handlers["ended"](SimpleNamespace(code=self.code))

    def end_session(self):
        self.status = "ended"


def _app(tmp_path: Path, script=(), code: int = 1000, factory=True, delay: float = 0.0):
    queue = tmp_path / "runs" / "queue.jsonl"
    cases = tmp_path / "dossiers"
    shutil.copytree(ROOT / "data" / "dossiers", cases)
    sessions: list[FakeLiveSession] = []

    def session_factory(init_request):
        assert init_request["sample_rate"] == 16000 and init_request["language_config"]["languages"] == ["fr"]
        s = FakeLiveSession(list(script), code, delay)
        sessions.append(s)
        return s

    app = create_app(queue_path=queue, roster_path=ROOT / "data" / "roster.csv", course=COURSE, cases_dir=cases,
                     workspace_dir=tmp_path / "workspace", stt_session_factory=session_factory if factory else None)
    return TestClient(app, base_url=BASE), QueueStore(queue), sessions


def _dictate(client, turn_id="turn-ws-000001", student_id="s01", course=COURSE, end="end", chunks=2):
    events = []
    with client.websocket_connect("ws://127.0.0.1:8765/ws/dictation", headers=ORIGIN) as ws:
        ws.send_json({"type": "start", "turn_id": turn_id, "student_id": student_id, "course": course})
        events.append(ws.receive_json())
        if events[-1]["type"] == "result":
            return events
        for _ in range(chunks):
            ws.send_bytes(b"\x00\x00" * 1600)
        ws.send_json({"type": end})
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] == "result":
                return events


def test_websocket_turn_queues_only_after_the_end(tmp_path):
    script = [_msg("Lucas Bernard,", final=False), _msg("Lucas Bernard, ton récit est vivant,"),
              _msg("mais relis-toi.", start=2.0)]
    client, store, sessions = _app(tmp_path, script)
    events = _dictate(client)
    assert events[0] == {"type": "listening", "turn_id": "turn-ws-000001"}
    finals = [e["text"] for e in events if e["type"] == "final"]
    assert finals == ["Lucas Bernard, ton récit est vivant,", "mais relis-toi."]  # no partial forwarded
    result = events[-1]
    assert result["status"] == "queued" and result["student_name"] == "Lucas Bernard"
    assert [it["text"] for it in store.all()] == ["Ton récit est vivant, mais relis-toi."]
    assert len(sessions[0].audio) == 2


def test_partial_transcripts_never_queue(tmp_path):
    client, store, _ = _app(tmp_path, [_msg("Lucas Bernard, bon trimestre.", final=False)])
    assert _dictate(client)[-1]["reason"] == "empty"
    assert store.all() == []


def test_cancel_and_disconnect_queue_nothing(tmp_path):
    client, store, _ = _app(tmp_path, [_msg("Lucas Bernard, bon trimestre.")])
    assert _dictate(client, end="cancel")[-1]["status"] == "cancelled"
    with client.websocket_connect("ws://127.0.0.1:8765/ws/dictation", headers=ORIGIN) as ws:
        ws.send_json({"type": "start", "turn_id": "turn-ws-drop-01", "student_id": "s01", "course": COURSE})
        ws.receive_json()
        ws.send_bytes(b"\x00\x00" * 1600)
    assert store.all() == []
    rec = client.get("/api/workspace/dictations/turn-ws-drop-01").json()["dictation"]
    assert rec["status"] == "cancelled"


def test_cancel_after_end_while_finals_are_pending_queues_nothing(tmp_path):
    client, store, _ = _app(tmp_path, [_msg("Lucas Bernard, bon trimestre.")], delay=0.4)
    with client.websocket_connect("ws://127.0.0.1:8765/ws/dictation", headers=ORIGIN) as ws:
        ws.send_json({"type": "start", "turn_id": "turn-late-cancel", "student_id": "s01", "course": COURSE})
        ws.receive_json()
        ws.send_bytes(b"\x00\x00" * 1600)
        ws.send_json({"type": "end"})
        ws.send_json({"type": "cancel", "reason": "pupil_changed"})
        result = ws.receive_json()
        while result["type"] != "result":
            result = ws.receive_json()
    assert result["status"] == "cancelled" and result["reason"] == "pupil_changed"
    import time

    time.sleep(0.6)  # the late finals arrive after the cancel
    assert store.all() == []
    assert client.get("/api/workspace/dictations/turn-late-cancel").json()["dictation"]["status"] == "cancelled"


def test_retried_turn_id_does_not_write_twice(tmp_path):
    client, store, _ = _app(tmp_path, [_msg("Lucas Bernard, bon trimestre.")])
    first = _dictate(client)[-1]
    again = _dictate(client)
    assert again[-1]["item_id"] == first["item_id"] and again[-1]["duplicate"] is True
    assert len(store.all()) == 1


def test_provider_failure_queues_nothing(tmp_path):
    client, store, _ = _app(tmp_path, [_msg("Lucas Bernard, bon trimestre.")], code=4500)
    result = _dictate(client)[-1]
    assert result["status"] == "refused" and result["reason"] == "speech_to_text_failed"
    assert store.all() == []


def test_stale_course_and_stop_are_refused_at_start(tmp_path):
    client, store, sessions = _app(tmp_path, [_msg("Lucas Bernard, bon trimestre.")])
    assert _dictate(client, course="3A, FRANCAIS, Trimestre 2")[-1]["reason"] == "stale_context"
    client.post("/api/stop", json={})
    assert _dictate(client, turn_id="turn-ws-stop-01")[-1]["reason"] == "stopped"
    assert store.all() == [] and sessions == []


def test_websocket_refuses_foreign_or_missing_origin(tmp_path):
    client, _store, _ = _app(tmp_path)
    for headers in ({"origin": "http://evil.example"}, {}, {"origin": "http://127.0.0.1:9999"}):
        with pytest.raises(WebSocketDisconnect), \
                client.websocket_connect("ws://127.0.0.1:8765/ws/dictation", headers=headers) as ws:
            ws.receive_json()
    foreign = TestClient(client.app, base_url="http://evil.example")
    with pytest.raises(WebSocketDisconnect), \
            foreign.websocket_connect("ws://evil.example/ws/dictation", headers={"origin": "http://evil.example"}) as ws:
        ws.receive_json()


def test_without_speech_key_dictation_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("GLADIA_API_KEY", raising=False)
    client, _store, _ = _app(tmp_path, factory=False)
    info = client.get("/api/workspace/cases").json()["dictation"]
    assert info["available"] is False and "GLADIA_API_KEY" in info["reason"]
    assert _dictate(client)[-1]["reason"] == "unavailable"


def test_recent_dictations_listed_and_preparation_never_queues(tmp_path):
    client, store, _ = _app(tmp_path, [_msg("Lucas Bernard, bon trimestre.")])
    _dictate(client)
    recent = client.get("/api/workspace/dictations").json()["dictations"]
    assert [d["turn_id"] for d in recent] == ["turn-ws-000001"]
    client.post("/api/workspace/cases/s01-francais-t1/prepare", json={})
    assert len(store.all()) == 1
