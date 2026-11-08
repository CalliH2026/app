"""Native observer → H tools → grounded dossier → video, with no paid calls."""
import copy
import hashlib
from types import SimpleNamespace

import pytest

from . import engine, native_pipeline as pipeline


@pytest.fixture
def case(tmp_path):
    audio = tmp_path / 'parent.wav'
    audio.write_bytes(b'test parent audio, not sent to a provider')
    school = {'copy': 'Le calcul donne 5 cm. Justification absente : 0/1.',
              'rubric': 'La justification du théorème vaut un point.'}
    for name, text in school.items():
        (tmp_path / (name + '.txt')).write_text(text)
    provenance = {'kind': 'imported_demo_document', 'locator': str(tmp_path / 'copy.txt'),
                  'path': str(tmp_path / 'copy.txt'),
                  'native_context_id': 'native-context', 'observed_at': '2026-11-07T12:00:00+01:00',
                  'imported_into_native': True,
                  'import_evidence': {'method': 'native_ui', 'observed_at': 'test-only'}}
    return {
        'context': {'state': 'observed', 'source_kind': 'pronote_macos',
                    'context_id': 'native-context', 'method': 'win32_document_windows', 'pid': 100,
                    'database_path': str(tmp_path / 'base-exemple.not'), 'dossier_id': 'eval-test',
                    'window_title': 'copy.txt — PRONOTE'},
        'trigger': {'type': 'copy_opened', 'document_id': 'native-copy',
                    'source_locator': provenance['locator'], 'observed_at': provenance['observed_at'],
                    'proof': 'Viewer native ouvert : copy.txt',
                    'evidence': {'method': 'win32_document_windows', 'hwnd': '12', 'pid': 100,
                                 'window_title': 'copy.txt — PRONOTE', 'filename': 'copy.txt',
                                 'process': 'PRONOTE Monoposte.exe', 'class': 'TPdfViewer',
                                 'image_path': 'C:\\H-Demo\\PRONOTE\\PRONOTE Monoposte.exe'}},
        'sources': [
            {'id': 'native-copy', 'role': 'copy', 'title': 'Copie test importée',
             'text': school['copy'], 'provenance': provenance,
             'sha256': hashlib.sha256((tmp_path / 'copy.txt').read_bytes()).hexdigest()},
            {'id': 'native-rubric', 'role': 'rubric', 'title': 'Barème test importé',
             'text': school['rubric'],
             'sha256': hashlib.sha256((tmp_path / 'rubric.txt').read_bytes()).hexdigest(),
             'provenance': {**provenance, 'locator': str(tmp_path / 'rubric.txt'),
                            'path': str(tmp_path / 'rubric.txt')}},
        ],
        'parent_audio': {'path': str(audio), 'provenance': {
            **provenance, 'kind': 'attached_test_dossier', 'locator': str(audio),
            'imported_into_native': False}},
        'identity': {'student_name': 'Camille Exemple', 'class_name': '4e C'},
    }


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'DATA', tmp_path)
    monkeypatch.setattr(engine, 'JOBS', {})
    return tmp_path


def answer(question='Pourquoi perd-il un point ?'):
    return {
        'question': question, 'intent': 'points', 'summary': 'La justification manque selon la copie et le barème.',
        'evidence': [
            {'claim': 'La justification est absente.', 'quote': 'Justification absente : 0/1.', 'source_ids': ['native-copy']},
            {'claim': 'Le critère est annoncé.', 'quote': 'La justification du théorème vaut un point.', 'source_ids': ['native-rubric']},
        ], 'unknowns': ['L’élève peut-il expliquer oralement son raisonnement ?'],
        'scenes': [
            {'title': 'La question', 'body': question, 'narration': question, 'source_ids': ['audio']},
            {'title': 'Les critères', 'body': 'Justifier le théorème.', 'narration': 'Un point est prévu pour la justification.', 'source_ids': ['native-rubric']},
            {'title': 'La copie', 'body': 'Une justification absente.', 'narration': 'Le calcul et le raisonnement sont deux critères.', 'source_ids': ['native-copy', 'native-rubric']},
            {'title': 'Progresser', 'body': 'Expliciter chaque étape.', 'narration': 'La ressource publique aide à retravailler la justification.', 'source_ids': ['web-1']},
        ],
    }


EXTERNAL = [{'id': 'web-1', 'title': 'Raisonner', 'url': 'https://eduscol.education.fr/test',
             'excerpt': 'Expliciter son raisonnement.', 'type': 'external'}]


