"""Modern teacher workspace with explicit, source-preserving local demo data.

The native connector status is shown separately. Reading a native window does not
turn this teaching example into synchronised PRONOTE records.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import re
import unicodedata

from .engine import DATA, FIXTURE, JOBS, LOCK, launch, save, snapshot, job_created_timestamp

STATE = DATA / 'new-pronote-workspace.json'
ROLES = {'copie': 'copy', 'bareme': 'rubric', 'consigne': 'instructions', 'methode': 'method'}
SOURCE = {
    'kind': 'local_demo',
    'label': 'Dossier de démonstration',
    'detail': 'Données fictives locales. Le dossier d’Alex n’est pas importé depuis PRONOTE.',
    'native_synced': False,
    'editable': False,
}


def _now():
    return datetime.now().astimezone().isoformat()


def _read_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except (ValueError, OSError):
            pass
    return {'appointment_at': (datetime.now().astimezone() + timedelta(hours=2)).isoformat(), 'opens': []}


def _save_state(value):
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(STATE)


def _assessment(copy, rubric):
    """Expose the recorded marks; never infer marks from an agent's summary."""
    def number(raw):
        value = float(raw.replace(',', '.'))
        return int(value) if value.is_integer() else value
    numeric = r'(\d+(?:[,.]\d+)?)'
    total = re.search(r'Note de l’exercice\s*:\s*' + numeric + r'\s*/\s*' + numeric, copy['text'], re.I)
    section = re.search(r'Détail attribué\s*:\s*(.*?)\.\s*Note de l’exercice', copy['text'], re.I)
    criteria = []
    if section:
        for raw in section.group(1).split(';'):
            match = re.fullmatch(r'\s*(.+?)\s+' + numeric + r'\s*/\s*' + numeric + r'\s*', raw)
            if not match:
                continue
            label, score, maximum = match.groups()
            identifier = unicodedata.normalize('NFKD', label).encode('ascii', 'ignore').decode().replace(' ', '-')
            criteria.append({'id': identifier, 'label': label[0].upper() + label[1:],
                             'score': number(score), 'maximum': number(maximum),
                             'source_id': copy['id'], 'quote': raw.strip()})
    score, maximum = (number(total.group(1)), number(total.group(2))) if total else (None, None)
    rubric_points = [number(raw) for raw in re.findall(r':\s*' + numeric + r'\s*points?\b', rubric['text'], re.I)]
    issues = []
    if total is None:
        issues.append('Aucune note d’exercice lisible dans la copie.')
    if total and criteria and (sum(c['score'] for c in criteria) != score or sum(c['maximum'] for c in criteria) != maximum):
        issues.append('Le détail des critères ne correspond pas au total inscrit sur la copie.')
    if total and rubric_points and sum(rubric_points) != maximum:
        issues.append('Le total du barème ne correspond pas au maximum inscrit sur la copie.')
    if any(c['score'] < 0 or c['score'] > c['maximum'] for c in criteria):
        issues.append('Un critère contient une valeur incohérente.')
    return {'label': 'Exercice 2 · Pythagore', 'score': score, 'maximum': maximum,
            'source_id': copy['id'], 'scope': 'exercise', 'criteria': criteria,
            'quote': total.group(0) if total else None, 'consistent': not issues, 'issues': issues,
            'rubric_source_id': rubric['id'], 'rubric_maximum': sum(rubric_points) if rubric_points else None}


def get_document(document_id):
    document = next((deepcopy(d) for d in FIXTURE['documents'] if d['id'] == document_id), None)
    if document is None:
        raise ValueError('Document inconnu')
    document.update(
        role=ROLES[document_id],
        source=deepcopy(SOURCE),
        source_locator='fixture:alex/documents/' + document_id,
        content_hash=hashlib.sha256(document['text'].encode()).hexdigest(),
        href='/api/workspace/documents/' + document_id,
        open_href='/api/workspace/documents/' + document_id + '/open',
    )
    if document_id == 'copie':
        rubric = next(d for d in FIXTURE['documents'] if d['id'] == 'bareme')
        document['assessment'] = _assessment(document, rubric)
        for field, prefix in (('written_answer', 'Réponse écrite'), ('annotation', 'Annotation')):
            match = re.search(prefix + r'\s*:\s*«\s*(.*?)\s*»', document['text'])
            document[field] = match.group(1) if match else None
    return document


