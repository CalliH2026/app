"""Read-only Mac Pronote connector. No grade, student or database is invented."""
import hashlib
import json
import secrets
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel,Field
from fastapi import HTTPException,Request
from .engine import ROOT,DATA,LOCK

TOKEN_FILE=ROOT.parent/'credentials/pronote-bridge-token'

def bridge_token():
    """The local companion's bearer token, created on first use (never as an import side effect)."""
    if not TOKEN_FILE.exists():
        TOKEN_FILE.parent.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(secrets.token_urlsafe(32));TOKEN_FILE.chmod(0o600)
    return TOKEN_FILE.read_text().strip()
SETTINGS=DATA/'native-settings.json'
STATE=DATA/'native-context.json'

def read_settings():
    return json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {'enabled':False,'allow_ocr':False,'panel_request':''}

def configure(allow_ocr=False,mode='client'):
    value={'enabled':True,'allow_ocr':allow_ocr,'panel_request':secrets.token_hex(8),'mode':mode}
    with LOCK:SETTINGS.write_text(json.dumps(value))
    return value

class NativeContext(BaseModel):
    state:str=Field(max_length=70)
    source_kind:str='pronote_macos'
    app_name:str='Client PRONOTE'
    bundle_id:str=''
    pid:int=0
    method:str=''
    visible_text:str=Field(default='',max_length=16000)
    window_title:str=Field(default='',max_length=300)
    observed_at:str=''
    message:str=Field(default='',max_length=1000)
    accessibility_authorized:bool=False

def context():
    if STATE.exists():return json.loads(STATE.read_text())
    return {'state':'not_connected','message':'Le client natif n’a pas encore été relié au compagnon.','source_kind':'pronote_macos','report':None}

def ingest(body:NativeContext,request:Request):
    expected='Bearer '+bridge_token()
    if not secrets.compare_digest(request.headers.get('authorization',''),expected):raise HTTPException(401,'Compagnon local non authentifié')
    if body.source_kind!='pronote_macos':raise HTTPException(400,'Source native incorrecte')
    settings=read_settings()
    if not settings.get('enabled'):raise HTTPException(409,'Lecture arrêtée')
    if settings.get('mode')=='pilot' and body.method=='win32_controls':raise HTTPException(409,'Source de démonstration refusée pendant le pilote')
    data=body.model_dump();text=body.visible_text
    previous=context()
    if body.method!='win32_controls' and previous.get('method')=='win32_controls' and previous.get('state')=='observed':
        try:fresh=(datetime.now().astimezone()-datetime.fromisoformat(previous.get('observed_at',''))).total_seconds()<15
        except ValueError:fresh=False
        if fresh:return {'accepted':True,'state':previous['state'],'context_id':previous.get('context_id')}
    lower=text.casefold()
    # A login screen never becomes a stored credential or a pedagogical source.
    if 'mot de passe' in lower or 'identifiant' in lower:
        data['visible_text']='Écran de connexion Pronote. Les identifiants restent à saisir directement dans l’application.'
        lower=data['visible_text'].casefold()
    if body.state=='observed':
        if 'base exemple' in body.window_title.casefold() and body.method=='win32_controls':
            data['connection_state']='example_open'
            summary='La base d’exemple officielle est ouverte dans le vrai PRONOTE local.'
            unknowns=['Les copies et critères détaillés doivent encore être repérés dans les vues ouvertes.','Les contrôles dessinés sur mesure peuvent nécessiter une lecture visuelle complémentaire.']
        elif 'aucun serveur' in lower or 'coordonnées d’un nouveau serveur' in lower or 'coordonnee' in lower and 'serveur' in lower:
            data['connection_state']='server_required'
            summary='Le vrai client est ouvert. Aucune base scolaire n’est connectée.'
            unknowns=['Le serveur de l’établissement ou une base de test native reste à renseigner.','Aucune copie, consigne ou grille de notation n’est disponible dans cet écran.']
        elif 'connexion pronote' in lower or 'se connecter' in lower:
            data['connection_state']='login_required';summary='Le client attend une connexion à la base scolaire.';unknowns=['L’authentification doit être effectuée directement dans Pronote.','Aucune copie n’a encore été collectée.']
        else:
            data['connection_state']='visible_context';summary='Le contexte visible du client Pronote a été relevé localement.';unknowns=[]
            for label in ('copie','consigne','barème'):
                if label not in lower:unknowns.append('Pièce non repérée dans cette fenêtre : '+label+'.')
        fingerprint=hashlib.sha256((data['visible_text']+data['window_title']).encode()).hexdigest()[:16]
        previous=context()
        data['context_id']=fingerprint
        data['report']={'title':summary,'facts':['Application native : '+body.app_name,'Lecture : '+({'macos_accessibility':'texte d’accessibilité macOS','win32_controls':'contrôles Win32 en lecture seule, dans l’environnement d’exemple'}.get(body.method,'OCR de la seule fenêtre Pronote')),'Source : '+(body.window_title or body.app_name)],'unknowns':unknowns,'video_ready':False}
        if previous.get('context_id')==fingerprint:
            data['kept']=previous.get('kept',False);data['dismissed']=previous.get('dismissed',False)
    with LOCK:
        temp=STATE.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(STATE)
    return {'accepted':True,'state':data['state'],'context_id':data.get('context_id')}

def decide(value,context_id=None):
    with LOCK:
        active=context();data=active
        if context_id and context_id!=active.get('context_id'):
            if not all(c in '0123456789abcdef' for c in context_id) or len(context_id)!=16:raise HTTPException(400,'Contexte invalide')
            prepared=DATA/'native-prepared'/(context_id+'.json')
            if not prepared.exists():raise HTTPException(404,'Rapport natif introuvable')
            data=json.loads(prepared.read_text())
        if not data.get('report'):raise HTTPException(409,'Aucun contexte natif lisible à conserver pour le moment.')
        if value=='keep':
            data['kept']=True;data['dismissed']=False
            from .native_ai import status
            ai=status()
            if ai.get('status')=='ready' and ai.get('context_id')==data.get('context_id'):data['h_report']=ai['report']
            folder=DATA/'native-reports';folder.mkdir(exist_ok=True)
            (folder/(data['context_id']+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2))
        else:data['dismissed']=True
        decisions=DATA/'native-notification-decisions.json'
        choices=json.loads(decisions.read_text()) if decisions.exists() else {}
        choices[data['context_id']]=value;decisions.write_text(json.dumps(choices))
        if data.get('context_id')==active.get('context_id'):STATE.write_text(json.dumps(data,ensure_ascii=False,indent=2))
        return data
