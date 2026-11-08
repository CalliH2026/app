"""Calli addition: keep the vendored modules' state out of the source tree during their tests."""
import os
import tempfile

os.environ.setdefault("PRONOTE_DATA_DIR", tempfile.mkdtemp(prefix="h-parallel-tests-"))
