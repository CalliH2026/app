"""Native export/open contracts using explicit fake DB, FSFB and viewer handles."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas

from mvp.native import document_service as service
from mvp.native.native_documents import (
    AttachmentRegistry, DocumentOpenDetector, EXPORT_METHOD, METHOD,
    archive_native_exports, digest, exported_registry, preview_open_file, read_export_snapshot,
)


GUID = '{11111111-2222-3333-4444-555555555555}'


def prepared(tmp_path):
    drive = tmp_path / 'bottle/drive_c'
    originals = drive / 'H-Demo/Pieces'
    originals.mkdir(parents=True)
    database = drive / 'H-Demo/Base_test.not'
    database.write_bytes(b'explicit test database')
    temp = drive / 'users/crossover/Temp' / GUID
    temp.mkdir(parents=True)
    storage = (drive / 'ProgramData/IndexEducation/PRONOTE/MONOPOSTE'
               / 'VERSION 2026-0/FR/DocJointEleve/123')
    storage.mkdir(parents=True)
    sources = []
    for role in ('copy', 'rubric', 'instructions'):
        original = originals / (role + '.pdf')
        canvas = Canvas(str(original))
        canvas.drawString(72, 720, f'Fictional native test: {role}, Pythagore, 3/6.')
        canvas.save()
        data = original.read_bytes()
        container = storage / role
        container.write_bytes(b'FSFB\x02\0\0\0' + hashlib.sha256(data).digest()
                             + hashlib.md5(data).digest() + b'test fixture envelope')
        sources.append({'id': role, 'role': role, 'path': str(original),
            'display_name': original.name, 'sha256': digest(original),
            'provenance': {'kind': 'imported_demo_document',
                'import_evidence': {'method': 'native_ui', 'observed_at': 'test-only'},
                'native_storage': {'path': str(container), 'file_sha256': digest(container)}}})
    manifest = {'attachment_roots': [str(originals)], 'sources': sources,
                'database_path': str(database), 'base_id': '123',
                'native_context_id': 'explicit-test-native', 'dossier_id': 'test-dossier'}
    main = {'pid': 312, 'hwnd': '12', 'process': 'PRONOTE Monoposte.exe',
            'title': 'PRONOTE [Base_test.not]', 'image_path': r'C:\H-Demo\PRONOTE.exe'}
    snapshot = {'method': METHOD, 'observed_at': '2026-11-07T15:00:00+00:00',
                'windows': [main]}
    return manifest, AttachmentRegistry(manifest), temp, snapshot


def export_all(manifest, directory):
    for record in manifest['sources']:
        (directory / record['display_name']).write_bytes(Path(record['path']).read_bytes())


def viewer(path):
    return {'viewer_pid': 42, 'viewer_process': 'Preview',
            'viewer_bundle_id': 'com.apple.Preview', 'viewer_open_path': str(path),
            'viewer_executable': '/System/Applications/Preview.app/Contents/MacOS/Preview'}


def test_file_creation_alone_is_not_an_opening_and_real_handle_reads_exported_bytes(tmp_path):
    manifest, registry, temp, snapshot = prepared(tmp_path)
    detector = DocumentOpenDetector(tmp_path / 'events.json')
    detector.observe_exports(snapshot, read_export_snapshot(registry, viewer=lambda _: None), registry)
    export_all(manifest, temp)
    assert detector.observe_exports(snapshot, read_export_snapshot(registry, viewer=lambda _: None), registry) == []
    event, = detector.observe_exports(snapshot, read_export_snapshot(registry, viewer=viewer), registry)
    assert event['trigger']['evidence']['method'] == EXPORT_METHOD
    assert event['trigger']['source_locator'] == str(temp / 'copy.pdf')
    assert all(source['provenance']['kind'] == 'native_export' for source in event['sources'])
    assert all(source['provenance']['import_origin_kind'] == 'imported_demo_document'
               for source in event['sources'])
    assert all(source['provenance']['imported_into_native'] for source in event['sources'])
    assert all(Path(source['provenance']['path']).parent == temp for source in event['sources'])
    from mvp.native_pipeline import NativeCase
    NativeCase.model_validate(event)
    # Closing and reopening the same underlying copy cannot launch another job.
    detector.observe_exports(snapshot, read_export_snapshot(registry, viewer=lambda _: None), registry)
    assert detector.observe_exports(snapshot, read_export_snapshot(registry, viewer=viewer), registry) == []


def test_first_existing_open_export_is_only_baseline(tmp_path):
    manifest, registry, temp, snapshot = prepared(tmp_path)
    export_all(manifest, temp)
    detector = DocumentOpenDetector()
    actual = read_export_snapshot(registry, viewer=viewer)
    assert detector.observe_exports(snapshot, actual, registry) == []
    assert detector.observe_exports(snapshot, actual, registry) == []


def test_wrong_named_bytes_and_symlink_export_are_ignored(tmp_path):
    manifest, registry, temp, _ = prepared(tmp_path)
    (temp / 'copy.pdf').write_bytes(b'wrong copy bytes')
    assert read_export_snapshot(registry, viewer=viewer)['exports'] == []
    (temp / 'copy.pdf').unlink()
    (temp / 'copy.pdf').symlink_to(manifest['sources'][0]['path'])
    assert read_export_snapshot(registry, viewer=viewer)['exports'] == []


def test_container_must_still_match_actual_native_import(tmp_path):
    manifest, registry, temp, _ = prepared(tmp_path)
    export_all(manifest, temp)
    storage = Path(manifest['sources'][0]['provenance']['native_storage']['path'])
    storage.write_bytes(storage.read_bytes() + b'changed after import')
    with pytest.raises(ValueError, match='registered native storage'):
        read_export_snapshot(registry, viewer=viewer)


def test_unrelated_viewer_handle_or_wrong_base_cannot_trigger(tmp_path):
    manifest, registry, temp, snapshot = prepared(tmp_path)
    export_all(manifest, temp)
    detector = DocumentOpenDetector()
    detector.observe_exports(snapshot, {'method': EXPORT_METHOD, 'exports': []}, registry)
    actual = read_export_snapshot(registry, viewer=viewer)
    bad = copy.deepcopy(actual)
    next(item for item in bad['exports'] if item['role'] == 'copy')['viewer']['viewer_open_path'] = str(temp / 'rubric.pdf')
    with pytest.raises(ValueError, match="Preview's exact"):
        detector.observe_exports(snapshot, bad, registry)
    wrong = {**snapshot, 'windows': [{**snapshot['windows'][0], 'title': 'Other.not'}]}
    with pytest.raises(ValueError, match='base to be open'):
        detector.observe_exports(wrong, actual, registry)


def test_export_queue_failure_retries_without_consuming_opening(tmp_path, monkeypatch):
    manifest, registry, temp, snapshot = prepared(tmp_path)
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(service, 'STATE', tmp_path / 'observer.json')
    detector = DocumentOpenDetector(tmp_path / 'events.json')
    no_exports = lambda _: {'method': EXPORT_METHOD, 'exports': [], 'observed_at': snapshot['observed_at']}
    service.poll_once(detector, path, read=lambda: snapshot, read_exports=no_exports,
                      enqueue=lambda _: {'id': 'unexpected'})
    export_all(manifest, temp)
    opened = lambda _: read_export_snapshot(registry, viewer=viewer)
    def unavailable(_):
        raise RuntimeError('queue unavailable')
    with pytest.raises(RuntimeError, match='queue unavailable'):
        service.poll_once(detector, path, read=lambda: snapshot, read_exports=opened, enqueue=unavailable)
    assert not detector.state_file.exists()
    jobs = service.poll_once(detector, path, read=lambda: snapshot, read_exports=opened,
                             enqueue=lambda _: {'id': 'accepted-real-export-test'})
    assert jobs[0]['id'] == 'accepted-real-export-test'
    assert service.poll_once(detector, path, read=lambda: snapshot, read_exports=opened,
                              enqueue=lambda _: pytest.fail('duplicate opening')) == []


def test_lsof_proof_requires_exact_file_and_system_preview_executable(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path = tmp_path / 'copy.pdf'
    path.write_bytes(b'test-only')
    def run(args, **kwargs):
        if args[0] == '/usr/sbin/lsof':
            return SimpleNamespace(returncode=0, stdout=f'p42\ncPreview\nftxt\nn{path}\n')
        return SimpleNamespace(stdout='/System/Applications/Preview.app/Contents/MacOS/Preview\n')
    monkeypatch.setattr('mvp.native.native_documents.subprocess.run', run)
    assert preview_open_file(path)['viewer_pid'] == 42
    def impostor(args, **kwargs):
        return (run(args, **kwargs) if args[0] == '/usr/sbin/lsof'
                else SimpleNamespace(stdout='/tmp/Preview\n'))
    monkeypatch.setattr('mvp.native.native_documents.subprocess.run', impostor)
    assert preview_open_file(path) is None


def archived_case(tmp_path, monkeypatch):
    manifest, registry, temp, snapshot = prepared(tmp_path)
    monkeypatch.setattr('mvp.native.native_documents.NATIVE_EXPORT_CACHE', tmp_path / 'native-export-cache')
    export_all(manifest, temp)
    actual = read_export_snapshot(registry, viewer=viewer)
    active = next(item for item in actual['exports'] if item['role'] == 'copy')
    decoded = exported_registry(registry, actual['exports'], active, actual['observed_at'])
    archived = archive_native_exports(decoded)
    # Simulate PRONOTE's cleanup between launches. No cache setup emits a job.
    import shutil
    shutil.rmtree(temp)
    return archived, AttachmentRegistry(archived), temp, snapshot


def test_copy_only_new_export_uses_verified_archived_companions_after_temp_cleanup(tmp_path, monkeypatch):
    archived, registry, previous_temp, snapshot = archived_case(tmp_path, monkeypatch)
    assert len(registry.sources('after-native-restart')) == 3
    detector = DocumentOpenDetector()
    detector.observe_exports(snapshot, read_export_snapshot(registry, viewer=viewer), registry)
    new_temp = previous_temp.parent / '{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}'
    new_temp.mkdir()
    original_copy = next(record for record in archived['sources'] if record['role'] == 'copy')
    active_path = new_temp / original_copy['display_name']
    active_path.write_bytes(Path(original_copy['path']).read_bytes())
    exported = read_export_snapshot(registry, viewer=viewer)
    assert [item['role'] for item in exported['exports']] == ['copy']
    event, = detector.observe_exports(snapshot, exported, registry)
    roles = {source['role']: source for source in event['sources']}
    assert roles['copy']['provenance']['path'] == str(active_path)
    assert 'archived_from' not in roles['copy']['provenance']
    assert roles['rubric']['provenance']['archived_from']['path'].startswith(str(previous_temp))
    assert Path(roles['rubric']['provenance']['path']).parent.name == archived['native_context_id']
    from mvp.native_pipeline import NativeCase
    NativeCase.model_validate(event)


def test_archive_helper_rejects_prepared_originals_and_does_not_mutate_registry(tmp_path, monkeypatch):
    manifest, registry, _, _ = prepared(tmp_path)
    monkeypatch.setattr('mvp.native.native_documents.NATIVE_EXPORT_CACHE', tmp_path / 'native-export-cache')
    before = copy.deepcopy(manifest)
    with pytest.raises(ValueError, match='Only actual decoded native Temp exports'):
        archive_native_exports(registry)
    assert manifest == before
    assert not (tmp_path / 'native-export-cache').exists()


@pytest.mark.parametrize('damage', ['missing', 'unverified', 'stale'])
def test_invalid_archived_companion_cannot_prepare_on_copy_only_open(tmp_path, monkeypatch, damage):
    archived, registry, previous_temp, snapshot = archived_case(tmp_path, monkeypatch)
    rubric = next(record for record in archived['sources'] if record['role'] == 'rubric')
    if damage == 'missing':
        Path(rubric['path']).unlink()
    elif damage == 'unverified':
        del rubric['provenance']['archived_from']
        del rubric['provenance']['archive_evidence']
    else:
        Path(rubric['path']).write_bytes(b'%PDF-stale different file')
    new_temp = previous_temp.parent / '{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}'
    new_temp.mkdir()
    active = next(record for record in archived['sources'] if record['role'] == 'copy')
    (new_temp / active['display_name']).write_bytes(Path(active['path']).read_bytes())
    detector = DocumentOpenDetector()
    detector.observe_exports(snapshot, {'method': EXPORT_METHOD, 'exports': []}, registry)
    with pytest.raises((ValueError, FileNotFoundError)):
        detector.observe_exports(snapshot, read_export_snapshot(registry, viewer=viewer), registry)
    assert detector.emitted == set()


def test_archived_files_never_create_a_copy_open_event(tmp_path, monkeypatch):
    _, registry, _, snapshot = archived_case(tmp_path, monkeypatch)
    detector = DocumentOpenDetector()
    for _ in range(2):
        assert detector.observe_exports(snapshot, read_export_snapshot(registry, viewer=viewer), registry) == []
