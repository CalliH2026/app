"""Optional Calli appreciations module, mounted at /calli when the server is configured for it.

Calli (github.com/wilfred-dore/calligraphe) dictates report-card comments, queues them behind its identity guards
and lets its writer enter them in the native PRONOTE client, reading each cell back. This module only mounts
Calli's own ASGI app; Calli keeps its Host/Origin checks, JSON-only POSTs, WebSocket origin check, STOP and journal.
Nothing is configured from the browser. Without CALLI_SOURCE the upstream app starts unchanged; with PUBLIC_URL
(shared hosting) the module is never mounted.

Server configuration (environment):
  CALLI_SOURCE         path to a Calli checkout (contains ui/app.py)
  CALLI_QUEUE          live queue file shared with Calli's writer
  CALLI_ROSTER         native roster CSV (student_id, display_name, aliases)
  CALLI_COURSE         exact class · subject · period of that roster, as Calli stores it
  CALLI_JOURNAL        optional journal to show (default: Calli's latest run journal next to the queue)
  CALLI_WORKSPACE_DIR  optional Calli workspace state directory
Dictation uses Calli's Gladia path only if GLADIA_API_KEY is set in this server's environment.
"""
import os
import sys
from pathlib import Path

from fastapi import APIRouter, Request

PREFIX = '/calli'
EMBED_URL = PREFIX + '/workspace?embed=1'
REQUIRED = ('CALLI_QUEUE', 'CALLI_ROSTER', 'CALLI_COURSE')
TEACHER_MESSAGE = 'Le module Appréciations n’est pas activé sur ce serveur.'
UNCONFIGURED = {'available': False, 'reason': TEACHER_MESSAGE, 'detail': 'CALLI_SOURCE absent.'}
router = APIRouter()


@router.get('/api/calli/status')
def status(request: Request):
    # "available" means the module is mounted; whether a writer is running and what it verified is shown inside it.
    return dict(getattr(request.app.state, 'calli_status', UNCONFIGURED))


def _unavailable(detail):
    # The teacher sees one plain sentence; the technical cause is kept for the collapsed details.
    return {'available': False, 'reason': TEACHER_MESSAGE, 'detail': detail}


def mount(app, env=None):
    """Mount the local native workspace from server-owned configuration, or describe its unavailability.

    PUBLIC_URL always disables this mount because the native queue has no remote authentication.
    Mounting exposes the UI and its queue endpoints; it does not launch a native writer.
    """
    env = os.environ if env is None else env
    if env.get('PUBLIC_URL', '').strip():
        # Calli's queue drives a local writer and has no remote authentication: never expose it on shared hosting.
        return _unavailable('Module Calli désactivé : ce serveur est publié (PUBLIC_URL).')
    source = env.get('CALLI_SOURCE', '').strip()
    if not source:
        return dict(UNCONFIGURED)
    missing = [name for name in REQUIRED if not env.get(name, '').strip()]
    if missing:
        return _unavailable('Configuration Calli incomplète : ' + ', '.join(missing) + '.')
    root = Path(source).expanduser().resolve()
    if not (root / 'ui' / 'app.py').is_file():
        return _unavailable('CALLI_SOURCE ne désigne pas une copie de Calli.')
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from ui.app import create_app
        from ui.dictation import speech_availability
    except Exception as exc:
        return _unavailable(f'Calli ne peut pas être chargé ({type(exc).__name__}).')
    optional = {key: Path(env[name]) for key, name in (('journal_path', 'CALLI_JOURNAL'), ('workspace_dir', 'CALLI_WORKSPACE_DIR'))
                if env.get(name, '').strip()}
    try:
        calli = create_app(queue_path=Path(env['CALLI_QUEUE']), roster_path=Path(env['CALLI_ROSTER']),
                           course=env['CALLI_COURSE'].strip(), **optional)
    except Exception as exc:
        return _unavailable(f'Calli ne peut pas démarrer avec cette configuration ({type(exc).__name__}).')
    app.mount(PREFIX, calli)
    dictation = speech_availability(None)
    return {'available': True, 'url': EMBED_URL, 'course': env['CALLI_COURSE'].strip(),
            'dictation_available': dictation['available'], 'dictation_reason': dictation['reason']}


def install(app, env=None):
    app.include_router(router)
    app.state.calli_status = mount(app, env)
    return dict(app.state.calli_status)
