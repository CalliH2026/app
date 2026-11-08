"""Read-only macOS foreground guard for the isolated PRONOTE example.

A Wine HWND can remain foreground within its bottle while another macOS app is
actually on screen. The native desktop driver must check the macOS application,
not infer desktop readiness from Win32 focus alone. No permission is requested,
window raised, screenshot taken, or input sent by this module.
"""
from datetime import datetime, timezone
import sys

EXPECTED_BUNDLE_ID = "local.hcompany.pronote-demo"


def _frontmost_application_info():
    from AppKit import NSWorkspace

    application = NSWorkspace.sharedWorkspace().frontmostApplication()
    if application is None:
        return None
    bundle_url = application.bundleURL()
    return {
        "bundle_id": str(application.bundleIdentifier() or ""),
        "name": str(application.localizedName() or ""),
        "pid": int(application.processIdentifier()),
        "application_path": str(bundle_url.path()) if bundle_url else None,
    }


def _pronote_window_title(pid):
    # Read a title only after verifying the exact authorised bundle. This avoids
    # inspecting a browser or messaging window when the guard is blocked.
    from ApplicationServices import (
        AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
        kAXFocusedWindowAttribute, kAXMainWindowAttribute, kAXTitleAttribute,
    )

    application = AXUIElementCreateApplication(pid)
    for attribute in (kAXFocusedWindowAttribute, kAXMainWindowAttribute):
        error, window = AXUIElementCopyAttributeValue(application, attribute, None)
        if error or window is None:
            continue
        error, title = AXUIElementCopyAttributeValue(window, kAXTitleAttribute, None)
        if not error and title:
            return str(title)
    return None


def frontmost_pronote_state():
    """Return an authoritative Mac-app guard; Win32 readiness stays separate.

    `ready` requires the actual frontmost macOS bundle to be this project's
    isolated official example launcher. The optional title is diagnostic only:
    callers must also retain their own Base Exemple/Win32 check before a run.
    """
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "method": "NSWorkspace.frontmostApplication",
        "expected_bundle_id": EXPECTED_BUNDLE_ID,
        "matches_expected_bundle": False,
        "state": "unavailable",
        "window_title": None,
    }
    if sys.platform != "darwin":
        return {**result, "message": "Le contrôle de premier plan macOS est indisponible sur ce système."}
    try:
        application = _frontmost_application_info()
    except Exception as error:
        return {**result, "error_type": type(error).__name__,
                "message": "Impossible de vérifier l’application au premier plan sur macOS."}
    if application is None:
        return {**result, "state": "blocked",
                "message": "Aucune application macOS au premier plan n’est observée."}
    result.update(
        frontmost_bundle_id=application["bundle_id"],
        frontmost_app_name=application["name"],
        frontmost_pid=application["pid"],
        frontmost_application_path=application["application_path"],
    )
    if application["bundle_id"] != EXPECTED_BUNDLE_ID:
        return {**result, "state": "blocked",
                "message": "Affichez PRONOTE Démo locale au premier plan sur le Mac avant de lancer H."}
    result.update(state="ready", matches_expected_bundle=True,
                  message="PRONOTE Démo locale est l’application au premier plan sur macOS.")
    try:
        result["window_title"] = _pronote_window_title(application["pid"])
    except Exception:
        # A title may be inaccessible without AX. The app identity is still a
        # positive read from NSWorkspace; the caller separately checks Win32.
        result["window_title"] = None
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(frontmost_pronote_state(), ensure_ascii=False, indent=2))
