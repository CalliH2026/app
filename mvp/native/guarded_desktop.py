"""H's public desktop bridge, bounded to the foreground PRONOTE demo app.

No SDK package is patched. The driver keeps the SDK's scaled coordinate frame,
checks the Mac app before every operation and discards a captured observation if
focus changed during capture. A focus failure latches until this bridge closes.
"""
from contextlib import contextmanager
from pathlib import Path
import sys
import threading
from typing import Sequence

from hai_agents_local.desktop import PyautoguiDesktopBridge, ensure_macos_input_permissions
from hai_agents_local.killswitch import StopWatcher, arm_esc_listener
from hai_agents_local.manager import BridgeManager
from hai_drivers.common.types import Key, MouseButton, ScrollDirection
from hai_drivers.desktop.interface import DesktopDriverInterface, ObservationSnapshot
from hai_drivers.desktop.models import RunCommandResponse

from .foreground import frontmost_pronote_state


class PronoteForegroundLost(PermissionError):
    """The desktop is no longer an authorised PRONOTE-only observation."""


class PronoteStopRequested(PermissionError):
    """The user requested an out-of-band stop."""


class GuardedDesktopDriver(DesktopDriverInterface):
    """A fail-closed wrapper over the installed H desktop-driver protocol.

    The optional callback must only signal/record the block. Do not synchronously
    stop/join the bridge from its command-dispatch thread. The owning controller
    can watch ``focus_lost`` and cancel its H session from another thread.
    """
    NAVIGATION_KEYS = frozenset({
        "tab", "\t", "enter", "return", "\n", "\r", "escape", "esc",
        "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
        "page_up", "page_down", "pgup", "pgdn", "shift", "shiftleft", "shiftright",
    })

    def __init__(self, driver, *, check=frontmost_pronote_state,
                 focus_lost=None, stop_requested=None, on_block=None, allow_text_input=False):
        self._driver = driver
        self._check_state = check
        self.focus_lost = focus_lost if focus_lost is not None else threading.Event()
        self.stop_requested = stop_requested if stop_requested is not None else threading.Event()
        self.on_block = on_block
        self.allow_text_input = allow_text_input
        self._keys = set()
        self._buttons = set()
        self._lock = threading.RLock()
        self._closed = False
        self.last_block = None

    def _release_owned(self):
        # No new down, click, motion or text event is allowed during cleanup.
        # Only inputs this wrapper actually pressed are released, even if the
        # user changed focus; otherwise a held modifier would remain stuck.
        for key in tuple(self._keys):
            self._keys.discard(key)
            try:self._driver.release_key(key)
            except Exception:pass
        for button in tuple(self._buttons):
            self._buttons.discard(button)
            try:self._driver.mouse_release(button)
            except Exception:pass

    def _guard(self):
        if self.stop_requested.is_set():
            self._release_owned()
            raise PronoteStopRequested("Arrêt demandé : aucune nouvelle capture ni action desktop n’est autorisée.")
        if self._closed or self.focus_lost.is_set():
            raise PronoteForegroundLost("Session desktop arrêtée : PRONOTE n’est plus la cible autorisée.")
        try:
            state = self._check_state()
        except Exception as error:
            state = {"state": "unavailable", "error_type": type(error).__name__}
        if state.get("state") == "ready" and state.get("matches_expected_bundle") is True:
            return state
        self.last_block = state
        self.focus_lost.set()
        self._release_owned()
        if self.on_block is not None:
            try:self.on_block(dict(state))
            except Exception:pass
        raise PronoteForegroundLost("PRONOTE doit rester seul au premier plan. Aucune capture ni action hors cible n’est transmise.")

    def _read(self, name, *args, **kwargs):
        with self._lock:
            self._guard()
            try:value = getattr(self._driver, name)(*args, **kwargs)
            except BaseException:
                self._release_owned()
                raise
            # Includes get_screen_size/get_mouse_position: the local H driver
            # can lazily capture the desktop to initialise its coordinate frame.
            self._guard()
            return value

    @property
    def platform(self):
        with self._lock:
            self._guard()
            value = self._driver.platform
            self._guard()
            return value

    def screenshot_b64(self) -> str:
        return self._read("screenshot_b64")

    def get_observation_snapshot(self) -> ObservationSnapshot:
        return self._read("get_observation_snapshot")

    def get_screen_size(self) -> tuple[int, int]:
        return self._read("get_screen_size")

    def get_mouse_position(self) -> tuple[int, int]:
        return self._read("get_mouse_position")

    def get_accessibility_tree(self) -> str:
        return self._read("get_accessibility_tree")

    def get_number_of_pixels_scrolled_per_click(self) -> int:
        return self._read("get_number_of_pixels_scrolled_per_click")

    def mouse_move_to(self, x: int, y: int):
        return self._read("mouse_move_to", x, y)

    def mouse_press(self, button: MouseButton):
        with self._lock:
            self._guard()
            self._buttons.add(button)
            try:
                value = self._driver.mouse_press(button)
                self._guard()
                return value
            except BaseException:
                self._release_owned()
                raise

    def mouse_release(self, button: MouseButton):
        with self._lock:
            self._guard()
            if button not in self._buttons:return None
            try:return self._driver.mouse_release(button)
            finally:
                self._buttons.discard(button)
                self._guard()

    def _click(self, name, x, y, button, *extra):
        with self._lock:
            self._guard()
            self._buttons.add(button)
            try:
                result = getattr(self._driver, name)(x, y, button, *extra)
                # Both SDK composite operations finish with mouseUp. Keep their
                # native multiclick/Retina semantics rather than reimplementing.
                self._buttons.discard(button)
                self._guard()
                return result
            except BaseException:
                self._release_owned()
                raise

    def click(self, x: int, y: int, button: MouseButton = "left"):
        return self._click("click", x, y, button)

    def double_click(self, x: int, y: int, button: MouseButton = "left", delay_between_clicks: float = 0.05):
        return self._click("double_click", x, y, button, delay_between_clicks)

    def _allow_key(self, key):
        if not self.allow_text_input and key not in self.NAVIGATION_KEYS:
            raise PermissionError("Seules les touches de navigation sont autorisées dans cette démo en lecture seule.")

    def press_key(self, key: Key):
        with self._lock:
            self._guard()
            self._allow_key(key)
            self._keys.add(key)
            try:
                result = self._driver.press_key(key)
                self._guard()
                return result
            except BaseException:
                self._release_owned()
                raise

    def release_key(self, key: Key):
        with self._lock:
            self._guard()
            if key not in self._keys:return None
            try:return self._driver.release_key(key)
            finally:
                self._keys.discard(key)
                self._guard()

    def tap_key(self, key: Key):
        with self._lock:
            try:
                self.press_key(key)
                self.release_key(key)
            finally:
                # If focus changed, _guard already emitted only the owned up.
                if key in self._keys:self._release_owned()

    def hotkey(self, keys: list[Key]):
        with self._lock:
            self._guard()
            for key in keys:self._allow_key(key)
            try:
                for key in keys:self.press_key(key)
                for key in reversed(keys):self.release_key(key)
            finally:
                self._release_owned()

    def write(self, text: str, delay_between_keys: float = 0.0):
        with self._lock:
            self._guard()
            if not self.allow_text_input:
                raise PermissionError("La saisie de texte est désactivée pour cette démo PRONOTE en lecture seule.")
            # Each character is a separate guarded action; a long typing call
            # cannot continue in another app after a user changes focus.
            for character in text:
                self._read("write", character, delay_between_keys)

    def write_at(self, x: int, y: int, text: str, *, overwrite: bool = False,
                 press_enter: bool = False, delay_between_keys: float = 0.0,
                 button: MouseButton = "left"):
        with self._lock:
            self._guard()
            if not self.allow_text_input:
                raise PermissionError("La saisie de texte est désactivée pour cette démo PRONOTE en lecture seule.")
            return super().write_at(x, y, text, overwrite=overwrite,
                press_enter=press_enter, delay_between_keys=delay_between_keys, button=button)

    def scroll_by_n_clicks(self, direction: ScrollDirection, clicks: int):
        return self._read("scroll_by_n_clicks", direction, clicks)

    # Composite drag/scroll/write_at use this wrapper's guarded primitives from
    # DesktopDriverInterface, so no composite bypasses the target checks.

    def run_command(self, command: Sequence[str], timeout: int | None = 60,
                    env: dict[str, str] | None = None, cwd: Path | None = None,
                    detach: bool = False, ignore_errors: bool = False) -> RunCommandResponse:
        with self._lock:
            self._guard()
            raise PermissionError("Les commandes système sont désactivées dans cette démo PRONOTE.")

    def read_file(self, path: str) -> bytes:
        with self._lock:
            self._guard()
            raise PermissionError("L’accès aux fichiers est désactivé dans cette démo PRONOTE.")

    def write_file(self, path: str, content: bytes) -> None:
        with self._lock:
            self._guard()
            raise PermissionError("L’écriture de fichiers est désactivée dans cette démo PRONOTE.")

    def close(self):
        with self._lock:
            if self._closed:return
            self._closed = True
            self._release_owned()
            self._driver.close()


