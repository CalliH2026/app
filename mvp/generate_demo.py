"""Generate a private DemoBro film of the implemented parallel-report prototype.

Only a frozen frontend snapshot and fictitious fixture are temporarily published.
This never proxies localhost APIs, credentials, school sessions or imported audio.
"""
from __future__ import annotations
import contextlib, copy, hashlib, json, mimetypes, re, select, shutil, subprocess, threading, time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import httpx, yaml
from .demobro import DemoBro, account_headers

ROOT=Path(__file__).parent.resolve()
OUT=ROOT/'data'/'product-demo-v2'
JOB='film-snapshot'
CAPTURE_BROWSER='chrome'

def log(message): print(message,flush=True)
def write(name,value): (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))

@contextlib.contextmanager
def public_snapshot():
    OUT.mkdir(parents=True,exist_ok=True)
    assets=OUT/'snapshot-static'
    if not assets.exists():shutil.copytree(ROOT/'static',assets)
    fixture=json.loads((ROOT/'fixtures/alex.json').read_text())
    now=datetime.now(timezone.utc)
    fixture.update(server_time=now.isoformat(),appointment_at=(now+timedelta(hours=2)).isoformat())
    # This known, locally generated offline dossier contains fictitious data only.
    job=json.loads((ROOT/'data/ef72999bdb10/state.json').read_text())
    job.update(id=JOB,status='ready',mode='demo',video_provider='local',approved=False,decision=None,kept=False,notification_dismissed=False,video=f'/outputs/{JOB}/capsule.mp4',captions=f'/outputs/{JOB}/captions.vtt')
    job.pop('session_id',None)
    fixture['audio']={k:v for k,v in fixture['audio'].items() if k in ('points','progress')}
    request_log=OUT/'requests.jsonl'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,data,mime='application/json',status=200):
            payload=json.dumps(data,ensure_ascii=False).encode() if mime=='application/json' else data
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def record(self):
            with request_log.open('a') as f:f.write(json.dumps({'at':time.time(),'method':self.command,'path':urlparse(self.path).path})+'\n')
        def do_GET(self):
            self.record();path=urlparse(self.path).path
            if path in ('/','/notes','/copy','/report','/report-proof'):
                data=(assets/'index.html').read_text()
                # Capture state hooks call the actual app functions; no redesigned screens.
                bootstrap=''
                if path=='/copy':bootstrap=f"current=await api('/api/jobs/{JOB}');showView('copie');draw(current);"
                elif path in ('/report','/report-proof'):
                    bootstrap=f"current=await api('/api/jobs/{JOB}');showView('copie');draw(current);panel(true);"+("document.getElementById('report').scrollTop=610;" if path=='/report-proof' else '')
                if bootstrap:data=data.replace('</body>',f"<script>let filmStart=setInterval(async()=>{{if(typeof fixture!=='undefined'&&fixture){{clearInterval(filmStart);{bootstrap}}}}},30);</script></body>")
                self.reply(data.encode(),'text/html; charset=utf-8');return
            if path=='/api/fixture':self.reply(fixture);return
            if path==f'/api/jobs/{JOB}':self.reply(job);return
            if path=='/api/reports':self.reply([{'id':JOB,'scenario':'points','status':'ready','question':job['dossier']['question']}] if job.get('kept') else []);return
            if path=='/api/notifications/status':self.reply({'status':'not_enabled'});return
            if path.startswith('/static/'):
                file=(assets/path.removeprefix('/static/')).resolve()
                if assets.resolve() not in file.parents or not file.is_file():self.send_error(404);return
            elif path in ('/audio/points','/audio/progress'):
                file=ROOT/'fixtures'/fixture['audio'][path.rsplit('/',1)[1]]['file']
            elif path in (f'/outputs/{JOB}/capsule.mp4',f'/outputs/{JOB}/captions.vtt'):
                file=ROOT/'data/ef72999bdb10'/path.rsplit('/',1)[1]
            else:self.send_error(404);return
            self.reply(file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        def do_POST(self):
            self.record();path=urlparse(self.path).path
            length=int(self.headers.get('Content-Length','0'))
            if length>8192:self.send_error(413);return
            try:data=json.loads(self.rfile.read(length) or '{}')
            except ValueError:self.send_error(400);return
            if path=='/api/open-copy':self.reply(job);return
            if path==f'/api/jobs/{JOB}/decision':
                choice=data.get('decision')
                if choice not in ('keep','dismiss'):self.send_error(400);return
                job['kept']=job.get('kept') or choice=='keep';job['decision']='keep' if job['kept'] else choice;job['notification_dismissed']=choice=='dismiss';self.reply(job);return
            if path==f'/api/jobs/{JOB}/approve':job['approved']=True;self.reply(job);return
            self.send_error(404)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    local=f'http://127.0.0.1:{server.server_port}'
    (OUT/'local-url.txt').write_text(local)
    tunnel_log=(OUT/'tunnel.log').open('w')
    p=subprocess.Popen(['cloudflared','tunnel','--url',local,'--protocol','http2','--no-autoupdate'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+100;base=None
        while time.monotonic()<deadline:
            if p.poll() is not None:raise RuntimeError('Tunnel exited; see tunnel.log')
            if select.select([p.stderr],[],[],1)[0]:
                line=p.stderr.readline();tunnel_log.write(line);tunnel_log.flush()
                match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
                if match:base=match.group(0);break
        if not base:raise RuntimeError('No public snapshot URL')
        def drain():
            for line in p.stderr:tunnel_log.write(line);tunnel_log.flush()
        threading.Thread(target=drain,daemon=True).start()
        host=urlparse(base).hostname
        for _ in range(30):
            try:
                if httpx.get(base+'/notes',timeout=15).status_code==200:break
            except httpx.HTTPError:
                ips=subprocess.check_output(['dig','+short',host],text=True).splitlines()
                addresses=[ip for ip in ips if re.fullmatch(r'[0-9.]+',ip)]
                if addresses:
                    checked=subprocess.run(['curl','--silent','--show-error','--fail','--max-time','15','--resolve',f'{host}:443:{addresses[0]}',base+'/notes'],capture_output=True)
                    if checked.returncode==0 and b'Notes' in checked.stdout:break
            time.sleep(2)
        else:raise RuntimeError('Snapshot unreachable')
        (OUT/'public-url.txt').write_text(base)
        log('Snapshot ready '+local)
        yield base
    finally:
        p.terminate()
        try:p.wait(timeout=10)
        except subprocess.TimeoutExpired:p.kill();p.wait()
        server.shutdown();server.server_close();tunnel_log.close()

def config(base):
    def click(selector,narration,wait=2):return {'action':'click','locator':{'type':'css','value':selector},'narration':narration,'wait':wait}
    steps=[
      {'action':'navigate','url':base+'/notes','wait':2,'narration':'Le professeur consulte les évaluations. Dans ce dossier fictif, un rendez-vous avec les parents d’Alex est prévu dans deux heures.'},
      click('#opencopy','Il ouvre simplement la copie. La préparation démarre en parallèle, sans prompt à rédiger.'),
      {'action':'navigate','url':base+'/copy','wait':2,'narration':'Le professeur continue son travail. Le résultat est juste, mais la justification et la conclusion manquent.'},
      click('#agenttoggle','Le rapport H rassemble la question des parents et les pièces pertinentes, dans un volet indépendant.'),
      {'action':'navigate','url':base+'/report','wait':2,'narration':'La question est reliée aux preuves scolaires. Le professeur peut consulter les sources et relire une explication préparée.'},
      click('#keep','Keep conserve le rapport dans le dossier. Dismiss permet de le masquer, sans interrompre le travail.'),
      click('#closepanel','Le professeur revient à sa copie. Il garde la main sur la relecture et le partage avec la famille.'),
    ]
    return {'metadata':{'title':'H en parallèle — parcours du prototype','description':'Capture réelle du frontend de démonstration avec données fictives. Cette vidéo illustre le rapport parallèle ; elle ne prouve pas une intégration à un établissement PRONOTE.','version':'2.0.0'},'voice':{'engine':'gtts','voice_id':'fr','language':'fr'},'subtitle':{'enabled':True,'style':'classic'},'output':{'branding':False},'scenarios':[{'name':'Le professeur travaille, H prépare','url':base+'/notes','browser':CAPTURE_BROWSER,'viewport':{'width':1600,'height':1000},'steps':steps}]}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    ledger=OUT/'submission.json'
    c=DemoBro()
    try:
        # Discovery must precede using remote names, including repeat executions.
        names={t['name'] for t in c.tools()}
        for name in ('validate_demo_config','probe_demo_config','estimate_demo_cost','render_demo_from_yaml','get_render'):
            if name not in names:raise RuntimeError('Missing DemoBro tool '+name)
        with public_snapshot() as base:
            raw=yaml.safe_dump(config(base),allow_unicode=True,sort_keys=False)
            (OUT/'demo.yaml').write_text(raw)
            if ledger.exists():
                record=json.loads(ledger.read_text());rid=record.get('render_id')
                if not rid:raise RuntimeError('Unconfirmed submission; inspect account, do not resubmit.')
                log('Following existing render '+rid)
            else:
                validation=c.call('validate_demo_config',{'yaml_config':raw,'interactive':True});write('validation.json',validation)
                if not validation.get('valid'):raise RuntimeError('Invalid DemoDSL '+str(validation)[:700])
                log('Config valid; probing observed selectors')
                probe=c.call('probe_demo_config',{'yaml_config':raw});write('probe.json',probe)
                log('Probe summary '+str({k:probe.get(k) for k in ('resolved','report','unresolved','ambiguous')})[:1000])
                if probe.get('resolved') is False or probe.get('unresolved',0)>0 or probe.get('ambiguous',0)>0:raise RuntimeError('Selectors not resolved; do not render')
                estimate=c.call('estimate_demo_cost',{'yaml_config':raw});write('estimate.json',estimate)
                if estimate.get('affordable') is False:raise RuntimeError('Render not affordable')
                log('Estimated '+str(estimate.get('total_credits'))+' credits; private interactive render')
                ledger.write_text(json.dumps({'state':'submitting','at':time.time()}))
                result=c.call('render_demo_from_yaml',{'name':'H en parallèle — interface de démonstration','description':config(base)['metadata']['description'],'project_name':'H Company — rapport parallèle — prototype','yaml_config':raw,'interactive':True,'animation_style':'auto','is_public':False})
                rid=result.get('render_id') or result.get('id')
                write('submission.json',{'render_id':rid,'response':result})
                if not rid:raise RuntimeError('Submission not confirmed; no retry')
                log('Render '+rid)
            previous=None
            for _ in range(180):
                status=c.call('get_render',{'render_id':rid});write('status.json',status)
                summary={k:status.get(k) for k in ('status','progress_pct','progress_label','elapsed_seconds','execution_state')}
                key={k:v for k,v in summary.items() if k!='elapsed_seconds'}
                if key!=previous:log(str(summary));previous=key
                if status.get('execution_state')=='action_required':raise RuntimeError('User action required '+str(status.get('user_action')))
                if status.get('status') in ('completed','success','done'):
                    url=status.get('video_url')
                    if not url:raise RuntimeError('No video URL')
                    if url.startswith('/'):url='https://demobro.com'+url
                    host=urlparse(url).hostname or ''
                    headers=account_headers() if host=='demobro.com' else {}
                    r=httpx.get(url,headers=headers,follow_redirects=True,timeout=180);r.raise_for_status()
                    target=OUT/'h-parallel-demo.mp4';target.write_bytes(r.content)
                    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(target)]));write('ffprobe.json',info)
                    log('Completed '+str(target));return
                if status.get('status') in ('failed','error','cancelled'):raise RuntimeError('DemoBro failed: '+str(status.get('error_message')))
                time.sleep(5)
            raise TimeoutError('Render still running; use existing render ID')
    finally:c.close()

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',choices=('chrome','webkit','firefox'),default='chrome')
    parser.add_argument('--output',type=Path,default=OUT)
    args=parser.parse_args()
    CAPTURE_BROWSER=args.browser;OUT=args.output.resolve()
    main()
