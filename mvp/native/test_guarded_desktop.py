"""No real desktop operations: verify the SDK guard blocks foreign frames/input."""
import pytest
from hai_drivers.desktop.interface import ObservationSnapshot
from hai_agents_local.routing import localize_agent

from mvp.native import guarded_desktop as guarded


READY = {"state": "ready", "matches_expected_bundle": True}
BLOCKED = {"state": "blocked", "matches_expected_bundle": False}


class FakeDriver:
    platform = "Darwin"

    def __init__(self):self.calls=[]
    def screenshot_b64(self):
        self.calls.append(("screenshot",));return "REAL_FRAME_FROM_DRIVER"
    def get_observation_snapshot(self):
        self.calls.append(("observation",))
        return ObservationSnapshot(screenshot_b64="REAL_FRAME_FROM_DRIVER",cursor_position=(3,4))
    def click(self,*args):self.calls.append(("click",*args))
    def press_key(self,key):self.calls.append(("key_down",key))
    def release_key(self,key):self.calls.append(("key_up",key))
    def mouse_press(self,button):self.calls.append(("mouse_down",button))
    def mouse_release(self,button):self.calls.append(("mouse_up",button))
    def close(self):self.calls.append(("close",))


@pytest.mark.parametrize("operation", [lambda driver:driver.screenshot_b64(),
    lambda driver:driver.get_observation_snapshot(),lambda driver:driver.click(10,20)])
def test_outside_pronote_never_calls_capture_or_action(operation):
    inner=FakeDriver();driver=guarded.GuardedDesktopDriver(inner,check=lambda:BLOCKED)
    with pytest.raises(guarded.PronoteForegroundLost):operation(driver)
    assert inner.calls==[]
    assert driver.focus_lost.is_set()


@pytest.mark.parametrize("method,call", [("screenshot",lambda d:d.screenshot_b64()),
                                      ("observation",lambda d:d.get_observation_snapshot())])
def test_focus_lost_during_capture_discards_the_obtained_frame(method,call):
    states=iter((READY,BLOCKED))
    inner=FakeDriver();driver=guarded.GuardedDesktopDriver(inner,check=lambda:next(states))
    with pytest.raises(guarded.PronoteForegroundLost):call(driver)
    assert inner.calls==[(method,)]
    # Returning to PRONOTE cannot revive this already blocked bridge.
    driver._check_state=lambda:READY
    with pytest.raises(guarded.PronoteForegroundLost):call(driver)
    assert inner.calls==[(method,)]


def test_focus_loss_releases_only_owned_inputs_without_new_key_or_click():
    state=dict(READY);inner=FakeDriver()
    driver=guarded.GuardedDesktopDriver(inner,check=lambda:state)
    driver.press_key("shift")
    driver.mouse_press("left")
    state.update(BLOCKED)
    with pytest.raises(guarded.PronoteForegroundLost):driver.click(90,90)
    assert inner.calls==[("key_down","shift"),("mouse_down","left"),
                         ("key_up","shift"),("mouse_up","left")]
    driver.close();driver.close()
    assert inner.calls[-1]==("close",)
    assert inner.calls.count(("key_up","shift"))==1
    assert inner.calls.count(("mouse_up","left"))==1


def test_text_shell_and_files_are_rejected_before_any_input():
    inner=FakeDriver();driver=guarded.GuardedDesktopDriver(inner,check=lambda:READY)
    for operation in (lambda:driver.write("123"),lambda:driver.write_at(1,2,"123"),
                      lambda:driver.run_command(["true"]),lambda:driver.read_file("/tmp/a"),
                      lambda:driver.write_file("/tmp/a",b"a")):
        with pytest.raises(PermissionError):operation()
    assert inner.calls==[]


def test_explicit_environment_does_not_get_an_unguarded_sdk_auto_bridge():
    bridge=guarded.GuardedPronoteDesktopBridge(api_key="test-key",check=lambda:READY)
    localized=localize_agent({"name":"test","environments":[bridge.environment]},api_key="test-key")
    assert localized.bridges==[]
    assert localized.agent["environments"][0]["session_id"]==bridge.session_id


def test_public_manager_lifetime_is_owned_and_cleaned(monkeypatch):
    events=[]
    class Manager:
        def ensure(self,bridges):
            events.append(("ensure",bridges[0].session_id));return [bridges[0].session_id]
        def stop(self,ids):events.append(("stop",ids[0]))
    monkeypatch.setattr(guarded,"BridgeManager",Manager)
    class Watcher:
        def __init__(self,on_stop):self.on_stop=on_stop
        def stop(self):pass
    monkeypatch.setattr(guarded,"StopWatcher",Watcher)
    monkeypatch.setattr(guarded,"_arm_escape_listener_if_authorized",lambda:None)
    with guarded.guarded_pronote_bridge(api_key="test-key",check=lambda:READY) as bridge:
        assert bridge.environment["host"]=="user_device"
        session_id=bridge.session_id
    assert events==[("ensure",session_id),("stop",session_id)]


def test_stop_watcher_only_signals_and_blocks_following_driver_operations(monkeypatch):
    callbacks=[];events=[]
    class Manager:
        def ensure(self,bridges):return [bridges[0].session_id]
        def stop(self,ids):events.append("manager_stop")
    class Watcher:
        def __init__(self,on_stop):callbacks.append(on_stop)
        def stop(self):events.append("watcher_stop")
    class Listener:
        def stop(self):events.append("listener_stop")
    monkeypatch.setattr(guarded,"BridgeManager",Manager)
    monkeypatch.setattr(guarded,"StopWatcher",Watcher)
    monkeypatch.setattr(guarded,"_arm_escape_listener_if_authorized",lambda:Listener())
    with guarded.guarded_pronote_bridge(api_key="test-key",check=lambda:READY) as bridge:
        inner=FakeDriver()
        driver=guarded.GuardedDesktopDriver(inner,check=lambda:READY,stop_requested=bridge.stop_requested)
        driver.press_key("shift")
        callbacks[0]()
        assert bridge.stop_requested.is_set() and bridge.escape_armed
        assert events==[]  # The watcher callback performs no stop/join itself.
        with pytest.raises(guarded.PronoteStopRequested):driver.click(10,20)
        assert inner.calls==[("key_down","shift"),("key_up","shift")]
    assert events==["watcher_stop","listener_stop","manager_stop"]


def test_listener_teardown_failure_still_stops_the_owned_bridge(monkeypatch):
    events=[]
    class Manager:
        def ensure(self,bridges):return [bridges[0].session_id]
        def stop(self,ids):events.append("manager_stop")
    class Watcher:
        def __init__(self,on_stop):pass
        def stop(self):pass
    class Listener:
        def stop(self):raise RuntimeError("Listener teardown failed")
    monkeypatch.setattr(guarded,"BridgeManager",Manager)
    monkeypatch.setattr(guarded,"StopWatcher",Watcher)
    monkeypatch.setattr(guarded,"_arm_escape_listener_if_authorized",lambda:Listener())
    with pytest.raises(RuntimeError,match="Listener teardown"):
        with guarded.guarded_pronote_bridge(api_key="test-key",check=lambda:READY):pass
    assert events==["manager_stop"]