class GuardedPronoteDesktopBridge(PyautoguiDesktopBridge):
    """Public H bridge whose session route must be passed explicitly to H."""
    def __init__(self, *args, check=frontmost_pronote_state, on_block=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.check_foreground = check
        self.focus_lost = threading.Event()
        self.stop_requested = threading.Event()
        self.escape_armed = False
        self.last_block = None
        self._on_block = on_block

    @property
    def environment(self):
        # The explicit id prevents SDK routing.localize_agent from substituting
        # its unguarded, automatically created desktop bridge.
        return {"id": self.environment_id, "kind": "desktop", "host": "user_device",
                "session_id": self.session_id}

    def _record_block(self, state):
        self.last_block = state
        if self._on_block is not None:
            try:self._on_block(state)
            except Exception:pass

    def _check_before_start(self):
        if self.stop_requested.is_set():
            raise PronoteStopRequested("Arrêt demandé avant le lancement du pilote H.")
        if self.focus_lost.is_set():
            raise PronoteForegroundLost("Ce pilote a déjà été arrêté après une perte de premier plan.")
        try:state = self.check_foreground()
        except Exception as error:
            state = {"state": "unavailable", "error_type": type(error).__name__}
        if state.get("state") != "ready" or state.get("matches_expected_bundle") is not True:
            self.focus_lost.set()
            self._record_block(state)
            raise PronoteForegroundLost("PRONOTE Démo locale doit être au premier plan avant de servir le pilote H.")

    def preflight(self):
        # No implicit permission dialog while the controller is being prepared.
        if sys.platform == "darwin":ensure_macos_input_permissions(prompt=False)
        self._check_before_start()

    def create_driver(self):
        self._check_before_start()
        return GuardedDesktopDriver(super().create_driver(), check=self.check_foreground,
            focus_lost=self.focus_lost, stop_requested=self.stop_requested, on_block=self._record_block)


def _arm_escape_listener_if_authorized():
    # The SDK's optional Esc listener is separate from its stop-file watcher.
    # Never request Input Monitoring: this extra permission is not necessary
    # for H to run, and the stop-file channel remains available without it.
    if sys.platform == "darwin":
        try:
            import Quartz
            preflight = getattr(Quartz, "CGPreflightListenEventAccess", None)
            if preflight is None or not preflight():return None
        except Exception:return None
    return arm_esc_listener()


@contextmanager
def guarded_pronote_bridge(*, api_key, base_url=None, environment_id="pronote-desktop",
                           check=frontmost_pronote_state, on_block=None):
    """Own the public manager and expose one explicitly routed guarded bridge.

    The caller must cancel its H session before leaving this context on failure.
    ``BridgeManager.stop`` always runs; it releases only run-owned held inputs.
    """
    manager = BridgeManager()
    bridge = GuardedPronoteDesktopBridge(environment_id, api_key=api_key,
        base_url=base_url, check=check, on_block=on_block)
    started = manager.ensure([bridge])
    watcher = None
    listener = None
    try:
        # Both callbacks only signal the controller. No bridge join/network
        # cancellation is attempted on a listener/dispatch thread.
        watcher = StopWatcher(bridge.stop_requested.set)
        listener = _arm_escape_listener_if_authorized()
        bridge.escape_armed = listener is not None
        yield bridge
    finally:
        try:
            if watcher is not None:watcher.stop()
        finally:
            try:
                if listener is not None:listener.stop()
            finally:
                manager.stop(started)