def services(calls, dossier=None, fail=None, captured=None):
    class Session:
        id = 'h-test-session'

        def wait_for_completion(self, **kwargs):
            # idle is the actual successful H SDK completion state too.
            return SimpleNamespace(status='idle', answer=dossier or answer(), error=None)

        def send_message(self, message):
            calls.append(('repair', message))

        def cancel(self):
            calls.append(('cancel', None))

    class Client:
        def start_session(self, **kwargs):
            calls.append(('h', kwargs['agent']))
            tools = {tool.__name__: tool for tool in kwargs['tools']}
            documents = tools['read_native_documents']()
            if captured is not None:
                import json
                captured['documents'] = json.loads(documents)
            tools['transcribe_audio']()
            tools['search_resources']('Mathématiques collège : justifier un raisonnement et exercice guidé')
            return Session()

    def transcribe(path):
        calls.append(('gladia', str(path)))
        if captured is not None:
            captured['audio'] = path.read_bytes()
        if fail:
            raise RuntimeError(fail)
        return {'provider': 'Gladia', 'job_id': 'stt-test',
                'text': 'Bonjour. Pourquoi perd-il un point ?',
                'utterances': [{'start': 0.8, 'end': 3.4, 'text': 'Pourquoi perd-il un point ?'}]}

    def search(topic):
        calls.append(('linkup', topic))
        return {'provider': 'Linkup', 'query': topic, 'sources': EXTERNAL}

    def render(dossier, folder):
        calls.append(('video', dossier))
        (folder / 'capsule.mp4').write_bytes(b'test render')
        return {'duration': 62, 'video': f'/outputs/{folder.name}/capsule.mp4',
                'captions': f'/outputs/{folder.name}/captions.vtt'}

    return pipeline.Services(transcribe=transcribe, search=search, client_factory=Client, render=render)


def test_native_event_requires_real_copy_match_and_rubric(case):
    assert pipeline.NativeCase.model_validate(case).trigger.document_id == 'native-copy'
    invalid = copy.deepcopy(case)
    invalid['trigger']['source_locator'] = 'C:/Unrelated.txt'
    with pytest.raises(ValueError, match='ne correspond pas'):
        pipeline.NativeCase.model_validate(invalid)
    invalid = copy.deepcopy(case)
    invalid['sources'][1]['role'] = 'method'
    with pytest.raises(ValueError, match='barème réellement lu manque'):
        pipeline.NativeCase.model_validate(invalid)
    invalid = copy.deepcopy(case)
    invalid['sources'][0]['provenance']['imported_into_native'] = False
    with pytest.raises(ValueError, match='import dans la base'):
        pipeline.NativeCase.model_validate(invalid)


def test_complete_native_pipeline_and_reopening_are_idempotent(case, isolated):
    calls = []
    first = pipeline.schedule(case, services=services(calls), background=False)
    assert first['status'] == 'ready'
    assert [name for name, _ in calls] == ['h', 'gladia', 'linkup', 'video']
    assert calls[0][1]['environments'] == []
    assert first['dossier']['display_label'] == 'Camille Exemple · 4e C'
    assert 'importés dans le vrai PRONOTE' in first['dossier']['provenance_notice']
    assert first['dossier']['sources'][0]['id'] == 'native-copy'
    assert first['source_kind'] == 'pronote_native_dossier'
    assert first['approved'] is False
    assert (isolated / first['id'] / 'dossier.json').exists()
    reopened = copy.deepcopy(case)
    reopened['trigger']['observed_at'] = '2026-11-07T12:01:00+01:00'
    reopened['context']['context_id'] = 'next-native-context'
    for source in reopened['sources']:
        source['provenance']['native_context_id'] = 'next-native-context'
    second = pipeline.schedule(reopened, services=services(calls), background=False)
    assert first['id'] == second['id']
    assert len(calls) == 4
    assert pipeline.status()['id'] == first['id']


def test_changed_voice_or_rubric_produces_new_preparation(case, isolated):
    calls = []
    first = pipeline.schedule(case, services=services(calls), background=False)
    changed = copy.deepcopy(case)
    changed['sources'][1]['text'] += ' Le résultat seul ne suffit pas.'
    from pathlib import Path
    path = Path(changed['sources'][1]['provenance']['path'])
    path.write_text(changed['sources'][1]['text'])
    changed['sources'][1]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    second = pipeline.schedule(changed, services=services(calls), background=False)
    assert second['id'] != first['id'] and second['status'] == 'ready'
    Path(case['parent_audio']['path']).write_bytes(b'another parent question')
    third = pipeline.schedule(changed, services=services(calls), background=False)
    assert third['id'] not in (first['id'], second['id'])
    assert sum(name == 'video' for name, _ in calls) == 3


def test_failed_provider_never_renders_or_substitutes_fixture(case, isolated):
    calls = []
    result = pipeline.schedule(case, services=services(calls, fail='Gladia unavailable'), background=False)
    assert result['status'] == 'failed' and result['error'] == 'Gladia unavailable'
    assert 'dossier' not in result and 'video' not in result
    assert not any(name == 'video' for name, _ in calls)
    again = pipeline.schedule(case, services=services(calls), background=False)
    assert again['id'] == result['id'] and again['status'] == 'failed'


def test_native_citations_and_external_boundary(case):
    native = pipeline.NativeCase.model_validate(case)
    transcript = {'text': 'Bonjour. Pourquoi perd-il un point ?'}
    valid = answer()
    assert pipeline.checked_answer(valid, native, transcript, EXTERNAL)['intent'] == 'points'
    invalid = answer()
    invalid['evidence'][0]['quote'] = 'Un calcul faux retire un point.'
    with pytest.raises(ValueError, match='Citation.*conforme'):
        pipeline.checked_answer(invalid, native, transcript, EXTERNAL)
    invalid = answer()
    invalid['scenes'][2]['source_ids'].append('web-1')
    with pytest.raises(ValueError, match='externes ne doivent pas expliquer la note'):
        pipeline.checked_answer(invalid, native, transcript, EXTERNAL)
    invalid = answer('Comment peut-il progresser ?')
    with pytest.raises(ValueError, match='question doit être un extrait exact'):
        pipeline.checked_answer(invalid, native, transcript, EXTERNAL)


