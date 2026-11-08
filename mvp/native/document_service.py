"""Observe verified PRONOTE attachments without desktop access or UI input.

Only a newly observed native document viewer can produce a job. An import
manifest is a prerequisite, not an opening event. Teacher prompts and browser
fixtures are never used as substitutes for the native evidence.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .native_documents import (AttachmentRegistry, DocumentOpenDetector, read_window_snapshot,
                               read_export_snapshot)
from .prepare_demo import DATA

MANIFEST = DATA / 'native-attachments.json'
STATE = DATA / 'native-document-observer.json'
EVENTS = DATA / 'native-document-openings.json'
LOCK = threading.RLock()
STOP = threading.Event()
THREAD = None


def now():
    return datetime.now(timezone.utc).isoformat()


def write(value):
    with LOCK:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        temp = STATE.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temp.replace(STATE)


def status():
    with LOCK:
        value = json.loads(STATE.read_text()) if STATE.exists() else {
            'state': 'waiting_for_import',
            'message': 'La copie et le barème doivent être importés puis vérifiés dans le vrai PRONOTE.',
        }
        value.update(active=bool(THREAD and THREAD.is_alive()), desktop_access=False,
                     manifest_available=MANIFEST.is_file())
        return value


def validate_database(snapshot, manifest):
    """Bind document observations to the explicitly configured, open .not base."""
    path = Path(manifest.get('database_path', '')).expanduser()
    if not path.is_absolute() or not path.is_file() or path.suffix.casefold() != '.not':
        raise ValueError('La base PRONOTE locale enregistrée est absente.')
    names = [window.get('title', '').casefold() for window in snapshot.get('windows', [])
             if window.get('process', '').casefold() in ('pronote monoposte.exe', 'client pronote.exe')]
    if not any(path.name.casefold() in title for title in names):
        raise ValueError('La base ouverte ne correspond pas au dossier de pièces enregistré.')
    if not manifest.get('dossier_id') or not manifest.get('native_context_id'):
        raise ValueError('Le dossier scolaire et son contexte natif doivent être identifiés.')


def poll_once(detector, manifest_path=MANIFEST, *, read=read_window_snapshot, enqueue=None,
              read_exports=read_export_snapshot):
    """A testable single observation; reading registration alone never enqueues."""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        write({'state': 'waiting_for_import', 'observed_at': now(),
               'message': 'En attente de l’import vérifié de la copie et du barème dans PRONOTE.'})
        return []
    registry = AttachmentRegistry.from_file(manifest_path)
    # Verify native import evidence, bytes and paired rubric before any event.
    sources = registry.sources(now())
    snapshot = read()
    validate_database(snapshot, registry.manifest)
    payloads = detector.observe(snapshot, registry, commit=False)
    if 'drive_c' in Path(registry.manifest['database_path']).parts:
        exported = read_exports(registry)
        payloads += detector.observe_exports(snapshot, exported, registry, commit=False)
    # A platform may expose both its own viewer and a native exported document.
    # Preserve the same one-job identity across these observations.
    payloads = list({payload['trigger']['event_id']: payload for payload in payloads}.values())
    if enqueue is None:
        from ..native_pipeline import schedule
        enqueue = schedule
    jobs = []
    for payload in payloads:
        jobs.append(enqueue(payload))
    detector.acknowledge(payloads)
    previous = status()
    value = {'state': 'watching', 'observed_at': snapshot['observed_at'],
             'message': 'Lecture native de fond active. L’ouverture de la copie déclenche H et la vidéo.',
             'sources': [{'id': source['id'], 'role': source['role'], 'title': source['title'],
                          'sha256': source['sha256']} for source in sources],
             'dossier_id': registry.manifest['dossier_id'], 'database': Path(registry.manifest['database_path']).name,
             'identity': registry.manifest.get('identity', {}),
             'opening_methods': ['win32_document_windows', 'native_export_file_open'],
             'last_job_id': jobs[-1]['id'] if jobs else previous.get('last_job_id')}
    if jobs:
        value.update(state='preparing', message='Copie réellement ouverte dans PRONOTE : H prépare le rapport et la capsule.',
                     last_opened_at=snapshot['observed_at'], trigger=payloads[-1]['trigger'])
    write(value)
    return jobs


def start():
    global THREAD
    with LOCK:
        if THREAD and THREAD.is_alive():
            return status()
        STOP.clear()
        def worker():
            detector = DocumentOpenDetector(EVENTS)
            while not STOP.is_set():
                try:
                    poll_once(detector)
                except Exception as error:
                    previous = status()
                    write({**previous, 'state': 'blocked', 'observed_at': now(),
                           'message': 'La lecture native attend une vérification des pièces ou de la base.',
                           'error': str(error)[:500]})
                STOP.wait(2)
        THREAD = threading.Thread(target=worker, name='pronote-native-document-observer', daemon=True)
        THREAD.start()
        return status()


def stop():
    STOP.set()