def _connection():
    from .native_bridge import context
    native = context()
    return {
        'state': native.get('connection_state', native.get('state', 'not_connected')),
        'app_name': native.get('app_name', 'PRONOTE Mac'),
        'window_title': native.get('window_title', ''),
        'observed_at': native.get('observed_at'),
        'context_id': native.get('context_id'),
        'method': native.get('method'),
        'native_synced': False,
        'label': 'Contexte PRONOTE détecté' if native.get('state') == 'observed' else 'PRONOTE non relié',
        'detail': 'Le connecteur natif lit le contexte de l’application. Les données pédagogiques de ce dossier restent locales.',
        'href': '/native',
    }


def _agent_state(state):
    associated = {item.get('job_id') for item in state['opens'] if item.get('job_id')}
    reports, actions = [], []
    for job in list(JOBS.values()):
        if job['id'] not in associated and job.get('workspace_origin') != 'new_pronote':
            continue
        dossier = job.get('dossier') or {}
        input_documents = {d['id']: d for d in job.get('input_context', {}).get('documents', [])}
        cited_ids = sorted({source_id for entry in dossier.get('evidence', []) + dossier.get('scenes', []) for source_id in entry.get('source_ids', [])})
        reports.append({
            'id': job['id'], 'status': job['status'], 'mode': job['mode'],
            'scenario': job['scenario'], 'question': dossier.get('question'),
            'summary': dossier.get('summary'), 'created_at': job['created_at'],
            'kept': bool(job.get('kept')), 'dismissed': bool(job.get('notification_dismissed')),
            'approved': bool(job.get('approved')), 'video': job.get('video'),
            'href': '/api/jobs/' + job['id'], 'source_kind': 'local_demo',
            'source_ids': cited_ids, 'appointment': job.get('input_context', {}).get('appointment'),
            'document_hashes': {key: hashlib.sha256(value['text'].encode()).hexdigest() for key, value in input_documents.items()},
        })
        for index, event in enumerate(job.get('events', [])):
            stage = event['stage']
            source_ids = {
                'observer': ['copie'], 'gladia': ['audio'],
                'video': cited_ids,
                'validation': [entry['id'] for entry in job.get('input_context', {}).get('documents', [])],
                'linkup': [source['id'] for source in job.get('search', {}).get('sources', [])],
            }.get(stage, [])
            if stage == 'navigation':
                viewed_id = event['text'].split(':')[-1].strip()
                source_ids = [viewed_id] if viewed_id in input_documents else []
            actions.append({
                'id': job['id'] + ':' + str(index), 'job_id': job['id'],
                'stage': stage, 'text': event['text'], 'at': event['time'],
                'source_ids': source_ids, 'href': '/api/jobs/' + job['id'],
                'provider': {'gladia': 'Gladia', 'linkup': 'Linkup', 'h': 'H Company', 'navigation': 'H Company', 'video': 'DemoBro' if job.get('video_provider') == 'demobro' else 'Python + FFmpeg'}.get(stage, 'Calli'),
                'execution': 'live' if job['mode'] == 'live' else 'scripted_demo',
                'query': event.get('query'),
            })
    return {
        'reports': sorted(reports, key=lambda report: (job_created_timestamp(report), report['id']), reverse=True),
        'actions': sorted(actions, key=lambda e: e['at'], reverse=True),
        'latest_job_id': next((item.get('job_id') for item in reversed(state['opens']) if item.get('job_id')), None),
        'open_history': list(reversed(state['opens'][-20:])),
    }


