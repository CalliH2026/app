"""Evidence classification and refusal tests; no desktop input or paid API."""
from types import SimpleNamespace
from copy import deepcopy
import json
import plistlib
import pytest

from mvp import recordings


def make_app(path, executable, name, identifier):
    main = path / 'Contents/MacOS' / executable
    main.parent.mkdir(parents=True, exist_ok=True)
    main.write_bytes(b'test fixture, never executed')
    (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({
        'CFBundleExecutable':executable, 'CFBundleName':name, 'CFBundleIdentifier':identifier}))
    return main


def test_host_discovery_prefers_outer_actual_app_over_python_and_embedded_cli(tmp_path):
    python = make_app(tmp_path/'Python.app', 'Python', 'Python', 'org.python.python')
    outer = tmp_path/'ChatGPT.app'
    host = make_app(outer, 'ChatGPT', 'ChatGPT', 'com.example.host')
    nested = make_app(outer/'Contents/Resources/CodexCLI.app', 'codex', 'Codex CLI', 'com.example.cli')
    chain = {300:(200,str(python)), 200:(100,str(nested)), 100:(1,str(host))}
    visited = []
    def read(pid):
        visited.append(pid)
        return chain[pid]
    result = recordings.discover_host_application(pid=300, read_process=read)
    assert result == {'path':str(outer), 'name':'ChatGPT', 'bundle_identifier':'com.example.host'}
    assert visited == [300, 200, 100]


def test_host_discovery_never_invents_a_nonexistent_app(tmp_path):
    missing = tmp_path/'Missing.app/Contents/MacOS/Missing'
    result = recordings.discover_host_application(pid=300,
        read_process=lambda pid: (1, str(missing)))
    assert result is None


def test_process_discovery_preserves_spaces_without_reading_arguments(monkeypatch):
    calls = []
    def read(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout='  100 /Applications/Studio Editor.app/Contents/MacOS/Editor\n')
    monkeypatch.setattr(recordings.subprocess, 'run', read)
    assert recordings._process_parent_and_executable(300) == (
        100, '/Applications/Studio Editor.app/Contents/MacOS/Editor')
    assert calls == [['ps', '-p', '300', '-o', 'ppid=,comm=']]


def test_preflight_exposes_host_guidance_without_claiming_authorization(monkeypatch, tmp_path):
    host_path = tmp_path/'ChatGPT.app'
    make_app(host_path, 'ChatGPT', 'ChatGPT', 'com.example.host')
    monkeypatch.setattr(recordings, 'discover_host_application', lambda: {
        'path':str(host_path), 'name':'ChatGPT', 'bundle_identifier':'com.example.host'})
    monkeypatch.setattr(recordings.sys, 'platform', 'darwin')
    monkeypatch.setattr(recordings.importlib.util, 'find_spec', lambda name: object())
    monkeypatch.setitem(recordings.sys.modules, 'ApplicationServices',
                        SimpleNamespace(AXIsProcessTrusted=lambda: False))
    monkeypatch.setitem(recordings.sys.modules, 'Quartz',
                        SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: False))
    result = recordings.desktop_preflight()
    assert result['host_application_name'] == result['authorization_target_name'] == 'ChatGPT'
    assert result['host_application_path'] == result['authorization_target_path'] == str(host_path)
    assert result['authorization_target_basis'] == 'host_process_ancestry'
    assert result['authorization_attribution_verified'] is False
    assert result['state'] == 'blocked'
    assert result['missing'] == ['accessibility', 'screen_recording']


