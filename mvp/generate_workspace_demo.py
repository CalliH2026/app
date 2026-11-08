"""Film New PRONOTE through DemoBro using an isolated replay of one real job.

Prepare only (no network): python -m mvp.generate_workspace_demo --job-id ID
Local preview: add --serve. Private DemoBro film: add --render explicitly.

Only the fictional school workspace, its recorded provider trace and its local
media are exposed. Nothing proxies the real app, credentials or native PRONOTE.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import mimetypes
import re
import select
import shutil
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

from .demobro import DemoBro, account_headers
from .tool_calls import summarize_tool_calls

ROOT = Path(__file__).parent.resolve()
FILM_JOB = 'workspace-film'
REPLAY_NOTE = 'Données fictives · relecture d’une exécution réelle H + Gladia + Linkup. Temps condensé.'
PRINT_LOCK = threading.Lock()
TOOL_REPLAY_SECONDS = 24
PRIVATE_METADATA = {'session_id', 'session_ids', 'validation_session_ids', 'job_id',
                    'render_id', 'validated_dossier_id', 'caller_id', 'request_id',
                    'access_token', 'refresh_token', 'authorization', 'api_key'}


def log(message):
    with PRINT_LOCK:
        print(message, flush=True)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_ready_job(job_id):
    if not re.fullmatch(r'[a-f0-9]{12}', job_id):
        raise ValueError('A local 12-character job ID is required.')
    folder = ROOT / 'data' / job_id
    job = json.loads((folder / 'state.json').read_text())
    if job.get('status') != 'ready' or job.get('mode') != 'live':
        raise ValueError('The source job must be a completed connected run, never an offline dossier.')
    if job.get('scenario') not in ('points', 'progress'):
        raise ValueError('Only the two known fictional parent recordings may be filmed.')
    if job.get('workspace_origin') != 'new_pronote' and job.get('source_kind') != 'pronote_modern_dossier':
        raise ValueError('The run must have been triggered from New PRONOTE.')
    if not job.get('session_id') or job.get('transcription', {}).get('provider') != 'Gladia' or job.get('search', {}).get('provider') != 'Linkup':
        raise ValueError('The recorded H, Gladia and Linkup execution evidence is incomplete.')
    if job.get('video_provider', 'local') != 'local':
        raise ValueError('Use the real locally generated capsule for the product film.')
    fixture = json.loads((ROOT / 'fixtures/alex.json').read_text())
    expected = {doc['id']: doc['text'] for doc in fixture['documents']}
    actual = {doc['id']: doc.get('text') for doc in job.get('dossier', {}).get('sources', []) if doc.get('id') in expected}
    if actual != expected:
        raise ValueError('The dossier is not the explicit fictional school corpus; refusing public exposure.')
    if not (folder / 'capsule.mp4').is_file():
        raise ValueError('The actual capsule MP4 is missing.')
    for event in job.get('events', []):
        if event.get('stage') == 'error':
            raise ValueError('Use a completed run without unresolved provider errors.')
    return job, fixture, folder


def clean_job(original):
    """An explicit field allowlist drops API sessions, native paths and secrets."""
    allowed = ('scenario', 'mode', 'status', 'video_provider', 'created_at', 'completed_at',
               'duration', 'transcription', 'search', 'dossier')
    job = {name: copy.deepcopy(original[name]) for name in allowed if name in original}
    job.update(id=FILM_JOB, approved=False, kept=False, decision=None,
               notification_dismissed=False, video=f'/outputs/{FILM_JOB}/capsule.mp4',
               captions=f'/outputs/{FILM_JOB}/captions.vtt' if original.get('captions') else None)
    job['events'] = [{name: event[name] for name in ('time', 'stage', 'text', 'query') if name in event}
                     for event in original['events']]
    # The film only publishes the known fixture documents and public references.
    dossier = job['dossier']
    dossier_allowed = ('question', 'intent', 'summary', 'evidence', 'unknowns', 'scenes', 'mode', 'display_label')
    safe_dossier = {name: dossier[name] for name in dossier_allowed if name in dossier}
    safe_dossier['sources'] = [{name: source[name] for name in ('id', 'title', 'type', 'text', 'url', 'excerpt') if name in source}
                               for source in dossier['sources']]
    safe_dossier['transcription'] = job['transcription']
    job['dossier'] = safe_dossier
    if isinstance(original.get('tool_calls'), list):
        public_fields = ('id', 'name', 'kind', 'status', 'started_at', 'ended_at',
                         'duration_ms', 'arguments', 'result_summary', 'cached')
        job['tool_calls'] = [{field: copy.deepcopy(call[field]) for field in public_fields if field in call}
                             for call in original['tool_calls']
                             if isinstance(call, dict) and call.get('kind') == 'custom']
        job['tool_call_summary'] = summarize_tool_calls(job)
    # Provider IDs can also occur in transcription payloads or JSON previews.
    # Keep source IDs/quote IDs, while removing account/session/render metadata.
    private_values = set()
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in PRIVATE_METADATA:
                    values = item if isinstance(item, list) else [item]
                    private_values.update(part for part in values if isinstance(part, str) and len(part) > 5)
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(original)
    def public(value):
        if isinstance(value, dict):
            return {key: public(item) for key, item in value.items() if key not in PRIVATE_METADATA}
        if isinstance(value, list):
            return [public(item) for item in value]
        if isinstance(value, str):
            value = value.replace(original.get('id', FILM_JOB), FILM_JOB)
            for identifier in sorted(private_values, key=len, reverse=True):
                value = value.replace(identifier, '[identifiant retiré]')
            return value
        return value
    return public(job)


def recorded_timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def replay_tool_calls(original, elapsed):
    """Reveal only recorded calls whose actual start precedes the replay clock."""
    calls = original.get('tool_calls', [])
    starts = [stamp for call in calls if (stamp := recorded_timestamp(call.get('started_at'))) is not None]
    if not starts:
        return []
    origin = recorded_timestamp(original.get('created_at'))
    origin = min(starts) if origin is None else min(origin, min(starts))
    ends = [stamp for call in calls if (stamp := recorded_timestamp(call.get('ended_at'))) is not None]
    end = max(starts + ends)
    virtual_now = origin + max(0, elapsed) * max(1, end - origin) / TOOL_REPLAY_SECONDS
    visible = []
    for original_call in calls:
        start = recorded_timestamp(original_call.get('started_at'))
        if start is None or start > virtual_now:
            continue
        call = copy.deepcopy(original_call)
        finished = recorded_timestamp(call.get('ended_at'))
        if finished is None or finished > virtual_now:
            call.update(status='running', ended_at=None, duration_ms=None,
                        result_summary='', cached=False)
        visible.append(call)
    return visible


def freeze_snapshot(job_id, output):
    """Copy exactly the frontend and fictional media needed by this replay."""
    source, fixture, folder = load_ready_job(job_id)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / 'snapshot-manifest.json'
    if (output / 'submission.json').exists():
        existing = json.loads(manifest_path.read_text())
        if existing['source_job_id'] != job_id:
            raise ValueError('This output folder already belongs to a different submitted film.')
        return existing
    static = output / 'snapshot-static'
    media = output / 'snapshot-media'
    if static.exists():
        shutil.rmtree(static)
    static.mkdir()
    media.mkdir(exist_ok=True)
    for name in ('workspace.html', 'workspace.js', 'workspace.css', 'management.js', 'outings.js', 'outings.css',
                 'background.js', 'background.css', 'native-preparation.js', 'native-preparation.css',
                 'sponsors.js', 'sponsors.css',
                 'parallel-symbol.svg', 'parallel-symbol-white.svg', 'parallel-logo.svg', 'parallel-logo-white.svg'):
        shutil.copy2(ROOT / 'static' / name, static / name)
    shutil.copytree(ROOT / 'static/h-kit', static / 'h-kit')
    shutil.copytree(ROOT / 'static/sponsors', static / 'sponsors')
    shutil.copy2(folder / 'capsule.mp4', media / 'capsule.mp4')
    if source.get('captions'):
        shutil.copy2(folder / 'captions.vtt', media / 'captions.vtt')
    for scenario in ('points', 'progress'):
        shutil.copy2(ROOT / 'fixtures' / fixture['audio'][scenario]['file'], media / f'parent-{scenario}.wav')
    # Build the actual workspace contract, then remove all native connection data,
    # prior reports and imported voice options before anything is served.
    from .workspace import get_workspace
    workspace = copy.deepcopy(get_workspace())
    workspace['source'].update(detail='Dossier fictif local. Relecture condensée d’une préparation connectée enregistrée.',
                               native_synced=False)
    workspace['connection'] = {
        'state': 'replay', 'app_name': 'New PRONOTE', 'window_title': '',
        'native_synced': False, 'label': 'Démonstration de l’interface moderne',
        'detail': 'Ce film ne montre pas une synchronisation avec le client natif PRONOTE.', 'href': '#',
    }
    workspace['agent'] = {'reports': [], 'actions': [], 'latest_job_id': None, 'open_history': []}
    workspace['voice_options'] = [option for option in workspace['voice_options'] if option['id'] in ('points', 'progress')]
    safe_job = clean_job(source)
    write_json(output / 'snapshot-workspace.json', workspace)
    write_json(output / 'snapshot-job.json', safe_job)
    files = {str(path.relative_to(output)): sha(path)
             for parent in (static, media) for path in sorted(parent.rglob('*')) if path.is_file()}
    files.update({name: sha(output / name) for name in ('snapshot-workspace.json', 'snapshot-job.json')})
    manifest = {'source_job_id': job_id, 'source_created_at': source['created_at'],
                'source_kind': 'local_demo', 'execution': 'recorded_live_run',
                'replay_note': REPLAY_NOTE, 'files': files,
                'actual_actions': len(safe_job['events']),
                'actual_tool_calls': len(safe_job.get('tool_calls', [])), 'duration': source.get('duration')}
    write_json(manifest_path, manifest)
    write_json(output / 'capture-contract.json', {
        'private_render': True, 'public_contents': list(files),
        'mutations': 'Snapshot decisions only, in memory. No live app API is proxied.',
        'recorded_source_job': job_id, 'replay': True,
    })
    return manifest


class Replay:
    def __init__(self, output):
        self.output = output
        self.original = json.loads((output / 'snapshot-job.json').read_text())
        self.workspace = json.loads((output / 'snapshot-workspace.json').read_text())
        self.started = None
        self.phase = 'idle'
        self.kept = False
        self.dismissed = False
        self.approved = False
        self.lock = threading.RLock()

    def start(self):
        with self.lock:
            self.started = time.monotonic()
            self.phase = 'working'

    def reset(self):
        with self.lock:
            self.started = None
            self.phase = 'idle'
            self.kept = self.dismissed = self.approved = False

    def job(self):
        with self.lock:
            result = copy.deepcopy(self.original)
            result.update(kept=self.kept, decision='keep' if self.kept else ('dismiss' if self.dismissed else None),
                          notification_dismissed=self.dismissed, approved=self.approved)
            if self.phase != 'ready':
                elapsed = time.monotonic() - self.started if self.started else 0
                if 'tool_calls' in result:
                    result['tool_calls'] = (copy.deepcopy(self.original['tool_calls'])
                                            if self.phase == 'activity' else replay_tool_calls(self.original, elapsed))
                    result['tool_call_summary'] = summarize_tool_calls(result)
                events = result['events']
                # Show the actual recorded event order at a condensed pace. The
                # ready checkpoint is explicit so probes cannot rush the film.
                count = len(events) if self.phase == 'activity' else min(len(events), max(1, round(elapsed / 2) + 1))
                result.update(status='rendering' if self.phase == 'activity' else 'preparing',
                              events=[event for event in events[:count] if event['stage'] != 'ready'])
                hidden = ('video', 'captions', 'duration') if self.phase == 'activity' else ('dossier', 'video', 'captions', 'duration')
                for field in hidden:
                    result.pop(field, None)
                if not any(event['stage'] == 'gladia' and ('reçue' in event['text'] or 'transcrit' in event['text']) for event in result['events']):
                    result.pop('transcription', None)
                if not any(event['stage'] == 'linkup' and 'sources' in event['text'] for event in result['events']):
                    result.pop('search', None)
            return result

    def state(self):
        with self.lock:
            value = copy.deepcopy(self.workspace)
            if self.started is not None:
                job = self.job()
                value['agent']['latest_job_id'] = FILM_JOB
                value['agent']['reports'] = [{name: job.get(name) for name in
                    ('id', 'status', 'mode', 'scenario', 'created_at', 'kept', 'approved', 'video')}
                    | {'question': self.original['dossier']['question'], 'summary': self.original['dossier']['summary']}]
                value['agent']['actions'] = copy.deepcopy(job['events'])
            return value


@contextlib.contextmanager
def snapshot_server(output):
    replay = Replay(output)
    static = (output / 'snapshot-static').resolve()
    media = (output / 'snapshot-media').resolve()
    requests = output / 'requests.jsonl'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def record(self):
            with replay.lock, requests.open('a') as stream:
                stream.write(json.dumps({'at': time.time(), 'method': self.command, 'path': urlparse(self.path).path}) + '\n')

        def reply(self, value, status=200, mime='application/json'):
            body = json.dumps(value, ensure_ascii=False).encode() if mime == 'application/json' else value
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def file(self, path):
            data = path.read_bytes()
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', self.headers.get('Range', ''))
            if match:
                start = int(match[1]); end = min(int(match[2]) if match[2] else len(data) - 1, len(data) - 1)
                if start > end or start >= len(data):
                    self.send_error(416); return
                self.send_response(206)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}')
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers(); self.wfile.write(data[start:end + 1]); return
            self.reply(data, mime=mime)

        def do_GET(self):
            self.record()
            path = urlparse(self.path).path
            if path in ('/', '/film/activity', '/film/ready', '/film/video', '/film/tools', '/film/errors'):
                if path == '/':
                    # Discovery/probing and the actual recorder each begin a
                    # fresh replay, without changing the frozen source job.
                    replay.reset()
                html = (static / 'workspace.html').read_text()
                # Same app functions and markup, with a clearly disclosed replay
                # banner and deterministic state checkpoints for the recorder.
                html = html.replace('Données fictives · les actions de préparation sont réelles en mode connecté.', REPLAY_NOTE)
                html = html.replace('Démonstration partagée · données fictives · préparations réelles en mode connecté.', REPLAY_NOTE)
                bootstrap = "preferences={voice:'" + replay.original['scenario'] + "',mode:'live',video_provider:'local'};"
                if path != '/':
                    with replay.lock:
                        if replay.started is None:
                            replay.start()
                        if path in ('/film/ready', '/film/video', '/film/tools', '/film/errors'):
                            replay.phase = 'ready'
                        else:
                            replay.phase = 'activity'
                    bootstrap += f"current=await api('/api/jobs/{FILM_JOB}');documentId='copie';showPage('{'messages' if path == '/film/activity' else 'document'}');lastSignature='';renderAgent(current);setPanel(true);"
                    bootstrap += ("let bareme=document.querySelector('#agent-content button[data-source=\"bareme\"]');"
                                  "if(bareme)bareme.id='film-bareme-source';"
                                  "let firstError=document.querySelector('.tool-call-item.failed');"
                                  "if(firstError)firstError.id='film-first-error';")
                    if path == '/film/activity':
                        bootstrap += "$ ('agent-content').scrollTop=$('agent-content').scrollHeight;"
                    elif path == '/film/video':
                        bootstrap += "let v=$('agent-video');if(v){v.muted=true;v.scrollIntoView({block:'center'});v.play().catch(()=>{});}"
                    elif path in ('/film/tools', '/film/errors'):
                        selector = '.tool-call-panel' if path == '/film/tools' else '.tool-call-item.failed'
                        bootstrap += ("requestAnimationFrame(()=>{let target=document.querySelector('" + selector + "');"
                                      "if(target)target.scrollIntoView({block:'start',behavior:'instant'});});")
                script = "<script>let replayInit=setInterval(async()=>{if(typeof workspace!=='undefined'&&workspace){clearInterval(replayInit);" + bootstrap + "}},30);</script>"
                html = html.replace('</body>', script + '</body>')
                self.reply(html.encode(), mime='text/html; charset=utf-8'); return
            if path == '/api/workspace':
                self.reply(replay.state()); return
            if path == f'/api/jobs/{FILM_JOB}':
                self.reply(replay.job()); return
            if path == '/api/notifications/status':
                self.reply({'status': 'not_enabled'}); return
            if path == '/api/auth/me':
                self.reply({'user': None, 'required': False}); return
            if path == '/api/calendar/status':
                self.reply({'configured': False, 'connected': False}); return
            if path == '/api/recordings':
                self.reply([]); return
            if path == '/api/pronote/background':
                self.reply({'state': 'stopped', 'active': False, 'actions': [], 'routes': [],
                            'message': 'Connexion distincte du dossier fictif présenté dans ce film.'}); return
            if path == '/api/native/documents':
                self.reply({'state': 'disconnected', 'preparation': None}); return
            if path.startswith('/api/workspace/documents/'):
                identifier = path.rsplit('/', 1)[-1]
                doc = next((doc for doc in replay.workspace['documents'] if doc['id'] == identifier), None)
                self.reply(doc if doc else {'detail': 'Unknown document'}, 200 if doc else 404); return
            if path.startswith('/static/'):
                target = (static / path.removeprefix('/static/')).resolve()
                if static not in target.parents or not target.is_file():
                    self.send_error(404); return
            elif path in ('/audio/points', '/audio/progress'):
                target = media / f'parent-{path.rsplit("/", 1)[-1]}.wav'
            elif path == f'/api/jobs/{FILM_JOB}/audio':
                target = media / f'parent-{replay.original["scenario"]}.wav'
            elif path in (f'/outputs/{FILM_JOB}/capsule.mp4', f'/outputs/{FILM_JOB}/captions.vtt'):
                target = media / path.rsplit('/', 1)[-1]
                if not target.is_file():
                    self.send_error(404); return
            elif path == f'/outputs/{FILM_JOB}/dossier.json':
                self.reply(replay.original['dossier']); return
            else:
                self.send_error(404); return
            self.file(target)

        def do_POST(self):
            self.record()
            size = int(self.headers.get('Content-Length', '0'))
            if size > 8192:
                self.send_error(413); return
            try:
                body = json.loads(self.rfile.read(size) or '{}')
            except ValueError:
                self.send_error(400); return
            path = urlparse(self.path).path
            match = re.fullmatch(r'/api/workspace/documents/([a-z]+)/open', path)
            if match:
                doc = next((doc for doc in replay.workspace['documents'] if doc['id'] == match[1]), None)
                if doc is None:
                    self.send_error(404); return
                if doc['id'] == 'copie' and replay.started is None:
                    replay.start()
                self.reply({'document': doc, 'preparation': replay.job() if doc['id'] == 'copie' else None,
                            'action': {'document_id': doc['id'], 'trigger': 'modern_copy_opened' if doc['id'] == 'copie' else 'document_opened', 'replay': True}}); return
            if path == f'/api/jobs/{FILM_JOB}/decision':
                if body.get('decision') not in ('keep', 'dismiss'):
                    self.send_error(400); return
                with replay.lock:
                    replay.kept = replay.kept or body['decision'] == 'keep'
                    replay.dismissed = body['decision'] == 'dismiss'
                self.reply(replay.job()); return
            if path == f'/api/jobs/{FILM_JOB}/approve' and replay.phase == 'ready':
                replay.approved = True
                self.reply(replay.job()); return
            self.send_error(404)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    local = f'http://127.0.0.1:{server.server_port}'
    (output / 'local-url.txt').write_text(local)
    try:
        yield local
    finally:
        server.shutdown(); server.server_close()


@contextlib.contextmanager
def public_tunnel(local, output):
    with (output / 'tunnel.log').open('w') as stream:
        process = subprocess.Popen(['cloudflared', 'tunnel', '--url', local, '--protocol', 'http2', '--no-autoupdate'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 100; base = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Tunnel exited; see tunnel.log')
                if select.select([process.stderr], [], [], 1)[0]:
                    line = process.stderr.readline(); stream.write(line); stream.flush()
                    match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
                    if match:
                        base = match.group(0); break
            if not base:
                raise RuntimeError('No public snapshot URL')
            def drain():
                for line in process.stderr:
                    stream.write(line); stream.flush()
            thread = threading.Thread(target=drain, daemon=True); thread.start()
            host = urlparse(base).hostname
            for _ in range(30):
                try:
                    if httpx.get(base, timeout=15).status_code == 200:
                        break
                except httpx.HTTPError:
                    # Some macOS resolvers cache NXDOMAIN for a new quick tunnel.
                    ips = subprocess.check_output(['dig', '+short', host], text=True).splitlines()
                    addresses = [ip for ip in ips if re.fullmatch(r'[0-9.]+', ip)]
                    if addresses:
                        check = subprocess.run(['curl', '--silent', '--show-error', '--fail', '--max-time', '15',
                                                '--resolve', f'{host}:443:{addresses[0]}', base], capture_output=True)
                        if check.returncode == 0 and b'New PRONOTE' in check.stdout:
                            break
                time.sleep(2)
            else:
                raise RuntimeError('Snapshot unreachable')
            (output / 'public-url.txt').write_text(base)
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()


def config(base, browser='chrome'):
    def click(selector, narration, wait=2):
        return {'action': 'click', 'locator': {'type': 'css', 'value': selector}, 'wait': wait, 'narration': narration}
    def navigate(path, narration, wait=2):
        return {'action': 'navigate', 'url': base + path, 'wait': wait, 'narration': narration}
    steps = [
        navigate('/', 'New PRONOTE réunit la journée du professeur et le travail de son agent H. Les données sont fictives ; nous rejouons ici une véritable préparation connectée.'),
        click('#main .meeting-card [data-doc="copie"]', 'Le professeur ouvre la copie d’Alex. Ce geste suffit à déclencher la préparation, sans prompt.'),
        click('#navigation [data-page="messages"]', 'Il continue ses échanges. En parallèle, Gladia transcrit le vocal des parents et H confronte leur question à la consigne, au barème et à la copie.'),
        navigate('/film/activity', 'Le journal reprend les actions réellement effectuées : pièces consultées, transcription, puis recherche Linkup. Le professeur peut suivre ce travail sans quitter son dossier.'),
        navigate('/film/ready', 'Le rapport est prêt. Chaque explication s’appuie sur un extrait scolaire ; la référence publique sert à comprendre et à progresser.'),
        click('#main .document-tabs [data-doc="bareme"]', 'Le barème est le même pour le professeur et pour l’agent. Un résultat juste ne remplace pas les critères de justification attendus.'),
        navigate('/film/video', 'Une vraie capsule personnalisée a été générée, avec narration française et sous-titres. Elle reste à relire avant tout partage.'),
        click('#keep', 'Keep conserve le rapport. Dismiss permet de masquer la notification : le professeur garde la main.'),
        click('.rail [data-page="reports"]', 'Le rapport, ses preuves et sa vidéo restent accessibles dans Rapports H. Le travail est préparé, pendant que le professeur avance.'),
    ]
    return {'metadata': {'title': 'New PRONOTE — H prépare en parallèle', 'version': '1.0.0',
                         'description': REPLAY_NOTE + ' Capture du frontend réel, avec traces du job connecté enregistré ; aucune intégration native ni temps réel n’est prétendu.'},
            'voice': {'engine': 'gtts', 'voice_id': 'fr', 'language': 'fr'},
            'subtitle': {'enabled': True, 'style': 'classic'}, 'output': {'branding': False},
            'scenarios': [{'name': 'Le professeur avance, H prépare', 'url': base + '/', 'browser': browser,
                           'viewport': {'width': 1600, 'height': 1000}, 'steps': steps}]}


def download_video(status, output):
    url = status.get('video_url') or status.get('download_url') or status.get('output_url')
    if not url:
        raise RuntimeError('Completed render has no video URL.')
    if url.startswith('/'):
        url = 'https://demobro.com' + url
    parsed = urlparse(url)
    # Signed Azure/video URLs must never receive the DemoBro account header.
    headers = account_headers() if parsed.hostname == 'demobro.com' and parsed.path.startswith('/api/') else {}
    response = httpx.get(url, headers=headers, follow_redirects=True, timeout=180)
    response.raise_for_status()
    target = output / 'new-pronote-demo.mp4'
    target.write_bytes(response.content)
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(target)]))
    write_json(output / 'ffprobe.json', info)
    log('Completed ' + str(target))


def follow(client, render_id, output, max_polls=240):
    previous = None
    for _ in range(max_polls):
        status = client.call('get_render', {'render_id': render_id})
        write_json(output / 'status.json', status)
        summary = {key: status.get(key) for key in ('status', 'progress_pct', 'progress_label', 'execution_state')}
        if summary != previous:
            log(str(summary)); previous = summary
        if status.get('execution_state') == 'action_required':
            raise RuntimeError('DemoBro action required: ' + str(status.get('user_action')))
        if status.get('status') in ('completed', 'success', 'done', 'finished'):
            download_video(status, output); return
        if status.get('status') in ('failed', 'error', 'cancelled', 'canceled'):
            raise RuntimeError('DemoBro failed; do not resubmit automatically: ' + str(status.get('error_message')))
        time.sleep(5)
    raise TimeoutError('Render still running. Submission ID preserved; no automatic resubmission.')


def main(args):
    output = (args.output or ROOT / 'data' / ('workspace-demo-' + args.job_id)).resolve()
    manifest = freeze_snapshot(args.job_id, output)
    (output / 'demo-preview.yaml').write_text(yaml.safe_dump(config('http://127.0.0.1:8766', args.browser), allow_unicode=True, sort_keys=False))
    log('Prepared isolated snapshot: ' + str(output))
    log(f'{manifest["actual_actions"]} actual events; fictional data; no provider calls during preparation.')
    if not (args.serve or args.render or args.probe or args.follow):
        return
    if args.follow:
        record = json.loads((output / 'submission.json').read_text())
        if not record.get('render_id'):
            raise RuntimeError('Unconfirmed submission; inspect the account before any new request.')
        client = DemoBro()
        try:
            client.tools(); follow(client, record['render_id'], output)
        finally:
            client.close()
        return
    with snapshot_server(output) as local:
        log('Local read-only replay: ' + local)
        if args.serve:
            deadline = time.monotonic() + args.serve_seconds
            while time.monotonic() < deadline:
                time.sleep(1)
            return
        with public_tunnel(local, output) as base:
            client = DemoBro()
            try:
                names = {tool['name'] for tool in client.tools()}
                for name in ('validate_demo_config', 'probe_demo_config', 'estimate_demo_cost', 'render_demo_from_yaml', 'get_render'):
                    if name not in names:
                        raise RuntimeError('Missing DemoBro tool: ' + name)
                ledger = output / 'submission.json'
                if ledger.exists():
                    raise RuntimeError('A submission already exists. Use --follow; do not create another render.')
                raw = yaml.safe_dump(config(base, args.browser), allow_unicode=True, sort_keys=False)
                (output / 'demo.yaml').write_text(raw)
                validation = client.call('validate_demo_config', {'yaml_config': raw, 'interactive': True})
                write_json(output / 'validation.json', validation)
                if not validation.get('valid'):
                    raise RuntimeError('Invalid DemoDSL: ' + str(validation)[:700])
                probe = client.call('probe_demo_config', {'yaml_config': raw})
                write_json(output / 'probe.json', probe)
                if probe.get('resolved') is False or probe.get('unresolved', 0) > 0 or probe.get('ambiguous', 0) > 0:
                    raise RuntimeError('Unresolved selectors: refusing render.')
                if args.probe:
                    log('Selectors probed. No render submitted.'); return
                estimate = client.call('estimate_demo_cost', {'yaml_config': raw})
                write_json(output / 'estimate.json', estimate)
                if estimate.get('affordable') is False:
                    raise RuntimeError('Render is not affordable.')
                # A fresh server state keeps the recorded opening visible even
                # when the probing browser already traversed every route.
                log('Probe passed. Starting a private interactive render.')
                write_json(ledger, {'state': 'submitting', 'at': time.time(), 'source_job_id': args.job_id, 'snapshot_url': base})
                result = client.call('render_demo_from_yaml', {
                    'name': 'New PRONOTE — H prépare en parallèle',
                    'description': config(base)['metadata']['description'],
                    'project_name': 'H Company — New PRONOTE — replay',
                    'yaml_config': raw, 'interactive': True, 'animation_style': 'auto', 'is_public': False})
                render_id = result.get('render_id') or result.get('id') or (result.get('render') or {}).get('id')
                write_json(ledger, {'render_id': render_id, 'response': result, 'source_job_id': args.job_id, 'snapshot_url': base})
                if not render_id:
                    raise RuntimeError('Submission not confirmed; no automatic retry.')
                follow(client, render_id, output)
            finally:
                client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--browser', choices=('chrome', 'webkit', 'firefox'), default='chrome')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--serve', action='store_true')
    mode.add_argument('--probe', action='store_true')
    mode.add_argument('--render', action='store_true')
    mode.add_argument('--follow', action='store_true')
    parser.add_argument('--serve-seconds', type=int, default=600)
    main(parser.parse_args())