def test_linkup_query_rejects_identity_and_contact_data(case):
    native = pipeline.NativeCase.model_validate(case)
    pipeline._check_public_query('Justification du raisonnement en mathématiques au collège', native)
    for topic in ('Camille a perdu un point en mathématiques',
                  'Comment faire progresser la classe 4e C ?',
                  'Explication pour parent@example.fr',
                  'Appeler le 0612345678 pour les maths'):
        with pytest.raises(ValueError, match='sans'):
            pipeline._check_public_query(topic, native)


def test_modern_workspace_is_explicitly_separate_from_native(case, isolated):
    modern = copy.deepcopy(case)
    modern['context'].update(source_kind='pronote_modern', method='modern_workspace',
                             window_title='PRONOTE moderne · Copie')
    modern['trigger']['type'] = 'modern_copy_opened'
    for source in modern['sources']:
        source['provenance'].update(kind='demo_workspace_document', imported_into_native=False)
    calls = []
    result = pipeline.schedule(modern, services=services(calls), background=False)
    assert result['status'] == 'ready'
    assert result['source_kind'] == 'pronote_modern_dossier'
    assert 'distincte du client natif' in result['dossier']['provenance_notice']
    assert not any('dans le vrai PRONOTE' in event['text'] for event in result['events'])
    # Reusing that payload as a native event must fail rather than upgrade provenance.
    modern['context']['source_kind'] = 'pronote_macos'
    modern['trigger']['type'] = 'copy_opened'
    with pytest.raises(ValueError, match='effectivement importé'):
        pipeline.NativeCase.model_validate(modern)


def test_registration_without_an_observed_viewer_is_not_an_opening(case):
    registered = copy.deepcopy(case)
    registered['trigger'].pop('evidence')
    with pytest.raises(ValueError, match='vraie ouverture'):
        pipeline.NativeCase.model_validate(registered)
    registered = copy.deepcopy(case)
    registered['trigger']['evidence']['hwnd'] = '0'
    with pytest.raises(ValueError):
        pipeline.NativeCase.model_validate(registered)
    registered = copy.deepcopy(case)
    registered['trigger']['evidence']['filename'] = 'other.txt'
    with pytest.raises(ValueError, match='ne désigne pas'):
        pipeline.NativeCase.model_validate(registered)


def test_native_rubric_must_share_the_observed_case_and_import_proof(case):
    other_case = copy.deepcopy(case)
    other_case['sources'][1]['provenance']['native_context_id'] = 'another-student-or-assessment'
    with pytest.raises(ValueError, match='même contexte'):
        pipeline.NativeCase.model_validate(other_case)
    no_proof = copy.deepcopy(case)
    no_proof['sources'][1]['provenance'].pop('import_evidence')
    with pytest.raises(ValueError, match='preuve native'):
        pipeline.NativeCase.model_validate(no_proof)
    no_base = copy.deepcopy(case)
    no_base['context'].pop('database_path')
    with pytest.raises(ValueError, match='base et le dossier'):
        pipeline.NativeCase.model_validate(no_base)


def test_generic_viewer_caption_can_prove_a_real_opening(case):
    captured = copy.deepcopy(case)
    captured['context']['window_title'] = 'Visionneuse PDF'
    captured['trigger']['evidence'].update(window_title='Visionneuse PDF',
                                          controls=[{'class': 'TLabel', 'text': 'copy.txt'}])
    assert pipeline.NativeCase.model_validate(captured).trigger.document_id == 'native-copy'
    captured['trigger']['evidence']['controls'] = [{'class': 'TLabel', 'text': 'copy.txt.backup'}]
    with pytest.raises(ValueError, match='ne désigne pas'):
        pipeline.NativeCase.model_validate(captured)


def test_actual_file_hash_and_extracted_text_are_checked_before_h(case, isolated):
    from pathlib import Path
    calls = []
    forged = copy.deepcopy(case)
    forged['sources'][1]['text'] = 'Invented marking scheme not in the actual file.'
    with pytest.raises(ValueError, match='octets réellement lus'):
        pipeline.schedule(forged, services=services(calls), background=False)
    Path(case['sources'][0]['provenance']['path']).write_text('Modified after native collection.')
    with pytest.raises(ValueError, match='changé depuis son observation'):
        pipeline.schedule(case, services=services(calls), background=False)
    assert not calls and not engine.JOBS


def test_queued_work_uses_frozen_documents_and_audio(case, isolated, monkeypatch):
    from pathlib import Path
    queued, calls, captured = [], [], {}
    class QueuedThread:
        def __init__(self, *, target, daemon, name):
            self.target = target
        def start(self):
            queued.append(self.target)
    monkeypatch.setattr(pipeline, 'threading', SimpleNamespace(Thread=QueuedThread))
    result = pipeline.schedule(case, services=services(calls, captured=captured))
    assert result['status'] == 'preparing' and not calls
    original_audio = Path(case['parent_audio']['path']).read_bytes()
    Path(case['parent_audio']['path']).write_bytes(b'changed while teacher continues working')
    Path(case['sources'][0]['provenance']['path']).write_text('Another copy, after the observation')
    case['sources'][0]['text'] = 'Mutated in-memory payload after scheduling'
    queued.pop()()
    result = engine.snapshot(result['id'])
    assert result['status'] == 'ready'
    assert captured['audio'] == original_audio
    assert captured['documents']['documents'][0]['text'] == 'Le calcul donne 5 cm. Justification absente : 0/1.'
    assert result['captured_audio'] == 'parent-audio.wav'
    assert (isolated / result['id'] / result['captured_audio']).read_bytes() == original_audio
    assert Path(next(value for name, value in calls if name == 'gladia')).parent == isolated / result['id']
    raw_copy = next(source for source in result['captured_sources'] if source['id'] == 'native-copy')
    assert (isolated / result['id'] / raw_copy['file']).read_text().startswith('Le calcul donne 5 cm.')