def get_workspace():
    with LOCK:
        state = _read_state()
        if not STATE.exists():
            _save_state(state)
        docs = [get_document(d['id']) for d in FIXTURE['documents']]
        student = deepcopy(FIXTURE['student'])
        student.update(initials=''.join(part[0] for part in student['name'].split())[:2], document_ids=[d['id'] for d in docs], source=deepcopy(SOURCE),
                       assessment=deepcopy(next(d for d in docs if d['id'] == 'copie')['assessment']))
        meeting = deepcopy(FIXTURE['appointment'])
        meeting.update(at=state['appointment_at'], student_id=student['id'], title='Parents d’Alex Martin',
                       source=deepcopy(SOURCE), document_ids=['copie', 'bareme', 'consigne'])
        inbox = [dict(deepcopy(message), student_id=student['id'], thread_id='famille-martin', source=deepcopy(SOURCE)) for message in FIXTURE['messages']]
        for message in inbox:
            message['subject'] = 'Rendez-vous · contrôle de mathématiques'
            message['unread'] = message['id'] == 'msg-2'
        inbox[1]['audio'] = {'scenario': 'points', 'url': '/audio/points', 'label': 'Question des parents', 'source_kind': 'attached_test_dossier'}
        return {
            'name': 'New PRONOTE',
            'school': {'name': 'Collège des Tilleuls', 'year': '2026–2027', 'source': 'local_demo'},
            'teacher': {'name': student['teacher'], 'initials': 'ML', 'subject': student['subject']},
            'source': deepcopy(SOURCE), 'connection': _connection(),
            'agenda': [meeting], 'inbox': inbox, 'students': [student],
            'classes': [{'id': '4e-b', 'name': student['class'], 'subject': student['subject'], 'student_ids': [student['id']], 'sample_count': 1, 'source': deepcopy(SOURCE)}],
            'documents': docs, 'agent': _agent_state(state),
            'voice_options': [{'id': 'points', 'label': 'Comprendre les points perdus', 'url': '/audio/points'}, {'id': 'progress', 'label': 'Préparer la progression', 'url': '/audio/progress'}],
            'server_time': _now(),
            'capabilities': {'read_documents': True, 'auto_prepare_on_open': True, 'keep_dismiss': True, 'approve_capsule': True, 'write_native': False, 'sync_grades': False},
        }


def open_document(document_id, voice='points', mode='live', retry=False, video_provider='local', teacher_assessment=None):
    """Opening the copy is the trigger; no teacher prompt is passed to the agent."""
    document = get_document(document_id)
    if voice not in FIXTURE['audio']:
        raise ValueError('Vocal inconnu')
    if mode not in ('demo', 'live'):
        raise ValueError('Mode inconnu')
    if video_provider not in ('local', 'demobro'):
        raise ValueError('Rendu vidéo inconnu')
    with LOCK:
        state = _read_state()
        # The appointment is persisted even if the copy is opened before the
        # first GET /workspace, and shared with the worker before it starts.
        input_context = deepcopy(FIXTURE)
        input_context['appointment']['at'] = state['appointment_at']
        input_context['source'] = deepcopy(SOURCE)
        if teacher_assessment is not None:
            from .teacher_assessment import bind_teacher_assessment
            input_context = bind_teacher_assessment(input_context, teacher_assessment)
        preparation = launch(voice, mode, 'http://127.0.0.1:8000', retry, video_provider, input_context=input_context) if document_id == 'copie' else None
        action = {
            'document_id': document_id, 'source_locator': document['source_locator'],
            'content_hash': document['content_hash'], 'opened_at': _now(),
            'trigger': 'modern_copy_opened' if preparation else 'document_opened',
            'source_kind': 'local_demo', 'native_synced': False,
            'job_id': preparation['id'] if preparation else None, 'voice': voice,
        }
        state['opens'].append(action)
        state['opens'] = state['opens'][-100:]
        _save_state(state)
        if preparation:
            job = JOBS[preparation['id']]
            job['workspace_origin'] = 'new_pronote'
            job['workspace_trigger'] = action
            job['source_provenance'] = deepcopy(SOURCE)
            save(job)
            preparation = snapshot(job['id'])
    return {'document': document, 'preparation': preparation, 'action': action}
