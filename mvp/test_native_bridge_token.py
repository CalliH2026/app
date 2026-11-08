import importlib
import sys


def test_import_creates_no_token_and_first_use_does(tmp_path, monkeypatch):
    from . import native_bridge
    token = tmp_path / 'credentials' / 'pronote-bridge-token'
    monkeypatch.setattr(native_bridge, 'TOKEN_FILE', token)
    sys.modules.pop(native_bridge.__name__)
    try:
        reloaded = importlib.import_module(native_bridge.__name__)
        monkeypatch.setattr(reloaded, 'TOKEN_FILE', token)
        assert not token.exists()
        value = reloaded.bridge_token()
        assert token.read_text() == value and len(value) >= 32 and token.stat().st_mode & 0o777 == 0o600
        assert reloaded.bridge_token() == value
    finally:
        sys.modules[native_bridge.__name__] = native_bridge