def selected_answer(question='Pourquoi perd-il un point ?'):
    result = answer(question)
    result['evidence'] = [{'claim': 'La justification est absente.', 'quote_id': 'q002'},
                          {'claim': 'Le critère est annoncé.', 'quote_id': 'q003'}]
    return result


def test_quote_ids_resolve_to_exact_observed_school_text(case):
    native = pipeline.NativeCase.model_validate(case)
    result = pipeline.checked_answer(selected_answer(), native,
                                     {'text': 'Bonjour. Pourquoi perd-il un point ?'}, EXTERNAL)
    assert result['evidence'][0]['quote'] == 'Justification absente : 0/1.'
    assert result['evidence'][0]['source_ids'] == ['native-copy']
    invalid = selected_answer()
    invalid['evidence'][0]['quote_id'] = 'q999'
    with pytest.raises(ValueError, match='Extrait scolaire inconnu'):
        pipeline.checked_answer(invalid, native, {'text': 'Pourquoi perd-il un point ?'}, EXTERNAL)


def test_without_audio_no_parent_question_or_gladia_call_is_fabricated(case, isolated):
    no_audio = copy.deepcopy(case)
    no_audio.pop('parent_audio')
    dossier = selected_answer(pipeline.DEFAULT_QUESTION)
    dossier['scenes'][0]['source_ids'] = ['native-copy', 'native-rubric']
    calls = []
    result = pipeline.schedule(no_audio, services=services(calls, dossier=dossier), background=False)
    assert result['status'] == 'ready'
    assert [name for name, _ in calls] == ['h', 'linkup', 'video']
    assert result['question_origin'] == 'workflow_default'
    assert result['transcription']['available'] is False and result['transcription']['provider'] is None
    assert result['dossier']['audio_provenance'] is None
    assert 'captured_audio' not in result
    forged = selected_answer(pipeline.DEFAULT_QUESTION)
    with pytest.raises(ValueError, match='inconnue'):
        pipeline.checked_answer(forged, pipeline.NativeCase.model_validate(no_audio),
                                {'text': pipeline.DEFAULT_QUESTION}, EXTERNAL)


def test_a_failed_newer_attempt_does_not_hide_a_ready_preparation(case, isolated):
    calls = []
    first = pipeline.schedule(case, services=services(calls), background=False)
    stale = copy.deepcopy(first)
    stale.update(id='ffffffffffff', status='failed', created_at='2099-01-01T00:00:00+00:00')
    engine.JOBS[stale['id']] = stale
    again = pipeline.schedule(case, services=services(calls), background=False)
    assert again['id'] == first['id'] and again['status'] == 'ready'
    assert len(calls) == 4


def test_fresh_repair_does_not_repeat_gladia_linkup_or_native_reading(case, isolated):
    calls, sessions = [], []
    class Session:
        def __init__(self, identifier, value):
            self.id, self.value, self.state = identifier, value, 'idle'
        def wait_for_completion(self, **kwargs):
            return SimpleNamespace(status='idle', answer=self.value, error=None)
        def status(self):
            return self.state
        def cancel(self):
            calls.append(('cancel', self.id))
            self.state = 'cancelled'
        def send_message(self, message):
            pytest.fail('A repair must not replay the previous idle session')
    class Client:
        def start_session(self, **kwargs):
            assert kwargs['agent']['environments'] == []
            tools = {tool.__name__: tool for tool in kwargs['tools']}
            if 'read_native_documents' in tools:
                assert kwargs['answer_schema'] is pipeline.NativeAgentDossier
                calls.append(('native-read', tools['read_native_documents']()))
                tools['transcribe_audio']()
                tools['search_resources']('Justifier un raisonnement en mathématiques au collège')
                invalid = selected_answer()
                invalid['evidence'][0]['quote_id'] = 'q999'
                session = Session('h-first', invalid)
            else:
                import json
                frozen = json.loads(tools['read_native_repair_context']())
                assert frozen['quote_catalog']['q002']['quote'] == 'Justification absente : 0/1.'
                assert frozen['audio_available'] is True
                assert frozen['question_catalog']['a001']['text'] == 'Pourquoi perd-il un point ?'
                assert frozen['transcription']['source_id'] == 'audio'
                assert frozen['scene_source_contract'] == {
                    'allowed_source_ids': ['native-copy', 'native-rubric', 'audio', 'web-1'],
                    'scene_1_exact_source_ids': ['audio'],
                    'scene_2_exact_source_ids': ['native-rubric'],
                    'scene_3_exact_source_ids': ['native-copy', 'native-rubric'],
                    'scene_4_select_from_external_ids': ['web-1'],
                }
                assert 'previous_answer' not in frozen
                assert frozen['previous_selection']['intent'] == 'points'
                assert 'conclusion rédigée' in kwargs['messages']
                assert 'réduite' not in kwargs['messages']
                assert 'CJK' not in kwargs['messages']
                assert 'audio_available=true' in kwargs['messages']
                assert 'Extrait scolaire inconnu' in frozen['validation_error']
                calls.append(('repair-read', None))
                session = Session('h-repair', selected_answer())
            sessions.append(session)
            return session
    service = services(calls)
    service.client_factory = Client
    result = pipeline.schedule(case, services=service, background=False)
    assert result['status'] == 'ready'
    assert result['validation_session_ids'] == ['h-repair']
    assert [name for name, _ in calls].count('native-read') == 1
    assert [name for name, _ in calls].count('gladia') == 1
    assert [name for name, _ in calls].count('linkup') == 1
    assert [name for name, _ in calls].count('video') == 1
    assert [value for name, value in calls if name == 'cancel'] == ['h-first', 'h-repair']
    assert len(result['h_answers']) == 2
    assert result['dossier']['evidence'][0]['quote'] == 'Justification absente : 0/1.'


