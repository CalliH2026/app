import hashlib
import html
import os
import json
import mimetypes
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from typing import Literal
from .engine import FIXTURE, DATA, ROOT, JOBS, LOCK, launch, snapshot, save
from .teacher_assessment import TeacherAssessment

MEETING_AT=(datetime.now().astimezone()+timedelta(minutes=120)).isoformat()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifecycle(app):
    if os.getenv('PUBLIC_URL'):
        yield
        return
    app.state.pronote_connection.start()
    try:
        from .native_bridge import read_settings
        from .native.win32_bridge import start,STOP
        if read_settings().get('mode')=='example':start()
        from .native.document_service import start as start_documents, stop as stop_documents
        start_documents()
        try:
            yield
        finally:
            from .pilot_web import stop
            stop()
            from .background_pronote import stop as stop_background
            stop_background()
            stop_documents()
            STOP.set()
    finally:
        app.state.pronote_connection.close()

app=FastAPI(title='New PRONOTE · Calli',lifespan=lifecycle)
from .outing_checkout_routes import install_routes as install_checkout, is_stripe_webhook
install_checkout(app)
from .grading_voice import install_routes as install_grading_voice
install_grading_voice(app)
from .pronote_connection import ConnectionManager, install_routes as install_pronote_connection
from .pilot import DATA as PILOT_DATA
app.state.pronote_connection = ConnectionManager(PILOT_DATA)
install_pronote_connection(app, app.state.pronote_connection)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
# Only known output files are exposed, never the source tree or credentials.
@app.get('/outputs/{job_id}/{filename}')
def output(job_id:str,filename:str):
    job=JOBS.get(job_id)
    captured_vocal=bool(job and filename==job.get('captured_audio')
        and Path(filename).name==filename and filename.startswith('parent-audio.')
        and Path(filename).suffix.lower() in ('.wav','.mp3','.m4a','.ogg','.mp4','.flac','.aac'))
    if not job or not (captured_vocal or filename in ('capsule.mp4','capsule-demobro.mp4','captions.vtt','captions.srt','dossier.json')):
        raise HTTPException(404)
    p=DATA/job_id/filename
    if not p.is_file(): raise HTTPException(404)
    return FileResponse(p)

@app.middleware('http')
async def local_only(request:Request,call_next):
    if os.getenv('PUBLIC_URL'):
        return await call_next(request)
    # Loopback app. Also reject cross-origin writes / DNS rebinding.
    host=request.headers.get('host','').split(':')[0]
    if host not in ('127.0.0.1','localhost','testserver'): return HTMLResponse('Localhost uniquement',status_code=403)
    if request.method!='GET' and not is_stripe_webhook(request):
        origin=request.headers.get('origin')
        local_port=os.getenv('H_LOCAL_PREVIEW_PORT','8000')
        if origin and origin not in (f'http://127.0.0.1:{local_port}',f'http://localhost:{local_port}','http://testserver'):
            return HTMLResponse('Origine refusée',status_code=403)
    return await call_next(request)

@app.get('/')
def home(): return FileResponse(ROOT/'static/workspace.html')

@app.get('/api/workspace')
def workspace():
    from .workspace import get_workspace
    return get_workspace()

class OutingRequest(BaseModel):
    class_id: str = '4e-b'
    destination_id: str = 'orsay'
    date: str
    visit_time: str = '10:00'
    duration_minutes: int = Field(default=120, ge=30, le=360)
    adults: int = Field(default=2, ge=1, le=10)
    transport_total: str = Field(default='180.00', max_length=16)
    subsidy: str = Field(default='0.00', max_length=16)
    objective: str = Field(default='', max_length=3000)
    mode: Literal['live'] = 'live'


@app.get('/api/outings/options')
def outing_options():
    from .outings import options
    return options()


