"""Guard Mac foreground independently from the Wine bottle's focus."""
from mvp.native import foreground


def test_another_mac_app_blocks_without_inspecting_its_window(monkeypatch):
    monkeypatch.setattr(foreground.sys, "platform", "darwin")
    monkeypatch.setattr(foreground, "_frontmost_application_info", lambda: {
        "bundle_id": "com.example.browser", "name": "Browser", "pid": 42,
        "application_path": "/Applications/Browser.app",
    })
    def forbidden(pid):
        raise AssertionError("An unrelated app's window must not be inspected")
    monkeypatch.setattr(foreground, "_pronote_window_title", forbidden)
    state = foreground.frontmost_pronote_state()
    assert state["state"] == "blocked"
    assert state["matches_expected_bundle"] is False
    assert state["window_title"] is None


def test_only_authorised_pronote_bundle_is_ready(monkeypatch):
    monkeypatch.setattr(foreground.sys, "platform", "darwin")
    monkeypatch.setattr(foreground, "_frontmost_application_info", lambda: {
        "bundle_id": foreground.EXPECTED_BUNDLE_ID,
        "name": "PRONOTE Démo locale", "pid": 51,
        "application_path": "/project/PRONOTE Démo locale.app",
    })
    monkeypatch.setattr(foreground, "_pronote_window_title", lambda pid: "Base Exemple.not")
    state = foreground.frontmost_pronote_state()
    assert state["state"] == "ready"
    assert state["matches_expected_bundle"] is True
    assert state["window_title"] == "Base Exemple.not"


def test_unavailable_mac_api_never_marks_ready(monkeypatch):
    monkeypatch.setattr(foreground.sys, "platform", "darwin")
    def missing():
        raise ImportError("AppKit missing")
    monkeypatch.setattr(foreground, "_frontmost_application_info", missing)
    assert foreground.frontmost_pronote_state()["state"] == "unavailable"