def _write_test_pdf(path, text):
    """Small genuine PDF from stdlib bytes; the native export remains a test double."""
    payload = ('BT /F1 10 Tf 40 750 Td (' + text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') + ') Tj ET').encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(payload)).encode() + b' >>\nstream\n' + payload + b'\nendstream']
    data, offsets = b'%PDF-1.4\n', [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(index).encode() + b' 0 obj\n' + value + b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets[1:])
    data += b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _native_export_case(case, tmp_path):
    import struct
    from mvp.native.native_documents import extract_text
    event = copy.deepcopy(case)
    drive = tmp_path / 'drive_c'
    base = drive / 'H-Demo/PRONOTE/Exemples/Base Exemple.not'
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_bytes(b'test-only database, not a production PRONOTE file')
    exported = drive / 'users/crossover/Temp/{11111111-2222-3333-4444-555555555555}/Copy_Fanny_Pythagore.pdf'
    _write_test_pdf(exported, 'Le calcul donne 5 cm. Justification absente : 0/1.')
    sha = hashlib.sha256(exported.read_bytes()).hexdigest()
    event['context'].update(method='native_export_file_open', database_path=str(base), base_id='23145',
                            database_window_title='PRONOTE - [' + base.name + ' modifie]',
                            window_title='PRONOTE - [' + base.name + ' modifie]')
    active = event['sources'][0]
    active.update(title=exported.name, text=extract_text(exported), sha256=sha)
    active['provenance'].update(kind='native_export', path=str(exported), locator=str(exported))
    from pathlib import Path
    for index, source in enumerate(event['sources'], 1):
        original = Path(source['provenance']['path']).read_bytes()
        storage = drive / 'ProgramData/IndexEducation/PRONOTE/MONOPOSTE/VERSION 2026-0/FR/DocJointEleve/23145' / f'{{test-storage-{index}}}'
        storage.parent.mkdir(parents=True, exist_ok=True)
        # Only its observed header is used by the pipeline; no payload decoder.
        raw = (b'FSFB\x02\x00\x00\x00' + bytes.fromhex(source['sha256'])
               + hashlib.md5(original).digest() + b'\x01' + struct.pack('<Q', len(original))
               + b'test-only native storage payload')
        storage.write_bytes(raw)
        source['provenance']['native_storage'] = {'path': str(storage),
                                                  'file_sha256': hashlib.sha256(raw).hexdigest()}
    event['trigger'].update(source_locator=str(exported), proof='Test-only observed Preview open-file export',
                            evidence={'method': 'native_export_file_open', 'export_path': str(exported),
                                      'sha256': sha, 'viewer_pid': 500, 'viewer_bundle_id': 'com.apple.Preview',
                                      'viewer_process': 'Preview', 'viewer_open_path': str(exported),
                                      'observed_at': event['trigger']['observed_at'], 'filename': exported.name})
    return event


def test_native_preview_export_is_validated_and_frozen_without_desktop(case, tmp_path, isolated):
    exported = _native_export_case(case, tmp_path)
    parsed = pipeline.NativeCase.model_validate(exported)
    assert isinstance(parsed.trigger.evidence, pipeline.NativeExportEvidence)
    calls = []
    result = pipeline.schedule(exported, services=services(calls, dossier=selected_answer()), background=False)
    assert result['status'] == 'ready'
    assert result['trigger']['evidence']['viewer_pid'] == 500
    assert result['source_kind'] == 'pronote_native_dossier'
    assert calls[0][1]['environments'] == []
    stored = next(source for source in result['captured_sources'] if source['id'] == 'native-copy')
    assert stored['file'].endswith('.pdf')
    assert (isolated / result['id'] / stored['file']).read_bytes().startswith(b'%PDF-')