@app.post('/api/outings')
def outing_start(body: OutingRequest):
    from .outings import start
    try:
        return start(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.get('/api/outings/{outing_id}')
def outing_get(outing_id: str):
    from .outings import get
    try:
        return get(outing_id)
    except (ValueError, KeyError):
        raise HTTPException(404, 'Sortie introuvable.')


class OutingObjective(BaseModel):
    objective: str = Field(max_length=3000)


@app.post('/api/outings/{outing_id}/objective')
def outing_objective(outing_id: str, body: OutingObjective):
    from .outings import update_objective
    try:
        return update_objective(outing_id, body.objective)
    except KeyError:
        raise HTTPException(404, 'Sortie introuvable.')
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post('/api/outings/{outing_id}/save')
def outing_save(outing_id: str):
    from .outings import save_dossier
    try:
        return save_dossier(outing_id)
    except KeyError:
        raise HTTPException(404, 'Sortie introuvable.')
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))


class OperationsDemoRequest(BaseModel):
    mode: Literal['simulation'] = 'simulation'
    model_config = {'extra': 'forbid'}


@app.post('/api/outings/{outing_id}/operations-demo')
def outing_operations_demo(outing_id: str, body: OperationsDemoRequest = OperationsDemoRequest()):
    from .outings import start_operations_demo
    try:
        return start_operations_demo(outing_id)
    except KeyError:
        raise HTTPException(404, 'Sortie introuvable.')
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))


@app.get('/api/outings/{outing_id}/export')
def outing_export(outing_id: str):
    from .outings import export_text
    try:
        text = export_text(outing_id)
    except KeyError:
        raise HTTPException(404, 'Sortie introuvable.')
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))
    return Response(text, media_type='text/plain; charset=utf-8', headers={
        'Content-Disposition': 'attachment; filename="dossier-sortie-scolaire.txt"',
        'Cache-Control': 'no-store',
    })

@app.get('/api/workspace/documents/{document_id}')
def workspace_document(document_id:str):
    from .workspace import get_document
    try:return get_document(document_id)
    except ValueError as exc:raise HTTPException(404,str(exc))

class WorkspaceOpen(BaseModel):
    voice:str='points'
    mode:Literal['demo','live']='live'
    retry:bool=False
    video_provider:Literal['local','demobro']='local'
    teacher_assessment:TeacherAssessment|None=None

@app.post('/api/workspace/documents/{document_id}/open')
def workspace_open(document_id:str,body:WorkspaceOpen):
    from .workspace import open_document
    try:
        result=open_document(document_id,body.voice,body.mode,body.retry,body.video_provider,
                             teacher_assessment=body.teacher_assessment)
        if document_id=='copie':
            from .background_pronote import schedule
            schedule(trigger='document_open')
        return result
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.get('/api/pronote/background')
def background_status():
    from .background_pronote import status
    return status()

class BackgroundStart(BaseModel):
    source:Literal['official_demo','school']='official_demo'

@app.post('/api/pronote/background/start')
def background_start(body:BackgroundStart):
    from .background_pronote import start
    try:return start(body.source)
    except (ValueError,RuntimeError) as exc:raise HTTPException(409,str(exc))

@app.post('/api/pronote/background/stop')
def background_stop():
    from .background_pronote import stop
    return stop()

@app.post('/api/pronote/background/read')
def background_read():
    from .background_pronote import schedule
    return schedule()

class BackgroundDecision(BaseModel):
    decision:Literal['keep','dismiss']

@app.post('/api/pronote/background/decision')
def background_decision(body:BackgroundDecision):
    from .background_pronote import decide
    return decide(body.decision)

@app.get('/api/pronote/background/replay/{run_id}')
def background_replay(run_id:str):
    import re
    if not re.fullmatch(r'[a-f0-9]{32}',run_id):raise HTTPException(404)
    path=DATA/'pronote-background/runs'/run_id/'replay.mp4'
    if not path.is_file():raise HTTPException(404)
    return FileResponse(path,media_type='video/mp4')

@app.get('/api/recordings')
def recordings():
    if os.getenv('PUBLIC_URL'):
        return []
    from .recordings import get_recordings
    return get_recordings()

