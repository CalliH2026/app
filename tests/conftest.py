"""Shared test setup: no test may reach the network."""

from __future__ import annotations

import socket

import pytest


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args, **kwargs):
        raise NetworkBlocked("tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(scope="session")
def h_parallel_dir(tmp_path_factory):
    """One state directory per test process: the vendored H Parallel modules read it once, at first import."""
    return tmp_path_factory.mktemp("h-parallel")
