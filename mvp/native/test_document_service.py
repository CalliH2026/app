"""Native observer contracts. UI observations here are explicit test doubles."""
import json
import pytest

from mvp.native import document_service as service
from mvp.native.native_documents import AttachmentRegistry, DocumentOpenDetector
from mvp.native.test_native_documents import scenario, snapshot, viewer


def setup(tmp_path, monkeypatch):
    manifest, registry = scenario(tmp_path)
    monkeypatch.setattr(service, 'STATE', tmp_path / 'observer.json')
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    main = {**viewer(), 'hwnd': '10', 'title': 'PRONOTE [Base_test.not]'}
    return path, main


def test_missing_manifest_does_not_read_desktop_or_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'STATE', tmp_path / 'state.json')
    def unexpected():
        raise AssertionError('No native read before an import manifest exists')
    assert service.poll_once(DocumentOpenDetector(), tmp_path / 'absent.json', read=unexpected) == []
    assert service.status()['state'] == 'waiting_for_import'
    assert service.status()['desktop_access'] is False


def test_actual_new_viewer_enqueues_once_without_prompt(tmp_path, monkeypatch):
    path, main = setup(tmp_path, monkeypatch)
    detector, jobs = DocumentOpenDetector(), []
    def enqueue(payload):
        from mvp.native_pipeline import NativeCase
        NativeCase.model_validate(payload)
        jobs.append(payload)
        return {'id': 'native-test-job'}
    service.poll_once(detector, path, read=lambda: snapshot(main), enqueue=enqueue)
    service.poll_once(detector, path, read=lambda: snapshot(main, viewer()), enqueue=enqueue)
    service.poll_once(detector, path, read=lambda: snapshot(main, viewer()), enqueue=enqueue)
    assert len(jobs) == 1
    assert service.status()['last_job_id'] == 'native-test-job'


def test_wrong_open_base_blocks_the_observation(tmp_path, monkeypatch):
    path, main = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='base ouverte'):
        service.poll_once(DocumentOpenDetector(), path, read=lambda: snapshot({**main, 'title': 'Other.not'}))


def test_queue_failure_can_retry_same_real_opening(tmp_path, monkeypatch):
    path, main = setup(tmp_path, monkeypatch)
    detector = DocumentOpenDetector(tmp_path / 'events.json')
    service.poll_once(detector, path, read=lambda: snapshot(main), enqueue=lambda _: None)
    def unavailable(_):
        raise ValueError('queue temporarily unavailable')
    with pytest.raises(ValueError, match='temporarily unavailable'):
        service.poll_once(detector, path, read=lambda: snapshot(main, viewer()), enqueue=unavailable)
    jobs = service.poll_once(detector, path, read=lambda: snapshot(main, viewer()), enqueue=lambda _: {'id': 'retry'})
    assert jobs[0]['id'] == 'retry'