@app.get('/recordings/{recording_id}/{filename}')
def recording_media(recording_id:str,filename:str):
    if recording_id not in ('native-pronote','legacy-web','product-workspace') or filename not in ('capture.mp4','preview.png'):
        raise HTTPException(404)
    path=DATA/'recordings'/recording_id/filename
    if not path.is_file():raise HTTPException(404)
    return FileResponse(path,media_type='video/mp4' if filename.endswith('.mp4') else 'image/png')

@app.get('/api/recordings/native/status')
def native_recording_status():
    from .recordings import status
    return status()

@app.post('/api/recordings/native/show-python')
def reveal_recording_python():
    import subprocess
    from .recordings import desktop_preflight
    target=desktop_preflight().get('application_path')
    if not target:raise HTTPException(409,'Application Python introuvable sur ce poste.')
    subprocess.run(['open','-R',target],check=True,capture_output=True,timeout=10)
    return {'message':'Python.app affiché dans Finder. Vous pouvez le sélectionner dans les réglages de confidentialité.'}

@app.post('/api/recordings/native/show-launcher')
def reveal_recording_launcher():
    import subprocess
    from .recordings import desktop_preflight
    check=desktop_preflight();target=check.get('authorization_target_path')
    if not target:raise HTTPException(409,'Application hôte introuvable sur ce poste.')
    subprocess.run(['open','-R',target],check=True,capture_output=True,timeout=10)
    return {'message':check.get('authorization_target_name','Application hôte')+' affiché dans Finder. Le SDK H recommande d’autoriser puis relancer cette application.'}

class NativeRecordingStart(BaseModel):
    desktop_prepared:bool=False

@app.post('/api/recordings/native/start')
def native_recording_start(body:NativeRecordingStart):
    from .recordings import start_native_session
    return start_native_session(desktop_prepared=body.desktop_prepared)

@app.get('/api/fixture')
def fixture():
    return {**FIXTURE,'server_time':datetime.now().astimezone().isoformat(),'appointment_at':MEETING_AT}

class OpenCopy(BaseModel):
    scenario:str='points'
    mode:Literal['demo','live']='demo'
    retry:bool=False
    video_provider:Literal['local','demobro']='local'

@app.post('/api/open-copy')
def open_copy(body:OpenCopy):
    if body.scenario not in FIXTURE['audio']: raise HTTPException(400,'Vocal inconnu')
    if body.mode=='demo' and body.scenario not in ('points','progress'): raise HTTPException(400,'Un vocal importé nécessite le mode réel.')
    try: return launch(body.scenario,body.mode,'http://127.0.0.1:8000',body.retry,body.video_provider)
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.get('/api/jobs/{job_id}')
def job(job_id:str):
    if job_id not in JOBS: raise HTTPException(404)
    return snapshot(job_id)


class PracticeRequest(BaseModel):
    model_config = {'extra': 'forbid'}
    mode: Literal['simulation', 'live'] = 'simulation'
    retry: bool = False


def practice_action(action, *args, **kwargs):
    try:
        return action(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, 'Rapport ou entraînement introuvable.')
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))


@app.get('/api/jobs/{job_id}/practice')
def practice_status(job_id: str):
    from .practice import get
    return Response(json.dumps(practice_action(get, job_id), ensure_ascii=False),
                    media_type='application/json', headers={'Cache-Control': 'no-store'})


@app.post('/api/jobs/{job_id}/practice')
def practice_start(job_id: str, body: PracticeRequest):
    from .practice import start
    return practice_action(start, job_id, retry=body.retry, mode=body.mode)


@app.post('/api/jobs/{job_id}/practice/approve')
def practice_approve(job_id: str):
    from .practice import approve
    return practice_action(approve, job_id)


@app.get('/api/jobs/{job_id}/practice/preview')
def practice_preview(job_id: str):
    from .practice import artifact_path
    from .practice_theme import PREVIEW_CSP, THEME_VERSION, themed
    path = practice_action(artifact_path, job_id)
    original = path.read_bytes()
    return Response(themed(original), media_type='text/html; charset=utf-8', headers={
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()',
        'Content-Security-Policy': PREVIEW_CSP,
        'X-Calli-Presentation': THEME_VERSION,
        'X-Calli-Original-SHA256': hashlib.sha256(original).hexdigest(),
    })


