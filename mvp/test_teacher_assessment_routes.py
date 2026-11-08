"""Teacher grading survives the real workspace and rendering paths, without APIs."""
from copy import deepcopy
import importlib
import json

from fastapi.testclient import TestClient
import pytest

from . import engine, preparation_tools, workspace
from .app import app
from .preparation_tools import PreparationTools
from .teacher_assessment import SOURCE_ID, bind_teacher_assessment


@pytest.fixture
def assessment():
    return {
        'student_id': 'alex', 'evaluation_id': 'source-alex',
        'title': 'Devoir de Pythagore', 'date': '2026-11-07',
        'score': 12, 'maximum': 20,
        'appreciation': 'Calcul réussi. Justifier le théorème avant de conclure.',
        'graded_at': '2026-11-07T17:00:00+01:00',
    }


@pytest.fixture
def isolated_workspace(monkeypatch, tmp_path):
    jobs = {}
    root = tmp_path / 'root'
    audio = root / 'fixtures' / engine.FIXTURE['audio']['points']['file']
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b'fake parent audio, hashed but never decoded')
    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setattr(engine, 'ROOT', root)
    monkeypatch.setattr(engine, 'DATA', data)
    monkeypatch.setattr(engine, 'JOBS', jobs)
    monkeypatch.setattr(workspace, 'JOBS', jobs)
    monkeypatch.setattr(workspace, 'STATE', tmp_path / 'workspace.json')
    monkeypatch.setattr(importlib.import_module('mvp.app'), 'JOBS', jobs)
    monkeypatch.setattr('mvp.background_pronote.schedule', lambda **kwargs: None)

    class PausedWorker:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(engine.threading, 'Thread', PausedWorker)
    return TestClient(app), jobs


def start(client, assessment):
    response = client.post('/api/workspace/documents/copie/open', json={
        'voice': 'points', 'mode': 'demo', 'video_provider': 'local',
        'teacher_assessment': assessment,
    })
    assert response.status_code == 200, response.text
    return response.json()['preparation']


@pytest.mark.parametrize('patch', [
    {'score': -1}, {'score': 21}, {'maximum': 0},
    {'title': ''}, {'appreciation': 'x' * 2001}, {'unexpected': True},
])
def test_workspace_route_validates_teacher_assessment_before_launch(isolated_workspace, assessment, patch):
    client, jobs = isolated_workspace
    response = client.post('/api/workspace/documents/copie/open', json={
        'mode': 'demo', 'teacher_assessment': {**assessment, **patch},
    })
    assert response.status_code == 422
    assert not jobs


def test_workspace_route_rejects_grading_another_pupil_with_alexs_copy(isolated_workspace, assessment):
    client, jobs = isolated_workspace
    response = client.post('/api/workspace/documents/copie/open', json={
        'mode': 'demo', 'teacher_assessment': {**assessment, 'student_id': 'lea'},
    })
    assert response.status_code == 400
    assert not jobs


def test_workspace_freezes_assessment_and_cache_changes_with_each_teacher_edit(isolated_workspace, assessment):
    client, jobs = isolated_workspace
    original = deepcopy(engine.FIXTURE)
    first = start(client, assessment)
    same = start(client, assessment)
    grade_changed = start(client, {**assessment, 'score': 15})
    appreciation_changed = start(client, {**assessment, 'appreciation': 'Bonne progression de la rédaction.'})
    assert first['id'] == same['id']
    assert len({first['id'], grade_changed['id'], appreciation_changed['id']}) == 3
    frozen = first['input_context']
    assert frozen['documents'][:-1] == original['documents']
    assert frozen['documents'][-1]['id'] == SOURCE_ID
    assert frozen['teacher_assessment']['score'] == 12
    assert frozen['teacher_assessment']['appreciation'] == assessment['appreciation']
    assert jobs[first['id']]['input_context']['teacher_assessment']['score'] == 12
    assert engine.FIXTURE == original
    assessment['score'] = 3
    assert jobs[first['id']]['input_context']['teacher_assessment']['score'] == 12
    source_page = client.get(f'/school/{SOURCE_ID}?agent=1&job={first["id"]}')
    assert source_page.status_code == 200
    assert '12/20' in source_page.text
    assert frozen['teacher_assessment']['appreciation'] in source_page.text
    stored = json.loads((engine.DATA / first['id'] / 'state.json').read_text())
    assert stored['input_context']['teacher_assessment'] == frozen['teacher_assessment']


