"""Functional H-tool workflow contracts, with no paid APIs or media rendering."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from hai_agents.tools import as_tools
import pytest

from . import engine, preparation_tools
from .preparation_tools import PreparationTools, inspect_media as inspect_media_actual
from .tool_calls import summarize_tool_calls


@pytest.fixture
def case(monkeypatch, tmp_path):
    context = deepcopy(engine.FIXTURE)
    job = {'id': 'tool-workflow', 'mode': 'live', 'scenario': 'points',
           'status': 'preparing', 'events': [], 'approved': False,
           'video_provider': 'local', 'input_context': context}
    calls = {'transcribe': [], 'search': [], 'render': [], 'inspect': []}
    monkeypatch.setattr(engine, 'DATA', tmp_path)

    def transcribe(path):
        calls['transcribe'].append(path)
        return {'provider': 'Gladia', 'job_id': 'gladia-test',
                'text': 'Pourquoi les points de rédaction manquent-ils ?', 'utterances': []}

    def search(topic):
        calls['search'].append(topic)
        exercise = 'exercice' in topic.casefold()
        return {'provider': 'Linkup', 'query': topic, 'sources': [
            {'id': 'web-1', 'title': 'Rédiger son raisonnement',
             'url': 'https://eduscol.education.fr/raisonnement#' + ('exercice' if exercise else 'reference'),
             'excerpt': 'Justifier le choix du théorème.', 'type': 'external'},
            {'id': 'web-2', 'title': 'Exercice' if exercise else 'Critères',
             'url': 'https://education.fr/' + ('exercice' if exercise else 'criteres'),
             'excerpt': 'Une ressource pédagogique.', 'type': 'external'},
        ]}

    def render(dossier, folder):
        calls['render'].append(deepcopy(dossier))
        return {'video': f'/outputs/{folder.name}/capsule.mp4',
                'captions': f'/outputs/{folder.name}/captions.vtt', 'duration': 82}

    def inspect(folder, output):
        calls['inspect'].append((folder, deepcopy(output)))
        return {'valid': True, 'duration_seconds': 82, 'has_video': True,
                'has_audio': True, 'subtitles_verified': True,
                'requires_teacher_review': True, 'video': output['video']}

    monkeypatch.setattr(engine, 'transcribe', transcribe)
    monkeypatch.setattr(engine, 'search', search)
    monkeypatch.setattr(engine, 'render', render)
    monkeypatch.setattr(preparation_tools, 'inspect_media', inspect)
    runtime = PreparationTools(job, context, tmp_path / 'audio.wav')
    return SimpleNamespace(job=job, context=context, runtime=runtime,
                           tools={tool.__name__: tool for tool in runtime.tools}, calls=calls)


def selected_dossier(runtime):
    dossier = engine.offline_dossier('points')
    identifiers = {source_id: next(key for key, value in runtime.catalog.items()
                                   if value['source_id'] == source_id)
                   for source_id in ('copie', 'bareme')}
    dossier['evidence'] = [
        {'claim': 'Le calcul est exact.', 'quote_id': identifiers['copie']},
        {'claim': 'La rédaction compte dans le barème.', 'quote_id': identifiers['bareme']},
    ]
    return engine.AgentDossier.model_validate(dossier)


def gather_evidence(case):
    case.tools['get_evidence_catalog'](['copie', 'bareme', 'consigne', 'methode'])
    case.tools['transcribe_audio']()
    case.tools['search_resources']('Pythagore justification rédaction', purpose='reference')
    case.tools['search_resources']('Pythagore exercice rédaction autonome', purpose='exercise')


def render_validated(case):
    gather_evidence(case)
    validation = json.loads(case.tools['validate_dossier'](selected_dossier(case.runtime)))
    return json.loads(case.tools['render_capsule'](validation['validated_dossier_id']))


def test_seven_actual_tool_calls_produce_verified_draft(case):
    rendered = render_validated(case)
    inspection = json.loads(case.tools['inspect_capsule'](rendered['render_id']))
    dossier, output = case.runtime.finish(rendered)
    assert inspection['valid'] is True
    assert dossier['transcription']['provider'] == 'Gladia'
    assert len(dossier['sources']) == len(case.context['documents']) + 3
    assert output['video'].endswith('/capsule.mp4')
    assert case.job['approved'] is False
    assert len(case.calls['transcribe']) == len(case.calls['render']) == len(case.calls['inspect']) == 1
    assert len(case.calls['search']) == 2
    summary = summarize_tool_calls(case.job)
    assert summary['total'] == summary['succeeded'] == 7
    assert summary['distinct_tools'] == 6 and summary['failed'] == summary['cached'] == 0
    assert len(case.job['events']) > summary['total']
    # More application progress messages never manufacture function calls.
    engine.event(case.job, 'ready', 'Aperçu disponible.')
    assert summarize_tool_calls(case.job)['total'] == 7


def test_h_sdk_accepts_real_tool_schemas_including_nested_dossier(case):
    tools = {tool.name: tool for tool in as_tools(case.runtime.tools)}
    assert set(tools) == set(case.tools)
    schema = tools['validate_dossier'].input_schema
    assert schema['required'] == ['dossier']
    dossier_schema = schema['$defs']['AgentDossier']
    assert {'question', 'intent', 'evidence', 'scenes'} <= dossier_schema['properties'].keys()
    assert schema['$defs']['SelectedEvidence']['properties']['quote_id']['type'] == 'string'
    purposes = tools['search_resources'].input_schema['properties']['purpose']['enum']
    assert purposes == ['reference', 'exercise']
    assert summarize_tool_calls(case.job)['total'] == 0


def test_query_cache_matches_query_and_purpose_and_source_ids_are_global(case):
    reference = json.loads(case.tools['search_resources']('Pythagore justification', 'reference'))
    cached = json.loads(case.tools['search_resources']('  PYTHAGORE   justification ', 'reference'))
    exercise = json.loads(case.tools['search_resources']('Pythagore exercice autonome', 'exercise'))
    assert cached == reference
    assert len(case.calls['search']) == 2
    assert reference['sources'][0]['id'] == exercise['sources'][0]['id']
    assert reference['sources'][1]['id'] != exercise['sources'][1]['id']
    sources = case.job['search']['sources']
    assert len(sources) == len({source['id'] for source in sources}) == 3
    assert len({source['url'].split('#')[0] for source in sources}) == 3
    assert len(case.job['search']['queries']) == 2
    assert summarize_tool_calls(case.job)['total'] == 3
    assert summarize_tool_calls(case.job)['cached'] == 1
    # Equal text under another purpose must not reuse the first purpose's cache.
    other_purpose = json.loads(case.tools['search_resources']('Pythagore justification', 'exercise'))
    assert other_purpose['purpose'] == 'exercise' and len(case.calls['search']) == 3


def test_validation_requires_two_genuinely_distinct_queries(case):
    case.tools['get_evidence_catalog']([])
    case.tools['transcribe_audio']()
    case.tools['search_resources']('Pythagore justification', 'reference')
    case.tools['search_resources']('  PYTHAGORE justification ', 'exercise')
    with pytest.raises(ValueError):
        case.tools['validate_dossier'](selected_dossier(case.runtime))
    case.tools['search_resources']('Pythagore exercice autonome', 'exercise')
    assert json.loads(case.tools['validate_dossier'](selected_dossier(case.runtime)))['valid'] is True


def test_unread_or_forged_evidence_cannot_authorize_render(case):
    case.tools['get_evidence_catalog'](['bareme'])
    case.tools['transcribe_audio']()
    case.tools['search_resources']('Pythagore justification', 'reference')
    case.tools['search_resources']('Pythagore exercice autonome', 'exercise')
    with pytest.raises(ValueError, match='Lire les extraits'):
        case.tools['validate_dossier'](selected_dossier(case.runtime))
    case.tools['get_evidence_catalog'](['copie'])
    dossier = selected_dossier(case.runtime).model_dump()
    dossier['evidence'][0]['quote_id'] = 'q999'
    with pytest.raises(ValueError, match='Extrait scolaire inconnu'):
        case.tools['validate_dossier'](dossier)
    assert case.runtime.validated == {} and case.calls['render'] == []
    assert summarize_tool_calls(case.job)['failed'] == 2


def test_render_and_inspection_reject_forged_ids_and_missing_steps(case):
    with pytest.raises(ValueError, match='Valider'):
        case.tools['render_capsule']('dossier-forged')
    with pytest.raises(ValueError, match='Aucune capsule'):
        case.tools['inspect_capsule']('capsule-forged')
    rendered = render_validated(case)
    with pytest.raises(ValueError, match='inspecter'):
        case.runtime.finish(rendered)
    with pytest.raises(ValueError, match='identifiants'):
        case.runtime.finish({**rendered, 'validated_dossier_id': 'dossier-forged'})
    with pytest.raises(ValueError, match='Aucune capsule'):
        case.tools['inspect_capsule']('capsule-forged')
    case.tools['inspect_capsule'](rendered['render_id'])
    assert case.runtime.finish(rendered)[1] == rendered['output']


def test_repeated_transcription_and_successful_render_reuse_provider_work(case):
    rendered = render_validated(case)
    case.tools['transcribe_audio']()
    cached_render = json.loads(case.tools['render_capsule'](rendered['validated_dossier_id']))
    assert cached_render == rendered
    assert len(case.calls['transcribe']) == len(case.calls['render']) == 1
    assert summarize_tool_calls(case.job)['cached'] == 2
    assert summarize_tool_calls(case.job)['total'] == 8


def test_failed_render_is_not_cached_and_can_be_retried(case, monkeypatch):
    gather_evidence(case)
    validated = json.loads(case.tools['validate_dossier'](selected_dossier(case.runtime)))
    real_render = engine.render

    def fail_render(*args):
        raise RuntimeError('Rendu interrompu')

    monkeypatch.setattr(engine, 'render', fail_render)
    with pytest.raises(RuntimeError, match='Rendu interrompu'):
        case.tools['render_capsule'](validated['validated_dossier_id'])
    assert case.runtime.rendered is None
    monkeypatch.setattr(engine, 'render', real_render)
    rendered = json.loads(case.tools['render_capsule'](validated['validated_dossier_id']))
    assert rendered['render_id']
    assert summarize_tool_calls(case.job)['failed'] == 1
    assert summarize_tool_calls(case.job)['cached'] == 0
    assert len(case.calls['render']) == 1


def test_engine_live_finishes_only_after_seven_tools_and_no_second_render(case, monkeypatch):
    monkeypatch.setattr(engine, 'key', lambda name: 'test-no-network')

    class FakeClient:
        def __init__(self, **kwargs):
            self.sessions = SimpleNamespace(get_session_changes=lambda *a, **kw: None)

        def start_session(self, **kwargs):
            tools = {tool.__name__: tool for tool in kwargs['tools']}
            tools['get_evidence_catalog']([])
            tools['transcribe_audio']()
            tools['search_resources']('Pythagore justification rédaction', 'reference')
            tools['search_resources']('Pythagore exercice rédaction autonome', 'exercise')
            valid = json.loads(tools['validate_dossier'](selected_dossier(case.runtime)))
            rendered = json.loads(tools['render_capsule'](valid['validated_dossier_id']))
            tools['inspect_capsule'](rendered['render_id'])
            answer = kwargs['answer_schema'](validated_dossier_id=valid['validated_dossier_id'],
                                             render_id=rendered['render_id'])
            return SimpleNamespace(id='session-functional-test',
                                   wait_for_completion=lambda **kw: SimpleNamespace(status='completed', answer=answer),
                                   status=lambda: {'status': 'completed'}, cancel=lambda: None)

    monkeypatch.setattr(engine, 'Client', FakeClient)
    engine._execute(case.job, 'http://localhost:8000')
    assert case.job['status'] == 'ready', case.job.get('error')
    assert case.job['capsule_inspection']['valid'] is True
    assert case.job['approved'] is False
    assert summarize_tool_calls(case.job)['total'] == 7
    assert len(case.calls['render']) == 1
    assert all(call['session_id'] == 'session-functional-test' for call in case.job['tool_calls'])
    persisted = json.loads((engine.DATA / case.job['id'] / 'state.json').read_text())
    assert summarize_tool_calls(persisted)['total'] == 7


def test_engine_offline_renders_without_any_function_call(case, monkeypatch):
    case.job['mode'] = 'demo'
    monkeypatch.setattr(engine, 'duration', lambda path: 38)

    def no_live_client(**kwargs):
        raise AssertionError('Offline mode must never create an H client')

    monkeypatch.setattr(engine, 'Client', no_live_client)
    engine._execute(case.job, 'http://localhost:8000')
    assert case.job['status'] == 'ready', case.job.get('error')
    assert summarize_tool_calls(case.job)['total'] == 0
    assert len(case.calls['render']) == 1
    assert case.calls['transcribe'] == case.calls['search'] == case.calls['inspect'] == []


@pytest.fixture
def media_probe(monkeypatch, tmp_path):
    folder = tmp_path / 'media-job'
    folder.mkdir()
    (folder / 'capsule.mp4').write_bytes(b'media-probe-is-stubbed')
    output = {'video': '/outputs/media-job/capsule.mp4'}
    metadata = {'format': {'duration': '82.5'},
                'streams': [{'codec_type': 'video'}, {'codec_type': 'audio'}]}
    probed = []

    def ffprobe(command, **kwargs):
        probed.append(command[-1])
        return SimpleNamespace(stdout=json.dumps(metadata))

    monkeypatch.setattr(preparation_tools.subprocess, 'run', ffprobe)
    return SimpleNamespace(folder=folder, output=output, metadata=metadata, probed=probed)


def test_media_inspection_accepts_video_audio_and_actual_webvtt(media_probe):
    media = media_probe
    (media.folder / 'captions.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:02.000\nBonjour\n')
    result = inspect_media_actual(media.folder, {**media.output, 'captions': '/outputs/media-job/captions.vtt'})
    assert result['valid'] and result['has_audio'] and result['has_video']
    assert result['duration_seconds'] == 82.5
    assert result['subtitles_verified'] and result['webvtt']
    assert result['requires_teacher_review'] is True
    assert Path(media.probed[0]) == media.folder / 'capsule.mp4'


def test_media_inspection_does_not_claim_burned_subtitles_were_verified(media_probe):
    result = inspect_media_actual(media_probe.folder, media_probe.output)
    assert result['valid'] is True
    assert result['subtitles_verified'] is False
    assert result['subtitle_track'] is result['webvtt'] is False
    assert result['warnings']
    media_probe.metadata['streams'].append({'codec_type': 'subtitle'})
    embedded = inspect_media_actual(media_probe.folder, media_probe.output)
    assert embedded['subtitles_verified'] and embedded['subtitle_track']


@pytest.mark.parametrize('duration', ['NaN', 'Infinity', '-2', '0'])
def test_media_inspection_rejects_nonpositive_or_nonfinite_duration(media_probe, duration):
    media_probe.metadata['format']['duration'] = duration
    with pytest.raises(ValueError, match='durée lisible'):
        inspect_media_actual(media_probe.folder, media_probe.output)


def test_media_inspection_rejects_missing_audio(media_probe):
    media_probe.metadata['streams'] = [{'codec_type': 'video'}]
    with pytest.raises(ValueError, match='piste audio'):
        inspect_media_actual(media_probe.folder, media_probe.output)


def test_media_inspection_rejects_external_paths_before_probing(media_probe):
    for path in ('/outputs/other-job/capsule.mp4', '/outputs/media-job/../other.mp4',
                 'https://example.com/capsule.mp4'):
        with pytest.raises(ValueError, match='dossier courant'):
            inspect_media_actual(media_probe.folder, {'video': path})
    assert media_probe.probed == []


def test_media_inspection_rejects_symlink_before_probing(media_probe, tmp_path):
    target = media_probe.folder / 'capsule.mp4'
    target.unlink()
    external = tmp_path / 'elsewhere.mp4'
    external.write_bytes(b'not-the-current-render')
    target.symlink_to(external)
    with pytest.raises(ValueError, match='absent ou vide'):
        inspect_media_actual(media_probe.folder, media_probe.output)
    assert media_probe.probed == []