@app.get('/api/jobs/{job_id}/practice/download')
def practice_download(job_id: str):
    from .practice import artifact_path
    path = practice_action(artifact_path, job_id, download=True)
    return FileResponse(path, media_type='text/html', filename='entrainement-pythagore.html', headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'",
    })


@app.get('/api/jobs/{job_id}/audio')
def job_audio(job_id:str):
    if job_id not in JOBS:raise HTTPException(404)
    state=snapshot(job_id)
    filename=state.get('captured_audio')
    if filename and Path(filename).name==filename:
        path=DATA/job_id/filename
        if path.is_file():return FileResponse(path)
    return audio(state['scenario'])

@app.post('/api/jobs/{job_id}/approve')
def approve(job_id:str):
    with LOCK:
        if job_id not in JOBS: raise HTTPException(404)
        j=JOBS[job_id]
        if j['status']!='ready': raise HTTPException(409,'La vidéo doit être prête avant validation.')
        j['approved']=True; save(j)
    return snapshot(job_id)

@app.post('/api/audio')
async def upload_audio(file:UploadFile):
    ext=Path(file.filename or '').suffix.lower()
    if ext not in ('.wav','.mp3','.m4a','.ogg','.mp4'): raise HTTPException(400,'Formats : WAV, MP3, M4A, OGG, MP4')
    content=await file.read(20*1024*1024+1)
    if not content or len(content)>20*1024*1024: raise HTTPException(400,'Vocal vide ou supérieur à 20 Mo')
    identifier='upload-'+uuid.uuid4().hex[:12]
    filename=identifier+ext
    (ROOT/'fixtures'/filename).write_bytes(content)
    with LOCK:
        FIXTURE['audio'][identifier]={'file':filename,'text':'Vocal importé : transcription à réaliser par Gladia.'}
        (DATA/'uploads.json').write_text(json.dumps({k:v for k,v in FIXTURE['audio'].items() if k.startswith('upload-')}))
    return {'scenario':identifier,'filename':file.filename}

@app.get('/audio/{scenario}')
def audio(scenario:str):
    item=FIXTURE['audio'].get(scenario)
    if not item: raise HTTPException(404)
    return FileResponse(ROOT/'fixtures'/item['file'],media_type=mimetypes.guess_type(item['file'])[0] or 'audio/wav')

