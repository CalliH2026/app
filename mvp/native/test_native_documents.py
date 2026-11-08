"""Opening-event/provenance contracts. All windows below are test doubles."""
import copy
import pytest

from mvp.native.native_documents import AttachmentRegistry, DocumentOpenDetector, METHOD, digest


def scenario(tmp_path):
    files = {"copy": "BC = 5 cm. Annotation : justifier.",
             "rubric": "Justification : 1 point. Calcul : 2 points."}
    sources = []
    for role, text in files.items():
        path = tmp_path / (role + ".txt")
        path.write_text(text)
        sources.append({"id": role, "role": role, "path": str(path),
            "display_name": path.name, "provenance": {
                "kind": "imported_demo_document",
                "import_evidence": {"method": "native_ui", "observed_at": "test-only"}}})
    audio = tmp_path / "parent.wav"
    audio.write_bytes(b"test-audio")
    database = tmp_path / 'Base_test.not'
    database.write_bytes(b'test-double-database')
    manifest = {"attachment_roots": [str(tmp_path)], "native_context_id": "example-only",
                "database_path": str(database), "dossier_id": "student-copy-test-only",
                "sources": sources, "parent_audio": {"path": str(audio),
                "provenance": {"kind": "native_document"}}}
    return manifest, AttachmentRegistry(manifest)


def snapshot(*windows):
    return {"method": METHOD, "observed_at": "test-observation", "windows": list(windows)}


def viewer():
    return {"pid": 100, "hwnd": "12", "owner_hwnd": "10", "class": "TPdfViewer",
            "image_path": r"C:\H-Demo\PRONOTE\PRONOTE Monoposte.exe", "parent_pid": 10,
            "process": "PRONOTE Monoposte.exe", "title": "copy.txt — PRONOTE"}


def test_baseline_and_main_grid_never_trigger(tmp_path):
    _, registry = scenario(tmp_path)
    detector = DocumentOpenDetector()
    assert detector.observe(snapshot(viewer()), registry) == []
    assert detector.observe(snapshot(), registry) == []
    main = {**viewer(), "class": "TEcranPrincipal",
            "title": "PRONOTE [Base Exemple.not]", "controls": [{"text": "copy.txt"}]}
    assert detector.observe(snapshot(main), registry) == []
    assert detector.observe(snapshot({**viewer(), "title": "Ouvrir"}), registry) == []


def test_real_bytes_event_and_persistent_dedup(tmp_path):
    manifest, registry = scenario(tmp_path)
    state = tmp_path / "events.json"
    detector = DocumentOpenDetector(state)
    detector.observe(snapshot(), registry)
    event, = detector.observe(snapshot(viewer()), registry)
    assert event["trigger"]["type"] == "copy_opened"
    assert event["trigger"]["evidence"]["window_title"] == viewer()["title"]
    assert event["sources"][0]["text"] == "BC = 5 cm. Annotation : justifier."
    assert event["sources"][0]["sha256"] == digest(tmp_path / "copy.txt")
    assert event["sources"][0]["provenance"]["kind"] == "imported_demo_document"
    from mvp.native_pipeline import NativeCase
    case = NativeCase.model_validate(event)
    assert case.context["state"] == "observed"
    assert case.trigger.source_locator == case.sources[0].provenance.locator
    detector.observe(snapshot(), registry)
    assert detector.observe(snapshot(viewer()), registry) == []
    restarted = DocumentOpenDetector(state)
    restarted.observe(snapshot(), registry)
    assert restarted.observe(snapshot(viewer()), registry) == []
    # A genuinely different parent question can start a new job on reopening.
    restarted.observe(snapshot(), registry)
    (tmp_path / "parent.wav").write_bytes(b"different-question")
    changed, = restarted.observe(snapshot(viewer()), registry)
    assert changed["trigger"]["event_id"] != event["trigger"]["event_id"]


def test_unverified_or_changed_import_rejected(tmp_path):
    manifest, registry = scenario(tmp_path)
    unverified = copy.deepcopy(manifest)
    del unverified["sources"][0]["provenance"]["import_evidence"]
    with pytest.raises(ValueError, match="observed native import"):
        AttachmentRegistry(unverified).sources("test")
    manifest["sources"][0]["sha256"] = digest(tmp_path / "copy.txt")
    (tmp_path / "copy.txt").write_text("modified")
    with pytest.raises(ValueError, match="changed since registration"):
        registry.sources("test")


def test_symlink_escape_rejected(tmp_path):
    native = tmp_path / "native"
    native.mkdir()
    manifest, _ = scenario(native)
    outside = tmp_path / "outside.txt"
    outside.write_text("Unrelated data")
    (native / "copy.txt").unlink()
    (native / "copy.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="outside the registered native roots"):
        AttachmentRegistry(manifest).sources("test")


def test_temporary_read_failure_does_not_consume_opening(tmp_path):
    manifest, registry = scenario(tmp_path)
    detector = DocumentOpenDetector()
    detector.observe(snapshot(), registry)
    manifest["sources"][0]["sha256"] = "wrong"
    with pytest.raises(ValueError, match="changed since registration"):
        detector.observe(snapshot(viewer()), registry)
    del manifest["sources"][0]["sha256"]
    event, = detector.observe(snapshot(viewer()), registry)
    assert event["trigger"]["document_id"] == "copy"


def test_external_test_audio_stays_external(tmp_path):
    manifest, _ = scenario(tmp_path)
    manifest['parent_audio']['provenance']['kind'] = 'attached_test_dossier'
    registry = AttachmentRegistry(manifest)
    assert registry.audio('test')['provenance']['imported_into_native'] is False
    manifest['sources'][0]['provenance']['kind'] = 'attached_test_dossier'
    with pytest.raises(ValueError, match='explicit source provenance'):
        AttachmentRegistry(manifest).sources('test')


def test_opening_without_parent_audio_has_no_synthetic_vocal(tmp_path):
    manifest, _ = scenario(tmp_path)
    del manifest['parent_audio']
    detector = DocumentOpenDetector()
    registry = AttachmentRegistry(manifest)
    detector.observe(snapshot(), registry)
    event, = detector.observe(snapshot(viewer()), registry)
    assert event['parent_audio'] is None
    from mvp.native_pipeline import NativeCase
    assert NativeCase.model_validate(event).parent_audio is None


def test_unaccepted_event_is_not_consumed(tmp_path):
    _, registry = scenario(tmp_path)
    detector = DocumentOpenDetector(tmp_path / 'events.json')
    detector.observe(snapshot(), registry)
    events = detector.observe(snapshot(viewer()), registry, commit=False)
    assert detector.observe(snapshot(viewer()), registry, commit=False) == events
    assert not detector.state_file.exists()
    detector.acknowledge(events)
    assert detector.observe(snapshot(viewer()), registry) == []