def test_prepared_pdf_or_wrong_open_file_cannot_become_a_native_export_event(case, tmp_path):
    from pathlib import Path
    exported = _native_export_case(case, tmp_path)
    absent_preview = copy.deepcopy(exported)
    absent_preview['trigger']['evidence']['viewer_pid'] = 0
    with pytest.raises(ValueError):
        pipeline.NativeCase.model_validate(absent_preview)
    other_viewer = copy.deepcopy(exported)
    other_viewer['trigger']['evidence']['viewer_bundle_id'] = 'not.preview'
    with pytest.raises(ValueError):
        pipeline.NativeCase.model_validate(other_viewer)
    wrong_opened = copy.deepcopy(exported)
    other = Path(exported['trigger']['evidence']['export_path']).with_name('other.pdf')
    other.write_bytes(Path(exported['trigger']['evidence']['export_path']).read_bytes())
    wrong_opened['trigger']['evidence']['viewer_open_path'] = str(other)
    with pytest.raises(ValueError, match='réellement ouvert'):
        pipeline.NativeCase.model_validate(wrong_opened)
    imported_only = copy.deepcopy(exported)
    imported_only['sources'][0]['provenance']['kind'] = 'imported_demo_document'
    with pytest.raises(ValueError, match='effectivement ouvert'):
        pipeline.NativeCase.model_validate(imported_only)


def test_export_must_belong_to_the_live_database_and_native_temp_root(case, tmp_path):
    exported = _native_export_case(case, tmp_path)
    wrong_base = copy.deepcopy(exported)
    wrong_base['context']['database_window_title'] = 'PRONOTE - [Another Base.not]'
    with pytest.raises(ValueError, match='base enregistrée'):
        pipeline.NativeCase.model_validate(wrong_base)
    outside = tmp_path / 'outside.pdf'
    from pathlib import Path
    outside.write_bytes(Path(exported['trigger']['evidence']['export_path']).read_bytes())
    escaped = copy.deepcopy(exported)
    escaped['trigger'].update(source_locator=str(outside))
    escaped['trigger']['evidence'].update(export_path=str(outside), viewer_open_path=str(outside), filename=outside.name)
    escaped['sources'][0]['provenance'].update(path=str(outside), locator=str(outside))
    with pytest.raises(ValueError, match='bouteille'):
        pipeline.NativeCase.model_validate(escaped)


def test_all_native_export_sources_need_unchanged_fsfb_linkage(case, tmp_path):
    from pathlib import Path
    exported = _native_export_case(case, tmp_path)
    missing = copy.deepcopy(exported)
    missing['sources'][1]['provenance'].pop('native_storage')
    with pytest.raises(ValueError, match='stockage natif FSFB'):
        pipeline.NativeCase.model_validate(missing)
    changed = copy.deepcopy(exported)
    record = changed['sources'][1]['provenance']['native_storage']
    path = Path(record['path'])
    payload = bytearray(path.read_bytes())
    payload[8:40] = bytes.fromhex('0' * 64)
    path.write_bytes(payload)
    # Updating the raw storage checksum cannot fake its link to this rubric.
    record['file_sha256'] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError, match='FSFB ne confirme pas'):
        pipeline.NativeCase.model_validate(changed)


def test_export_hash_and_symlink_escape_are_rejected(case, tmp_path):
    from pathlib import Path
    exported = _native_export_case(case, tmp_path)
    wrong = copy.deepcopy(exported)
    wrong['trigger']['evidence']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='empreinte'):
        pipeline.NativeCase.model_validate(wrong)
    path = Path(exported['trigger']['evidence']['export_path'])
    outside = tmp_path / 'outside-copy.pdf'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match='bouteille'):
        pipeline.NativeCase.model_validate(exported)


def test_native_clear_export_preserves_imported_demo_origin(case, tmp_path, isolated):
    exported = _native_export_case(case, tmp_path)
    for source in exported['sources']:
        source['provenance'].update(kind='native_export', import_origin_kind='imported_demo_document')
    result = pipeline.schedule(exported, services=services([], dossier=selected_answer()), background=False)
    assert result['status'] == 'ready'
    assert result['dossier']['provenance_notice'] == 'Documents de démonstration importés dans le vrai PRONOTE.'
    assert all(source['provenance']['import_origin_kind'] == 'imported_demo_document'
               for source in result['dossier']['sources'] if source['type'] == 'school')


def test_question_utterance_id_resolves_literal_text_and_audio_position(case):
    native = pipeline.NativeCase.model_validate(case)
    question = 'Pourquoi perd-elle ces points alors que son calcul est correct ?'
    transcript = {'provider': 'Gladia', 'job_id': 'stt-observed',
                  'text': 'Bonjour. ' + question + ' Nous aimerions comprendre ce qui est attendu.',
                  'utterances': [{'text': question, 'start': 16.878, 'end': 20.0}]}
    selected = selected_answer('Nous aimerions comprendre ce qui est attendre.')
    selected['question_quote_id'] = 'a001'
    dossier = pipeline.checked_answer(selected, native, transcript, EXTERNAL)
    assert dossier['question'] == question
    assert dossier['question_quote_id'] == 'a001'
    assert dossier['question_excerpt']['start'] == 16.878
    assert dossier['question_excerpt']['end'] == 20.0
    assert dossier['question_excerpt']['provider_job_id'] == 'stt-observed'
    invalid = copy.deepcopy(selected)
    invalid['question_quote_id'] = 'a999'
    with pytest.raises(ValueError, match='question inconnu'):
        pipeline.checked_answer(invalid, native, transcript, EXTERNAL)
    # Selecting a valid question never bypasses the audio/school source boundary.
    invalid = copy.deepcopy(selected)
    invalid['scenes'][0]['source_ids'] = ['native-copy', 'native-rubric']
    with pytest.raises(ValueError, match='première séquence doit citer le vocal'):
        pipeline.checked_answer(invalid, native, transcript, EXTERNAL)


