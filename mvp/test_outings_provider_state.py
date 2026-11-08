"""Provider queue status cannot be mistaken for a running collection."""
from types import SimpleNamespace
from . import outings
from .test_outings import store
from .test_outings_holo_integration import job_for

class StopAfterPoll:
    stopped = False
    def is_set(self): return self.stopped
    def wait(self, timeout): self.stopped = True


def test_queued_provider_leaves_all_tools_uncalled(store, monkeypatch):
    job = job_for(store, monkeypatch)
    client = SimpleNamespace(sessions=SimpleNamespace(get_session_status=lambda _: {'status':'queued'}))
    outings._follow_h_session(client, 'provider-queued', job, StopAfterPoll())
    assert job['agent']['provider_status'] == 'queued'
    assert job['agent']['status'] == 'provider_queued'
    assert all(t['status'] == 'pending' for t in job['tasks'])
    assert job['executions'] == job['tool_calls'] == []


def test_provider_poll_cannot_mutate_finished_job(store, monkeypatch):
    job = job_for(store, monkeypatch)
    job['status'] = 'ready'
    client = SimpleNamespace(sessions=SimpleNamespace(get_session_status=lambda _: {'status':'queued'}))
    outings._follow_h_session(client, 'provider-finished', job, StopAfterPoll())
    assert 'provider_status' not in job['agent']
