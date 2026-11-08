"""No real desktop capture, input or provider calls: native launch boundaries."""
import fcntl
import json
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from . import recordings
from .native import foreground, native_documents, guarded_desktop


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings,'STATUS_FILE',tmp_path/'native.json')
    monkeypatch.setattr(recordings,'RUNNING',threading.Lock())
    monkeypatch.setattr(recordings,'NATIVE_STOP',threading.Event())
    monkeypatch.setattr(recordings,'desktop_preflight',lambda:{'state':'ready','message':'ready'})
    monkeypatch.setattr(recordings,'key',lambda name:'test-key')
    monkeypatch.setattr(native_documents,'read_window_snapshot',lambda:{'windows':[{'title':'Base Exemple PRONOTE 2026','pid':123,'foreground':True}]})
    return recordings.STATUS_FILE


def settled():
    deadline=time.monotonic()+2
    while recordings.RUNNING.locked() and time.monotonic()<deadline:time.sleep(.005)
    assert not recordings.RUNNING.locked()


def test_wine_foreground_does_not_start_h_when_mac_app_is_different(isolated,monkeypatch):
    monkeypatch.setattr(foreground,'frontmost_pronote_state',lambda:{'state':'blocked','matches_expected_bundle':False})
    def forbidden():raise AssertionError('No H call without true Mac foreground')
    monkeypatch.setattr(recordings,'_client',forbidden)
    recordings.start_native_session(desktop_prepared=True,focus_timeout_seconds=0)
    settled()
    state=json.loads(isolated.read_text())
    assert state['state']=='blocked'
    assert state['session_id'] is None
    assert state['reason']=='pronote_not_foreground'


def test_two_cli_processes_cannot_control_desktop_or_overwrite_session(isolated):
    original={'state':'running','session_id':'existing-owner'}
    isolated.write_text(json.dumps(original))
    with isolated.with_suffix('.lock').open('a+') as owner:
        fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
        returned=recordings.start_native_session(desktop_prepared=True)
        assert returned['session_id']=='existing-owner'
        assert json.loads(isolated.read_text())==original
        assert not recordings.RUNNING.locked()


def test_transient_focus_is_not_enough_to_start(isolated,monkeypatch):
    sequence=iter([{'state':'blocked'},{'state':'ready'},{'state':'blocked'},{'state':'ready','marker':'first'},{'state':'ready','marker':'stable'}])
    monkeypatch.setattr(recordings.time,'sleep',lambda delay:None)
    result=recordings.wait_for_pronote_foreground(2,check=lambda:next(sequence))
    assert result['marker']=='stable'


def test_user_cancel_does_not_even_check_a_new_window(isolated):
    recordings.NATIVE_STOP.set()
    def forbidden():raise AssertionError('Cancelled before desktop access')
    with pytest.raises(InterruptedError):recordings.wait_for_pronote_foreground(2,check=forbidden)


def test_h_receives_only_explicit_guarded_environment(isolated,monkeypatch):
    environment={'id':'pronote-desktop','kind':'desktop','host':'user_device','session_id':'guarded-bridge'}
    guard=SimpleNamespace(environment=environment,focus_lost=threading.Event(),stop_requested=threading.Event(),escape_armed=False)
    @contextmanager
    def bridge(**kwargs):yield guard
    monkeypatch.setattr(guarded_desktop,'guarded_pronote_bridge',bridge)
    monkeypatch.setattr(recordings,'wait_for_pronote_foreground',lambda *a,**k:{'state':'ready'})
    monkeypatch.setattr(foreground,'frontmost_pronote_state',lambda:{'state':'ready'})
    calls=[]
    session=SimpleNamespace(id='actual-test-handle',wait_for_completion=lambda **kwargs:None,status=lambda:SimpleNamespace(status='completed'))
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def start_session(self,**kwargs):calls.append(kwargs);return session
    monkeypatch.setattr(recordings,'_client',Client)
    monkeypatch.setattr(recordings,'session_evidence',lambda client,id:{'status':'completed','session_id':id})
    recordings.start_native_session(desktop_prepared=True)
    settled()
    assert calls[0]['agent']['environments']==[environment]
    assert calls[0]['max_steps']==8
    state=json.loads(isolated.read_text())
    assert state['guarded_desktop'] is True and state['state']=='completed'