def test_question_catalog_keeps_raw_provider_utterance_as_its_source(case):
    native = pipeline.NativeCase.model_validate(case)
    utterance = 'Pourquoi perd-il un point ?'
    transcript = {'provider': 'Gladia', 'job_id': 'stt-observed',
                  'text': 'Provider full transcript has a different punctuation representation.',
                  'utterances': [{'text': utterance, 'start': 1.2, 'end': 3.4}]}
    result = selected_answer('A retyped question must not be used.')
    result['question_quote_id'] = 'a001'
    assert pipeline.checked_answer(result, native, transcript, EXTERNAL)['question'] == utterance
    assert pipeline.question_catalog(transcript)['a001']['text'] == utterance


def test_failed_native_resume_uses_same_job_and_frozen_cache_without_provider_calls(case, tmp_path, isolated):
    from pathlib import Path
    exported = _native_export_case(case, tmp_path)
    calls = []
    initial = services(calls, dossier=selected_answer())
    def fail_render(dossier, folder):
        raise RuntimeError('temporary rendering failure')
    initial.render = fail_render
    failed = pipeline.schedule(exported, services=initial, background=False)
    assert failed['status'] == 'failed'
    original_trigger = copy.deepcopy(failed['trigger'])
    original_answers = copy.deepcopy(failed['h_answers'])
    # These original paths can legitimately expire after Preview closes.
    for source in exported['sources']:
        Path(source['provenance']['path']).unlink()
        Path(source['provenance']['native_storage']['path']).unlink()
    Path(exported['parent_audio']['path']).unlink()
    Path(exported['context']['database_path']).unlink()
    selected = selected_answer('This deliberately retyped question should be replaced.')
    selected['question_quote_id'] = 'a001'
    resumed = services(calls, dossier=selected)
    def forbidden(*args, **kwargs):
        pytest.fail('Resume must not call Gladia or Linkup again')
    resumed.transcribe = resumed.search = forbidden
    result = pipeline.resume_failed(failed['id'], services=resumed, background=False)
    assert result['id'] == failed['id'] and result['status'] == 'ready'
    assert result['trigger'] == original_trigger
    assert result['h_answers'][:1] == original_answers
    assert len(result['h_answers']) == 2
    assert result['resume_history'][0]['previous_error'] == 'temporary rendering failure'
    assert result['dossier']['question'] == 'Pourquoi perd-il un point ?'
    assert [name for name, _ in calls].count('gladia') == 1
    assert [name for name, _ in calls].count('linkup') == 1
    assert [event['stage'] for event in result['events']].count('observer') == 1
    assert [event['stage'] for event in result['events']].count('resume') == 1
    assert result['dossier']['question_excerpt']['provider_job_id'] == 'stt-test'
    with pytest.raises(ValueError, match='échouée'):
        pipeline.resume_failed(result['id'], services=resumed, background=False)


@pytest.mark.parametrize('target', ['school', 'audio'])
def test_resume_rejects_changed_frozen_bytes_before_h(case, isolated, target):
    calls = []
    initial = services(calls, dossier=selected_answer())
    initial.render = lambda *args: (_ for _ in ()).throw(RuntimeError('render failed'))
    failed = pipeline.schedule(case, services=initial, background=False)
    folder = isolated / failed['id']
    filename = failed['captured_audio'] if target == 'audio' else failed['captured_sources'][0]['file']
    (folder / filename).write_bytes(b'tampered frozen input')
    with pytest.raises(ValueError, match='(changé|correspond pas)'):
        pipeline.resume_failed(failed['id'], services=services(calls), background=False)
    assert [name for name, _ in calls].count('h') == 1
    assert engine.JOBS[failed['id']]['status'] == 'failed'
    assert not engine.JOBS[failed['id']].get('resume_history')


def test_resume_requires_existing_cached_results_and_all_three_new_h_tools(case, isolated):
    calls = []
    initial = services(calls, dossier=selected_answer())
    initial.render = lambda *args: (_ for _ in ()).throw(RuntimeError('render failed'))
    failed = pipeline.schedule(case, services=initial, background=False)
    class SkippingClient:
        def start_session(self, **kwargs):
            tools = {tool.__name__: tool for tool in kwargs['tools']}
            tools['read_native_documents']()
            return SimpleNamespace(id='h-skipped-cached-tools',
                                   wait_for_completion=lambda **kwargs: SimpleNamespace(status='idle', answer=selected_answer()),
                                   cancel=lambda: None)
    resumed = services(calls)
    resumed.client_factory = SkippingClient
    rejected = pipeline.resume_failed(failed['id'], services=resumed, background=False)
    assert rejected['status'] == 'failed' and 'utilisé Gladia et Linkup' in rejected['error']
    engine.JOBS[failed['id']]['search'] = None
    with pytest.raises(ValueError, match='déjà collectées'):
        pipeline.resume_failed(failed['id'], services=services(calls), background=False)


@pytest.mark.parametrize('field', ['summary', 'claim', 'title', 'body', 'narration'])
def test_french_quality_rejects_cjk_in_generated_fields(case, field):
    dossier = selected_answer()
    if field == 'summary':
        dossier['summary'] += ' 是啊'
    elif field == 'claim':
        dossier['evidence'][0]['claim'] += ' 是啊'
    else:
        dossier['scenes'][0][field] += ' 是啊'
    with pytest.raises(ValueError, match='CJK'):
        pipeline.checked_answer(dossier, pipeline.NativeCase.model_validate(case),
                                {'text': 'Pourquoi perd-il un point ?'}, EXTERNAL)


