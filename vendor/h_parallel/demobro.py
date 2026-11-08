"""DemoBro MCP bridge. Credentials stay server side; no keys in generated YAML."""
import json
import os
from pathlib import Path
import httpx

ENDPOINT='https://mcp.demobro.com/mcp'

def account_headers():
    token=os.getenv('DEMOBRO_API_KEY')
    config=Path.home()/'Library/Application Support/Code/User/mcp.json'
    if config.exists():
        for server in json.loads(config.read_text()).get('servers',{}).values():
            if server.get('url')==ENDPOINT: return server.get('headers',{})
    if token: return {'Authorization':'Bearer '+token}
    raise RuntimeError('Configurer DEMOBRO_API_KEY ou le serveur DemoBro dans VS Code.')

class DemoBro:
    def __init__(self):
        self.client=httpx.Client(headers={**account_headers(),'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-03-26'},timeout=180)
        self.counter=0
        self.request('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'H-school-mvp','version':'1.0'}})
        self.client.post(ENDPOINT,json={'jsonrpc':'2.0','method':'notifications/initialized'})
    def request(self,method,params):
        self.counter+=1
        r=self.client.post(ENDPOINT,json={'jsonrpc':'2.0','id':self.counter,'method':method,'params':params})
        r.raise_for_status()
        if r.headers.get('mcp-session-id'):self.client.headers['Mcp-Session-Id']=r.headers['mcp-session-id']
        if 'text/event-stream' in r.headers.get('content-type',''):
            messages=[json.loads(line[5:].strip()) for line in r.text.splitlines() if line.startswith('data:')]
            data=next((v for v in messages if v.get('id')==self.counter),{})
        else:data=r.json()
        if data.get('error'):raise RuntimeError('DemoBro MCP : '+str(data['error']))
        return data.get('result',{})
    def tools(self):return self.request('tools/list',{}).get('tools',[])
    def call(self,name,args):
        data=self.request('tools/call',{'name':name,'arguments':args})
        if data.get('isError'):raise RuntimeError('DemoBro : '+str(data.get('content')))
        if data.get('structuredContent') is not None:
            result=data['structuredContent']
            while isinstance(result,dict) and isinstance(result.get('result'),str):
                try:result=json.loads(result['result'])
                except ValueError:break
            return result
        text='\n'.join(c.get('text','') for c in data.get('content',[]) if c.get('type')=='text')
        try:return json.loads(text)
        except ValueError:return {'text':text}
    def close(self):self.client.close()

if __name__=='__main__':
    client=DemoBro()
    try:
        tools=client.tools()
        print('Tools:',[(t['name'],t.get('description','')[:100]) for t in tools])
        for t in tools:
            if t['name'] in ('get_credits_balance','render_demo_from_yaml','get_render','estimate_demo_cost','validate_demo_config','probe_demo_config','connect_browser','get_browser_status','observe_browser','browser_action','create_render','list_voice_providers'):
                print(t['name'],json.dumps(t['inputSchema']))
        if any(t['name']=='get_credits_balance' for t in tools):print('Balance:',client.call('get_credits_balance',{}))
    finally:client.close()

# Isolated read-only scene server: never forwards the local application's API.
import contextlib
import html
import re
import select
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import yaml

ROOT=Path(__file__).parent
REMOTE_LOCK=threading.Lock()
ACTIVE_TUNNELS=set()
import atexit
@atexit.register
def close_tunnels():
    for process in list(ACTIVE_TUNNELS):
        if process.poll() is None: process.terminate()

@contextlib.contextmanager
def scene_server(dossier):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            path=urlparse(self.path).path
            if path.startswith('/static/h-kit/'):
                root=(ROOT/'static/h-kit').resolve();file=(root/path.removeprefix('/static/h-kit/')).resolve()
                if root not in file.parents or not file.is_file():self.send_error(404);return
                mime='font/woff2' if file.suffix=='.woff2' else ('image/svg+xml' if file.suffix=='.svg' else 'text/css')
                data=file.read_bytes()
            elif re.fullmatch('/scene/[0-3]',path):
                index=int(path.rsplit('/',1)[-1]);s=dossier['scenes'][index];esc=html.escape
                subtitle=['LA QUESTION DES PARENTS','LES CRITÈRES ANNONCÉS','LA COPIE, POINT PAR POINT','UNE PISTE POUR PROGRESSER'][index]
                data=f'''<!doctype html><html lang="fr"><meta charset="utf-8"><link rel="stylesheet" href="/static/h-kit/fonts.css"><style>*{{box-sizing:border-box}}body{{margin:0;background:#f9f9fb;color:#1c1c26;font-family:'Plus Jakarta Sans',sans-serif;width:1280px;height:720px;padding:65px 80px;position:relative}}header{{display:flex;align-items:center;gap:25px;color:#7a7a8a;font-family:'Fira Code';font-size:12px;letter-spacing:1px}}header img{{width:24px;height:24px;margin:24px}}.bar{{position:absolute;top:0;left:0;height:7px;width:100%;background:#5a04bc}}h1{{font-size:48px;font-weight:500;letter-spacing:-2px;line-height:1.2;max-width:1000px;margin:52px 0 30px}}p{{font-size:26px;font-weight:400;line-height:1.65;max-width:1060px;margin:0}}footer{{position:absolute;left:80px;right:80px;bottom:43px;border-top:1px solid #d8d8e2;padding-top:18px;display:flex;justify-content:space-between;color:#7a7a8a;font-size:11px}}.num{{color:#5a04bc;font-family:'Fira Code'}}.footnote{{font-size:10px;color:#7a7a8a;position:absolute;bottom:87px;left:80px}}</style><div class="bar"></div><header><img src="/static/h-kit/h-logo-black.svg" alt="H">EN PARALLÈLE / PRÉPARATION DU RENDEZ-VOUS</header><h1>{esc(s['title'])}</h1><p>{esc(s['body'])}</p><span class="footnote">Sources : {esc(', '.join(s['source_ids']))} · {'Les critères scolaires expliquent la note.' if index in (1,2) else 'Dossier fictif de démonstration.'}</span><footer><span>{esc(subtitle)}</span><span class="num">0{index+1} / 04</span></footer></html>'''.encode()
                mime='text/html; charset=utf-8'
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    process=subprocess.Popen(['cloudflared','tunnel','--url',f'http://127.0.0.1:{server.server_port}','--no-autoupdate'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    ACTIVE_TUNNELS.add(process)
    try:
        deadline=time.monotonic()+90;url=None
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('Le tunnel de rendu s’est arrêté.')
            if select.select([process.stderr],[],[],1)[0]:
                line=process.stderr.readline();match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
                if match:url=match.group(0);break
        if not url:raise TimeoutError('Cloudflare : URL de rendu indisponible.')
        for _ in range(30):
            try:
                r=httpx.get(url+'/scene/0',timeout=15)
                if r.status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(2)
        else:raise RuntimeError('Les scènes ne sont pas accessibles au moteur DemoBro.')
        yield url
    finally:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        ACTIVE_TUNNELS.discard(process)
        server.shutdown();server.server_close()

def render_capsule(dossier,folder,progress=lambda text:None):
    folder.mkdir(parents=True,exist_ok=True)
    ledger=folder/'demobro-render.json'
    with REMOTE_LOCK:
        client=DemoBro()
        try:
            with scene_server(dossier) as base:
                scenario={'name':'Explication personnalisée','url':base+'/scene/0','browser':'chrome','viewport':{'width':1280,'height':720},'steps':[{'action':'navigate','url':base+f'/scene/{i}','wait':2,'narration':s['narration']} for i,s in enumerate(dossier['scenes'])]}
                config={'metadata':{'title':'Alex · Préparation du rendez-vous','description':'Dossier scolaire fictif, capsule à relire avant partage.','version':'2.0.0'},'voice':{'engine':'gtts','voice_id':'fr','language':'fr'},'subtitle':{'enabled':True,'style':'classic'},'output':{'branding':False},'scenarios':[scenario]}
                raw=yaml.safe_dump(config,allow_unicode=True,sort_keys=False)
                (folder/'demobro.yaml').write_text(raw)
                if ledger.exists():
                    record=json.loads(ledger.read_text())
                    render_id=record.get('render_id')
                    if not render_id:raise RuntimeError('Une tentative DemoBro existe déjà sans identifiant confirmé. Vérifier le compte avant tout nouvel envoi.')
                    progress('Reprise du suivi DemoBro existant, sans nouveau rendu facturé.')
                else:
                    validation=client.call('validate_demo_config',{'yaml_config':raw})
                    (folder/'demobro-validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2))
                    if validation.get('valid') is False or validation.get('status') in ('error','invalid'):raise RuntimeError('Le scénario DemoBro est invalide : '+str(validation)[:800])
                    estimate=client.call('estimate_demo_cost',{'yaml_config':raw})
                    (folder/'demobro-estimate.json').write_text(json.dumps(estimate,ensure_ascii=False,indent=2))
                    progress('Scénario DemoBro validé ; estimation reçue. Quatre séquences avec narration et sous-titres.')
                    ledger.write_text(json.dumps({'status':'submitting','created_at':time.time()}))
                    result=client.call('render_demo_from_yaml',{'name':'Alex · question parentale · '+folder.name,'project_name':'H Company — rendez-vous scolaire','yaml_config':raw,'is_public':False})
                    render_id=result.get('render_id') or result.get('id') or (result.get('render') or {}).get('id')
                    if not render_id:
                        ledger.write_text(json.dumps({'status':'unconfirmed','response':result},ensure_ascii=False,indent=2))
                        raise RuntimeError('DemoBro n’a pas confirmé de render_id. Aucun renvoi automatique.')
                    ledger.write_text(json.dumps({'render_id':render_id,'response':result},ensure_ascii=False,indent=2))
                    progress('Rendu DemoBro lancé : '+render_id)
                previous=None
                for _ in range(180):
                    result=client.call('get_render',{'render_id':render_id})
                    (folder/'demobro-status.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
                    state=result.get('status') or result.get('execution_state') or result.get('render',{}).get('status')
                    display=f'{state} · {result.get("progress_pct",0)} % · {result.get("progress_label","")}'
                    if display!=previous:progress('DemoBro : '+display);previous=display
                    if result.get('execution_state')=='action_required':raise RuntimeError('DemoBro demande une action : '+str(result.get('user_action',{})))
                    if state in ('completed','success','done','finished'):
                        media=result.get('video_url') or result.get('output_url') or result.get('download_url') or result.get('output_file')
                        if not media and isinstance(result.get('outputs'),dict):media=result['outputs'].get('video_url') or result['outputs'].get('mp4')
                        if not media:raise RuntimeError('Rendu terminé mais URL vidéo absente. Consulter demobro-status.json.')
                        if media.startswith('/'):media='https://demobro.com'+media
                        host=urlparse(media).hostname or ''
                        media_headers=account_headers() if host=='demobro.com' and urlparse(media).path.startswith('/api/') else {}
                        response=httpx.get(media,headers=media_headers,follow_redirects=True,timeout=180);response.raise_for_status()
                        target=folder/'capsule-demobro.mp4';target.write_bytes(response.content)
                        from .video import duration
                        return {'video':f'/outputs/{folder.name}/capsule-demobro.mp4','duration':round(duration(target)),'video_provider':'demobro','demobro_render_id':render_id,'captions':None}
                    if state in ('failed','error','cancelled','canceled'):raise RuntimeError('Le rendu DemoBro a échoué : '+str(result.get('error_message') or result.get('error') or state))
                    time.sleep(5)
                raise TimeoutError('DemoBro : rendu toujours en cours. Identifiant conservé pour reprise sans nouveau débit.')
        finally:client.close()