def test_offline_execution_renders_the_current_grade_and_appreciation(isolated_workspace, assessment, monkeypatch):
    client, jobs = isolated_workspace
    prepared = start(client, assessment)
    rendered = []

    def render(dossier, folder):
        rendered.append(deepcopy(dossier))
        return {'video': f'/outputs/{folder.name}/capsule.mp4', 'duration': 82}

    monkeypatch.setattr(engine, 'render', render)
    monkeypatch.setattr(engine, 'duration', lambda path: 18)
    engine._execute(jobs[prepared['id']], 'http://localhost:8000')
    assert jobs[prepared['id']]['status'] == 'ready', jobs[prepared['id']].get('error')
    assert len(rendered) == 1
    dossier = rendered[0]
    assert '12/20' in dossier['summary']
    assert assessment['appreciation'] in dossier['summary']
    assert '12 sur 20' in dossier['scenes'][2]['narration']
    assert assessment['appreciation'] in dossier['scenes'][2]['narration']
    assert dossier['teacher_assessment']['evaluation_id'] == 'source-alex'
    assert dossier['sources'][-1]['id'] == SOURCE_ID
    assert '3/6' in next(doc['text'] for doc in dossier['sources'] if doc['id'] == 'copie')


def test_offline_execution_still_rejects_rewritten_baseline_documents(isolated_workspace, assessment, monkeypatch):
    client, jobs = isolated_workspace
    prepared = start(client, assessment)
    job = jobs[prepared['id']]
    job['input_context']['documents'][0]['text'] = 'Une nouvelle consigne sans rapport.'
    rendered = []
    monkeypatch.setattr(engine, 'render', lambda *args: rendered.append(args))
    engine._execute(job, 'http://localhost:8000')
    assert job['status'] == 'failed'
    assert not rendered
    assert 'pièces ont changé' in job['error']


def test_live_tools_keep_teacher_source_and_overlay_marks_even_when_h_omits_them(assessment, monkeypatch, tmp_path):
    context = bind_teacher_assessment(engine.FIXTURE, assessment)
    job = {
        'id': 'teacher-live-tools', 'mode': 'live', 'scenario': 'points',
        'status': 'preparing', 'events': [], 'approved': False,
        'video_provider': 'local', 'input_context': context,
    }
    rendered = []
    monkeypatch.setattr(engine, 'DATA', tmp_path)
    monkeypatch.setattr(engine, 'transcribe', lambda path: {
        'provider': 'Gladia', 'text': 'Comment peut-il progresser ?', 'utterances': [],
    })
    monkeypatch.setattr(engine, 'search', lambda topic: {'provider': 'Linkup', 'query': topic, 'sources': []})

    def render(dossier, folder):
        rendered.append(deepcopy(dossier))
        return {'video': f'/outputs/{folder.name}/capsule.mp4', 'duration': 82}

    monkeypatch.setattr(engine, 'render', render)
    monkeypatch.setattr(preparation_tools, 'inspect_media', lambda folder, output: {
        'valid': True, 'duration_seconds': 82, 'has_video': True,
        'has_audio': True, 'subtitles_verified': True, 'video': output['video'],
    })
    runtime = PreparationTools(job, context, tmp_path / 'unused-audio.wav')
    tools = {tool.__name__: tool for tool in runtime.tools}
    catalog = json.loads(tools['get_evidence_catalog'](['copie']))
    assert SOURCE_ID in {doc['id'] for doc in catalog['documents']}
    assert SOURCE_ID in runtime.read_ids
    assert catalog['teacher_assessment']['score'] == 12
    assert catalog['teacher_assessment']['appreciation'] == assessment['appreciation']
    tools['get_evidence_catalog'](['bareme'])
    tools['transcribe_audio']()
    tools['search_resources']('Pythagore justification rédaction', 'reference')
    tools['search_resources']('Pythagore exercice autonome', 'exercise')
    proposed = engine.offline_dossier('points')
    proposed['evidence'] = [
        {'claim': 'Une preuve issue de la copie.', 'quote_id': next(
            key for key, value in runtime.catalog.items() if value['source_id'] == identifier)}
        for identifier in ('copie', 'bareme')
    ]
    # Simulate an H answer still containing the historical grade. Server-side
    # inclusion supplies the actual teacher assessment before media rendering.
    validation = json.loads(tools['validate_dossier'](engine.AgentDossier.model_validate(proposed)))
    output = json.loads(tools['render_capsule'](validation['validated_dossier_id']))
    tools['inspect_capsule'](output['render_id'])
    final_dossier, final_output = runtime.finish(output)
    assert len(rendered) == 1
    assert '12/20' in rendered[0]['summary']
    assert assessment['appreciation'] in rendered[0]['scenes'][2]['narration']
    assert SOURCE_ID in rendered[0]['scenes'][2]['source_ids']
    assert final_dossier['teacher_assessment']['score'] == 12
    assert assessment['appreciation'] in final_dossier['summary']
    assert final_output['video'].endswith('/capsule.mp4')
    assert job['approved'] is False