@app.get('/school/{page}',response_class=HTMLResponse)
def school(page:str,scenario:str='points',agent:int=0,job:str|None=None):
    esc=html.escape
    source=FIXTURE
    if job:
        if job not in JOBS:raise HTTPException(404,'Préparation inconnue')
        source=snapshot(job).get('input_context') or FIXTURE
    job_query='&job='+esc(job) if job else ''
    nav=''.join(f'<a class="{"selected" if p==page else ""}" href="/school/{p}?scenario={esc(scenario)}&agent={agent}{job_query}">{label}</a>' for p,label in [('accueil','Accueil'),('agenda','Agenda'),('messages','Discussions'),('consigne','Cahier de textes'),('documents','Documents'),('bareme','Barème'),('copie','Copie d’Alex')])
    if page=='agenda':
        appointment=source['appointment']
        meeting_time=appointment.get('at') or MEETING_AT
        body=f'<h2>Rencontre parents / professeurs</h2><p>Identifiant : {esc(appointment["id"])} · Élève : {esc(source["student"]["name"])} · {esc(source["student"]["class"])}</p><h3>Rendez-vous : {esc(meeting_time)} · {appointment["duration_minutes"]} minutes</h3><p>{esc(appointment["room"])} · {esc(appointment["participants"])}</p><p>{esc(appointment["reason"])}</p>'
    elif page=='messages':
        audio_url='/api/jobs/'+esc(job)+'/audio' if job else '/audio/'+esc(scenario)
        body='<h2>Discussions · famille Martin</h2>'+''.join(f'<article><small>{esc(m["date"])} · {esc(m["id"])}</small><h3>{esc(m["from"])}</h3><p>{esc(m["text"])}</p></article>' for m in source['messages'])+f'<h3>Pièce jointe au dossier : vocal parental</h3><audio controls src="{audio_url}"></audio><p>Source : audio. Utilisez l’outil transcribe_audio pour obtenir le texte et ses repères.</p>'
    elif page=='documents':
        body='<h2>Documents du contrôle</h2>'+''.join(f'<article><a href="/school/{d["id"]}?scenario={esc(scenario)}&agent={agent}{job_query}">{esc(d["title"])}</a><small> · identifiant : {d["id"]}</small></article>' for d in source['documents'])
    elif page in {d['id'] for d in source['documents']}:
        d=next(d for d in source['documents'] if d['id']==page)
        body=f'<small>Mathématiques · Pythagore · identifiant source : {d["id"]}</small><h2>{esc(d["title"])}</h2><article class="paper"><p>{esc(d["text"])}</p></article>'
        if page=='copie': body+='<a href="/school/bareme?scenario='+esc(scenario)+'&agent='+str(agent)+job_query+'">Consulter le barème</a>'
    else:
        if page!='accueil': raise HTTPException(404,'Document introuvable : utiliser les liens de navigation.')
        body=f'<h2>Bonjour, {esc(source["student"]["teacher"])}</h2><p>Rendez-vous avec les parents : {esc(source["appointment"].get("at") or MEETING_AT)}.</p><p>{esc(source["appointment"]["reason"])}</p>'
    body=body.replace(f'?scenario={esc(scenario)}"',f'?scenario={esc(scenario)}&agent={agent}"')
    if page=='copie' and not agent:
        body+='''<script>fetch('/api/open-copy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario:new URLSearchParams(location.search).get('scenario')||'points',mode:'demo'})}).then(r=>r.json()).then(j=>{const a=document.createElement('a');a.href='/?job='+j.id;a.textContent='Préparation déclenchée : ouvrir le suivi →';document.querySelector('main').append(a);});</script>'''
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Portail scolaire local · {esc(page)}</title><link rel="stylesheet" href="/static/style.css"></head><body class="school"><header><b>PRONOTE · étude locale</b><span>Collège des Tilleuls · Espace Professeurs</span><a href="/">Revenir au suivi H</a></header><div class="disclaimer">DÉMONSTRATION INDÉPENDANTE · Données fictives · Interface locale inspirée du parcours Pronote, sans connexion à un établissement.</div><nav>{nav}</nav><main class="schoolmain"><small>Alex Martin · 4e B · Mme Laurent</small>{body}</main></body></html>'''

class Decision(BaseModel):
    decision:Literal['keep','dismiss']

@app.post('/api/jobs/{job_id}/decision')
def decision(job_id:str,body:Decision):
    with LOCK:
        if job_id not in JOBS: raise HTTPException(404)
        j=JOBS[job_id]
        if body.decision=='keep':
            j['kept']=True;j['notification_dismissed']=False
        else:j['notification_dismissed']=True
        j['decision']='keep' if j.get('kept') else body.decision
        j['decision_at']=datetime.now().astimezone().isoformat();save(j)
        return snapshot(job_id)

@app.get('/api/reports')
def saved_reports():
    with LOCK:
        return [{'id':j['id'],'scenario':j['scenario'],'status':j['status'],'question':j.get('dossier',{}).get('question')} for j in reversed(list(JOBS.values())) if j.get('decision')=='keep']

@app.get('/api/notifications/feed')
def notification_feed():
    result=[]
    with LOCK:
        for j in JOBS.values():
            if j.get('notification_dismissed') or j.get('decision')=='dismiss':continue
            for e in j['events']:
                if e['stage'] in ('ready','video'):
                    if e['stage']=='ready' and j.get('status')!='ready':continue
                    if j.get('status')=='failed':continue
                    native=j.get('source_kind')=='pronote_native_dossier'
                    label=(j.get('dossier') or {}).get('display_label') if native else 'Rendez-vous d’Alex'
                    result.append({'id':j['id'],'phase':'ready' if e['stage']=='ready' else 'draft','at':e['time'],
                                   'source_kind':j.get('source_kind','local_demo'),
                                   'label':label or 'PRONOTE · préparation du dossier',
                                   'url':f'/native?job={j["id"]}' if native else f'/?job={j["id"]}'})
    from .native_ai import status
    ai=status();decisions=DATA/'native-notification-decisions.json'
    choices=json.loads(decisions.read_text()) if decisions.exists() else {}
    if ai.get('status')=='ready' and choices.get(ai.get('context_id'))!='dismiss':
        result.append({'id':'native-'+ai['context_id'],'phase':'native-ready','at':ai.get('completed_at',ai['created_at'])})
    def notification_time(item):
        try:return datetime.fromisoformat(item.get('at','').replace('Z','+00:00')).timestamp()
        except (ValueError,TypeError):return 0
    return sorted(result,key=notification_time)[-20:]

@app.post('/api/notifications/enable')
def enable_notifications():
    import subprocess,sys
    if sys.platform!='darwin':raise HTTPException(400,'Les notifications natives de ce prototype nécessitent macOS.')
    bundle=DATA/'H Parallel.app'
    if not (bundle/'Contents/MacOS/HParallel').exists():
        try: subprocess.run([str(ROOT/'native/build.sh')],check=True,capture_output=True,timeout=120)
        except Exception: raise HTTPException(500,'Compilation du compagnon macOS impossible. Installer les outils Swift/Xcode.')
    if not (DATA/'notifier-status.json').exists():(DATA/'notifier-status.json').write_text(json.dumps({'status':'requesting'}))
    subprocess.run(['open','-a',str(bundle),'--args',str(DATA/'notifier-status.json')],check=True,capture_output=True,timeout=15)
    return {'message':'Compagnon macOS ouvert. Autorisez ses notifications si macOS le demande. Les alertes proposent Keep, Dismiss et Voir le rapport.'}

@app.get('/api/notifications/status')
def notification_status():
    p=DATA/'notifier-status.json'
    return json.loads(p.read_text()) if p.exists() else {'status':'not_enabled'}

@app.post('/api/jobs/{job_id}/demobro')
def generate_demobro(job_id:str):
    import threading
    from .engine import update,event
    with LOCK:
        if job_id not in JOBS:raise HTTPException(404)
        j=JOBS[job_id]
        if not j.get('dossier'):raise HTTPException(409,'Le dossier doit être prêt.')
        if j.get('demobro_render_id') and j.get('video_provider')=='demobro':return snapshot(job_id)
        if j['status']=='rendering':return snapshot(job_id)
        update(j,status='rendering',approved=False,error=None)
    def worker():
        try:
            from .demobro import render_capsule
            output=render_capsule(j['dossier'],DATA/job_id,lambda text:event(j,'demobro',text))
            update(j,**output,status='ready')
            event(j,'ready','Votre capsule DemoBro est prête à relire. Aucun partage automatique.')
        except Exception as exc:
            update(j,status='failed',error=str(exc)[:800]);event(j,'error','Le rendu DemoBro demande une vérification. Aucun nouveau rendu soumis automatiquement.')
    threading.Thread(target=worker,daemon=True).start()
    return snapshot(job_id)

@app.get('/native')
def native_page():return FileResponse(ROOT/'static/native.html')

@app.get('/demo')
def demo_page():return FileResponse(ROOT/'static/index.html')

@app.get('/api/native/settings')
def native_settings():
    from .native_bridge import read_settings
    return read_settings()

@app.get('/api/native/context')
def native_context():
    from .native_bridge import context
    return context()

@app.post('/api/native/context')
async def native_intake(request:Request):
    from .native_bridge import ingest,NativeContext
    try:body=NativeContext.model_validate(await request.json())
    except ValueError:raise HTTPException(422,'Contexte natif invalide')
    return ingest(body,request)

class NativeConnect(BaseModel):
    allow_ocr:bool=False

@app.post('/api/native/connect')
def native_connect(body:NativeConnect):
    import subprocess,sys
    from .native_bridge import configure
    if sys.platform!='darwin':raise HTTPException(400,'Client Mac requis')
    client=DATA/'pronote-native/component.pkg/Payload/Client PRONOTE 2026.app'
    if not client.exists():raise HTTPException(409,'Extraire le paquet officiel PRONOTE avec le script native/setup_client.sh.')
    configure(body.allow_ocr)
    enable_notifications()
    subprocess.run(['open','-a',str(client)],check=True,capture_output=True,timeout=20)
    return {'message':'Le vrai client et le compagnon sont ouverts. macOS demandera l’autorisation de lire la fenêtre si nécessaire.'}

class NativeDecision(Decision):
    context_id:str|None=Field(default=None,pattern=r'^[0-9a-f]{16}$')

@app.post('/api/native/decision')
def native_decision(body:NativeDecision):
    from .native_bridge import decide
    return decide(body.decision,body.context_id)

@app.post('/api/native/demo')
def launch_native_demo():
    import subprocess
    from .native.prepare_demo import bundle
    from .native.win32_bridge import start
    from .native_bridge import configure
    target=bundle()
    configure(False,mode='example')
    enable_notifications()
    subprocess.run(['open','-a',str(target)],check=True,capture_output=True,timeout=20)
    start()
    return {'message':'La base d’exemple officielle est lancée dans PRONOTE Monoposte, avec son connecteur local en lecture seule.'}

@app.get('/api/native/ai')
def native_ai_status():
    from .native_ai import status
    return status()

@app.get('/api/native/documents')
def native_document_status():
    from .native.document_service import status
    from .native_pipeline import status as preparation
    return {**status(), 'preparation': preparation()}

@app.get('/api/native/documents/{job_id}/{source_id}')
def native_document_file(job_id:str,source_id:str):
    job=JOBS.get(job_id)
    if not job or job.get('source_kind')!='pronote_native_dossier':raise HTTPException(404)
    source=next((entry for entry in job.get('captured_sources',[]) if entry['id']==source_id),None)
    if not source:raise HTTPException(404)
    path=DATA/job_id/source['file']
    if not path.is_file():raise HTTPException(404)
    return FileResponse(path)

@app.post('/api/native/preparations/{job_id}/resume')
def resume_native_preparation(job_id:str):
    from .native_pipeline import resume_failed
    job=JOBS.get(job_id)
    if not job or job.get('source_kind')!='pronote_native_dossier':raise HTTPException(404)
    try:
        return resume_failed(job_id)
    except ValueError as exc:
        raise HTTPException(409,str(exc))

@app.get('/demo-video')
def demo_video():
    p=DATA/'product-demo-v2/h-parallel-demo.mp4'
    if not p.exists():raise HTTPException(404,'Vidéo du prototype non disponible')
    return FileResponse(p,media_type='video/mp4')

@app.post('/api/native/ai/prepare')
def native_ai_prepare():
    from .native_ai import schedule,status
    from .native_bridge import context
    schedule(context(),force=True)
    return status()

# Google only manages the dedicated calendar created by this app.
@app.get('/api/calendar/status')
def calendar_status():
    from .google_calendar import status
    return status()

@app.post('/api/calendar/connect')
def calendar_connect():
    from .google_calendar import connect
    from urllib.parse import parse_qs, urlparse
    from fastapi.responses import JSONResponse
    try:
        url = connect()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    response = JSONResponse({'url': url})
    response.set_cookie('calendar_oauth_state', parse_qs(urlparse(url).query)['state'][0],
                        httponly=True, samesite='lax', max_age=600, path='/api/calendar')
    return response

@app.get('/api/calendar/callback')
def calendar_callback(request: Request, state: str = '', code: str = ''):
    from .google_calendar import callback
    from fastapi.responses import RedirectResponse
    import httpx
    try:
        callback(state, code, request.cookies.get('calendar_oauth_state', ''))
    except ValueError as exc:
        return HTMLResponse(html.escape(str(exc)) + ' <a href="/">Retour à l’agenda</a>', status_code=400)
    except (httpx.HTTPError, RuntimeError):
        return HTMLResponse('Connexion Google impossible. <a href="/">Réessayer depuis l’agenda</a>', status_code=502)
    response = RedirectResponse('/?calendar=connected', status_code=303)
    response.delete_cookie('calendar_oauth_state', path='/api/calendar')
    return response

@app.post('/api/calendar/sync')
def calendar_sync():
    from .google_calendar import sync
    from .workspace import get_workspace
    import httpx
    try:
        return sync(get_workspace()['agenda'])
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    except httpx.HTTPError:
        raise HTTPException(502, 'Synchronisation Google impossible. Vérifiez la connexion ou reconnectez le compte.')

@app.post('/api/calendar/disconnect')
def calendar_disconnect():
    from .google_calendar import disconnect
    import httpx
    try:
        disconnect()
    except httpx.HTTPError:
        raise HTTPException(502, 'Impossible de révoquer la connexion Google. Réessayez.')
    return {'connected': False}


@app.get('/pilot')
def pilot_page():
    return FileResponse(ROOT/'static/pilot.html')

@app.get('/api/pilot')
def pilot_status():
    from .pilot import status
    return status()

from .pilot import PilotConfig

@app.post('/api/pilot/config')
def pilot_config(body: PilotConfig):
    from .pilot import save
    from .native_bridge import read_settings, SETTINGS
    try:
        result = save(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    from .pilot_web import stop
    stop()
    # A changed target must be explicitly activated again.
    with LOCK:
        SETTINGS.write_text(json.dumps({**read_settings(), 'enabled': False}))
    return result

class PilotStart(BaseModel):
    allow_ocr: bool = False

@app.post('/api/pilot/start')
def pilot_start(body: PilotStart):
    import subprocess, sys
    from .pilot import load, client_info
    from .native_bridge import configure, SETTINGS, STATE
    from .native.win32_bridge import STOP
    if load().connection_mode != 'local':
        raise HTTPException(400, 'Sélectionner le mode client local.')
    from .pilot_web import stop
    stop()
    if sys.platform != 'darwin':
        raise HTTPException(400, 'Le pilote natif nécessite macOS.')
    try:
        target = client_info(load())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    enable_notifications()
    subprocess.run(['open', '-a', target['client_path']], check=True, capture_output=True, timeout=20)
    STOP.set()
    with LOCK:
        STATE.unlink(missing_ok=True)
        value = configure(body.allow_ocr, mode='pilot')
        value.update(target)
        SETTINGS.write_text(json.dumps(value))
    return {'message': 'Client ouvert. Connectez-vous directement dans PRONOTE, puis ouvrez une vue pédagogique. La lecture du contexte est active.'}

@app.post('/api/pilot/stop')
def pilot_stop():
    from .pilot_web import stop
    stop()
    from .native_bridge import read_settings, SETTINGS
    with LOCK:
        SETTINGS.write_text(json.dumps({**read_settings(), 'enabled': False}))
    return {'message': 'Lecture arrêtée. Les relevés déjà conservés restent sur ce Mac.'}


@app.get('/api/pilot/web')
def pilot_web_status():
    from .pilot_web import status
    return status()

@app.post('/api/pilot/web/start')
def pilot_web_start():
    from .pilot_web import start
    from .native_bridge import read_settings, SETTINGS
    with LOCK:
        SETTINGS.write_text(json.dumps({**read_settings(), 'enabled': False}))
    try:
        return start()
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(503, 'Navigateur dédié indisponible. Vérifier que Chrome ou Chromium est installé, puis réessayer.')

class PilotWebCapture(BaseModel):
    authenticated: bool = False

@app.post('/api/pilot/web/capture')
def pilot_web_capture(body: PilotWebCapture):
    from .pilot_web import capture
    if not body.authenticated:
        raise HTTPException(400, 'Confirmer la connexion et l’ouverture de la vue pédagogique.')
    try:
        return capture()
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception:
        raise HTTPException(503, 'Lecture impossible. Rouvrir le navigateur dédié puis se reconnecter.')


from .calli_module import install as install_calli
install_calli(app)
from .family import install as install_family
install_family(app)

from .auth import install_auth
install_auth(app)