def test_blocked_preflight_never_starts_h(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(recordings, "desktop_preflight", lambda: {
        "state": "blocked", "missing": ["accessibility", "screen_recording"], "message": "Denied"})
    def forbidden():
        raise AssertionError("H must not run before its permission preflight passes")
    monkeypatch.setattr(recordings, "_client", forbidden)
    value = recordings.start_native_session(desktop_prepared=True)
    assert value["state"] == "blocked"
    assert not value["native_video_available"]
    assert "session_id" not in value


def test_agent_view_is_read_from_provider_and_native_claim_is_explicit():
    record = {"id": "real-record-id", "request": {"agent": {"environments": [
        {"id": "local", "kind": "web", "host": "user_device", "mode": {"type": "text"}}]}},
        "status": {"status": "completed"}, "agent_view_url": None}
    class Session:
        def model_dump(self, **kwargs):
            return record
    client = SimpleNamespace(sessions=SimpleNamespace(get_session=lambda _: Session()))
    evidence = recordings.session_evidence(client, "real-record-id")
    assert evidence["kind"] == "h_browser_session"
    assert evidence["agent_view_url"] is None  # No guessed URL is manufactured.
    assert evidence["native_pronote_recording_verified"] is False
    record["status"]["status"] = "interrupted"
    record["latest_answer"] = "Réponse déjà reçue"
    evidence = recordings.session_evidence(client, "real-record-id")
    assert evidence["status"] == evidence["provider_status"] == "interrupted"
    assert evidence["answer_available"] is True
    assert "réponse est conservée" in evidence["detail"]
    record["request"]["agent"]["environments"][0]["kind"] = "desktop"
    record["agent_view_url"] = "https://platform.hcompany.ai/agents/sessions/real-record-id"
    evidence = recordings.session_evidence(client, "real-record-id")
    assert evidence["kind"] == "h_desktop_session"
    assert evidence["agent_view_url"] == record["agent_view_url"]
    assert evidence["native_pronote_recording_verified"] is False


def test_missing_or_invalid_video_is_never_exposed(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings, "DATA", tmp_path)
    monkeypatch.setattr(recordings, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(recordings, "status", lambda: {
        "state": "blocked", "preflight": {"state": "blocked"}})
    legacy = tmp_path / "recordings/legacy-web"
    legacy.mkdir(parents=True)
    (legacy / "state.json").write_text(json.dumps({"status": "completed"}))
    (legacy / "capture.mp4").write_bytes(b"not a video" * 200)
    records = recordings.get_recordings()
    assert all("video_url" not in item for item in records)
    assert next(item for item in records if item["id"] == "legacy-web")["kind"] == "h_web_session"


@pytest.mark.parametrize('provider_state', ['idle', 'running', 'queued', 'pending', 'completed'])
def test_session_cleanup_releases_only_idle(provider_state):
    from mvp import engine
    class Session:
        id = 'original-session'
        cancelled = 0
        def status(self):
            return SimpleNamespace(status='interrupted' if self.cancelled else provider_state)
        def cancel(self):
            self.cancelled += 1
    session = Session()
    cleanup = engine.finish_session_safely(session)
    assert session.cancelled == int(provider_state == 'idle')
    assert cleanup['provider_status_before'] == provider_state
    assert cleanup['release_requested'] is (provider_state == 'idle')
    if provider_state == 'idle':
        assert cleanup['provider_status_after'] == 'interrupted'


def test_original_navigation_cleanup_preserves_successful_job(monkeypatch):
    from mvp import engine, preparation_tools
    from mvp.preparation_tools import PreparedCapsule
    from mvp.tool_calls import summarize_tool_calls
    class Session:
        id = 'original-session'
        cancelled = 0
        answer = None
        def wait_for_completion(self, **kwargs):
            return SimpleNamespace(status='idle', answer=self.answer)
        def status(self):
            return SimpleNamespace(status='interrupted' if self.cancelled else 'idle')
        def cancel(self):
            self.cancelled += 1
    session = Session()
    class Client:
        def __init__(self, **kwargs):
            pass
        def start_session(self, **kwargs):
            assert kwargs['answer_schema'] is PreparedCapsule
            tools = {tool.__name__: tool for tool in kwargs['tools']}
            assert len(tools) == 6
            tools['get_evidence_catalog']([])
            tools['transcribe_audio']()
            tools['search_resources']('Pythagore justification', 'reference')
            tools['search_resources']('Pythagore exercice autonome', 'exercise')
            catalog = engine.quote_catalog(engine.FIXTURE['documents'])
            dossier = engine.offline_dossier('points')
            dossier['evidence'] = [
                {'claim': 'Le dossier contient cette preuve scolaire.',
                 'quote_id': next(key for key, value in catalog.items() if value['source_id'] == source_id)}
                for source_id in ('copie', 'bareme')]
            valid = json.loads(tools['validate_dossier'](engine.AgentDossier.model_validate(dossier)))
            rendered = json.loads(tools['render_capsule'](valid['validated_dossier_id']))
            tools['inspect_capsule'](rendered['render_id'])
            session.answer = PreparedCapsule(validated_dossier_id=valid['validated_dossier_id'],
                                             render_id=rendered['render_id'])
            return session
    class NoMonitor:
        def __init__(self, **kwargs):
            pass
        def start(self):
            pass
    monkeypatch.setattr(engine, 'Client', Client)
    monkeypatch.setattr(engine, 'key', lambda _: 'test')
    monkeypatch.setattr(engine, 'save', lambda _: None)
    monkeypatch.setattr(engine.threading, 'Thread', NoMonitor)
    monkeypatch.setattr(engine, 'transcribe', lambda _: {'job_id':'existing-transcript','text':'Pourquoi ces points ?'})
    monkeypatch.setattr(engine, 'search', lambda _: {'sources':[]})
    monkeypatch.setattr(engine, 'render', lambda *args: {'video':'/outputs/cleanup-test/capsule.mp4','duration':60})
    monkeypatch.setattr(preparation_tools, 'inspect_media', lambda *args: {
        'valid': True, 'duration_seconds': 60, 'has_video': True, 'has_audio': True,
        'subtitles_verified': True, 'requires_teacher_review': True})
    job = {'id':'cleanup-test','mode':'live','scenario':'points','events':[],
           'input_context':deepcopy(engine.FIXTURE)}
    engine._execute(job, 'http://localhost:8000')
    assert job['status'] == 'ready'
    assert job['dossier']['intent'] == 'points'
    assert job['session_id'] == 'original-session'
    assert summarize_tool_calls(job)['total'] == 7
    assert session.cancelled == 1
    assert job['session_cleanup']['release_requested'] is True


def test_repair_cleanup_returns_the_received_answer(monkeypatch):
    from mvp import engine
    answer = engine.offline_dossier('progress')
    class Session:
        id = 'repair-session'
        cancelled = 0
        def wait_for_completion(self, **kwargs):
            return SimpleNamespace(status='idle', answer=answer)
        def status(self):
            return SimpleNamespace(status='interrupted' if self.cancelled else 'idle')
        def cancel(self):
            self.cancelled += 1
    session = Session()
    class Client:
        def start_session(self, **kwargs):
            kwargs['tools'][0]()
            return session
    monkeypatch.setattr(engine, 'save', lambda _: None)
    job = {'id':'repair-test','events':[],'session_id':'original-session'}
    result = engine.repair_dossier(Client(), job, deepcopy(engine.FIXTURE),
        {'text':'Progression'}, {'sources':[]}, {'old':'answer'}, ValueError('Invalid quote'))
    assert result.answer is answer
    assert session.cancelled == 1
    assert job['session_id'] == 'original-session'
    assert job['validation_session_cleanup']['repair-session']['release_requested'] is True