@pytest.mark.parametrize('phrase', ['conclusion réduite', 'phrase réduite', 'la réduite du raisonnement',
                                    'la réduite complète', 's’entraîner à la réduite'])
def test_french_quality_rejects_misnamed_written_reasoning_criteria(phrase):
    dossier = answer()
    dossier['scenes'][2]['narration'] = 'Il faut retravailler ' + phrase + '.'
    with pytest.raises(ValueError, match='conclusion rédigée.*phrase rédigée.*rédaction du raisonnement'):
        pipeline.validate_french_dossier(dossier)


def test_french_quality_accepts_reduced_geometry_and_preserves_raw_source_text():
    dossier = answer()
    dossier['summary'] = 'La figure réduite conserve les angles ; sa taille est réduite.'
    dossier['scenes'][2]['narration'] = 'Écrire une conclusion rédigée et une phrase rédigée clarifie la rédaction du raisonnement.'
    dossier['evidence'][0]['quote'] = '原文 de la source : le contrôleur éditorial ne réécrit pas les citations.'
    assert pipeline.validate_french_dossier(dossier) is dossier


def test_quality_revision_withdraws_bad_ready_media_but_preserves_history_and_cache(case, isolated):
    calls = []
    first = pipeline.schedule(case, services=services(calls, dossier=selected_answer()), background=False)
    job = engine.JOBS[first['id']]
    original_trigger = copy.deepcopy(job['trigger'])
    original_manifest = copy.deepcopy(job['source_manifest'])
    # Legacy ready output generated before the new narrow editorial guard.
    job['dossier']['summary'] += ' 是啊'
    job['h_answers'][-1]['answer']['summary'] += ' 是啊'
    old_answers = copy.deepcopy(job['h_answers'])
    engine.save(job)
    folder = isolated / first['id']
    (folder / 'dossier.json').write_text(__import__('json').dumps(job['dossier']))
    (folder / 'captions.vtt').write_text('WEBVTT\n\nancienne conclusion réduite')
    baseline_calls = len(calls)
    invalid = pipeline.invalidate_ready_for_revision(first['id'])
    assert invalid['status'] == 'failed' and 'CJK' in invalid['error']
    assert len(calls) == baseline_calls
    assert invalid['trigger'] == original_trigger and invalid['source_manifest'] == original_manifest
    assert invalid['h_answers'] == old_answers
    assert not any(key in invalid for key in ('video', 'duration', 'dossier', 'captions', 'completed_at'))
    assert not (folder / 'capsule.mp4').exists() and not (folder / 'dossier.json').exists()
    archive = folder / 'revisions/001'
    assert (archive / 'capsule.mp4').read_bytes() == b'test render'
    assert '是啊' in invalid['quality_revision_history'][0]['dossier']['summary']
    assert [event['stage'] for event in invalid['events']].count('observer') == 1
    selected = selected_answer('Retyped question is replaced by its source ID')
    selected['question_quote_id'] = 'a001'
    resumed = services(calls, dossier=selected)
    resumed.transcribe = resumed.search = lambda *args: pytest.fail('No new Gladia or Linkup API on editorial correction')
    result = pipeline.resume_failed(first['id'], services=resumed, background=False)
    assert result['status'] == 'ready' and result['id'] == first['id']
    assert result['h_answers'][:1] == old_answers
    assert (archive / 'capsule.mp4').read_bytes() == b'test render'
    assert len(result['quality_revision_history']) == 1
    assert [name for name, _ in calls].count('gladia') == 1
    assert [name for name, _ in calls].count('linkup') == 1


def test_quality_revision_leaves_a_valid_ready_dossier_unchanged(case, isolated):
    result = pipeline.schedule(case, services=services([], dossier=selected_answer()), background=False)
    unchanged = pipeline.invalidate_ready_for_revision(result['id'])
    assert unchanged == result
    assert (isolated / result['id'] / 'capsule.mp4').exists()
    assert not (isolated / result['id'] / 'revisions').exists()


def test_nullable_agent_question_with_selected_utterance_is_valid_and_canonical(case):
    value = selected_answer()
    value.update(question=None, question_quote_id='a001')
    selected = pipeline.NativeAgentDossier.model_validate(value)
    assert selected.question is None and selected.question_quote_id == 'a001'
    result = pipeline.checked_answer(selected, pipeline.NativeCase.model_validate(case),
                                     {'text': 'Pourquoi perd-il un point ?', 'utterances': [
                                         {'text': 'Pourquoi perd-il un point ?', 'start': 1.2, 'end': 3.4}]}, EXTERNAL)
    assert result['question'] == 'Pourquoi perd-il un point ?'
    assert result['question_excerpt']['start'] == 1.2
    missing = copy.deepcopy(value)
    missing['question_quote_id'] = None
    with pytest.raises(ValueError, match='question_quote_id'):
        pipeline.NativeAgentDossier.model_validate(missing)
    with pytest.raises(ValueError, match='question_quote_id'):
        pipeline.checked_answer(missing, pipeline.NativeCase.model_validate(case),
                                {'text': 'Pourquoi perd-il un point ?'}, EXTERNAL)
