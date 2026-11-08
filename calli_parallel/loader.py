"""Import the vendored H Parallel modules with Calli's state directory and credential names.

Upstream reads PRONOTE_DATA_DIR once, at import, and expects H_COMPANY_API_KEY / DEVIN_API_KEY. Calli's
environment uses HAI_API_KEY, and the root operator keeps the Devin key in DEVIN_API, so both are aliased in
this process only (never written to disk or printed).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

PACKAGE = "vendor.h_parallel"
ALIASES = (("H_COMPANY_API_KEY", "HAI_API_KEY"), ("DEVIN_API_KEY", "DEVIN_API"))
_loaded: SimpleNamespace | None = None


class AlreadyLoaded(RuntimeError):
    pass


def alias_credentials(environ: dict[str, str] | os._Environ = os.environ) -> list[str]:
    """Set the upstream names from Calli's names when only the latter exist; return the names set."""
    done = []
    for target, source in ALIASES:
        if not environ.get(target) and environ.get(source):
            environ[target] = environ[source]
            done.append(target)
    return done


def upstream(data_dir: Path | None = None) -> SimpleNamespace:
    """The vendored modules, imported once per process with PRONOTE_DATA_DIR = data_dir."""
    global _loaded
    if _loaded is not None:
        if data_dir is not None and Path(data_dir).resolve() != _loaded.data_dir:
            raise AlreadyLoaded(f"H Parallel already loaded with {_loaded.data_dir}; one state directory per process")
        return _loaded
    if data_dir is None:
        raise ValueError("an H Parallel state directory is required (--parallel-dir)")
    if f"{PACKAGE}.engine" in sys.modules:
        raise AlreadyLoaded("vendor.h_parallel.engine was imported before the loader set its state directory")
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PRONOTE_DATA_DIR"] = str(data_dir)
    alias_credentials()
    mods = {name: importlib.import_module(f"{PACKAGE}.{name}")
            for name in ("engine", "preparation_tools", "practice", "outings", "tool_calls")}
    _loaded = SimpleNamespace(data_dir=data_dir, **mods)
    return _loaded


def configured() -> dict[str, bool]:
    """Which providers have a credential in this process (names only, never values)."""
    alias_credentials()
    return {"h": bool(os.environ.get("H_COMPANY_API_KEY")), "gladia": bool(os.environ.get("GLADIA_API_KEY")),
            "linkup": bool(os.environ.get("LINKUP_API_KEY")),
            "devin": bool(os.environ.get("DEVIN_API_KEY")) and bool(os.environ.get("DEVIN_ORG_ID"))}
