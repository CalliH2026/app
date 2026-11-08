"""Poll only the separate PRONOTE example bottle through documented Win32 reads."""
import json
import subprocess
import threading
import time
from pathlib import Path
import httpx
from .prepare_demo import ROOT,DATA,RUNTIME,BOTTLE,bundle

STOP=threading.Event()
THREAD=None


def read_once():
    binary=BOTTLE/'drive_c/H-Demo/pronote-context.exe'
    source=ROOT/'native/pronote_context.c'
    if not binary.exists() or source.stat().st_mtime>binary.stat().st_mtime:
        binary.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['x86_64-w64-mingw32-gcc','-Os','-municode','-mconsole','-o',str(binary),str(source),'-luser32','-lkernel32'],check=True,capture_output=True,timeout=30)
    output=BOTTLE/'drive_c/H-Demo/context.json'
    subprocess.run([str(RUNTIME/'bin/wine'),'--bottle',str(BOTTLE),'--no-update','--wait-children',str(binary),'C:\\H-Demo\\context.json'],check=True,capture_output=True,timeout=12)
    return json.loads(output.read_text())


def payload(snapshot):
    windows=snapshot.get('windows',[])
    if not windows:return {'state':'window_not_found','source_kind':'pronote_macos','app_name':'PRONOTE Monoposte','method':'win32_controls','message':'Le processus de démonstration n’a pas encore de fenêtre visible.'}
    selected=next((w for w in windows if 'base exemple' in w['title'].casefold()),windows[0])
    lines=[selected['title']]+[c['text'] for c in selected.get('controls',[])]
    from datetime import datetime
    return {'state':'observed','source_kind':'pronote_macos','app_name':'PRONOTE Monoposte 2026','bundle_id':'local.hcompany.pronote-demo','pid':selected['pid'],'method':'win32_controls','window_title':selected['title'],'visible_text':'\n'.join(dict.fromkeys(lines))[:16000],'observed_at':datetime.now().astimezone().isoformat(),'message':'Lecture locale des contrôles du vrai PRONOTE dans la base d’exemple isolée.'}


def start():
    global THREAD
    if THREAD and THREAD.is_alive():return
    STOP.clear()
    def worker():
        from ..native_bridge import bridge_token
        with httpx.Client(timeout=10,headers={'Authorization':'Bearer '+bridge_token()}) as client:
            while not STOP.is_set():
                try:
                    response=client.post('http://127.0.0.1:8000/api/native/context',json=payload(read_once()));response.raise_for_status()
                    # With the document observer active, paid H work starts
                    # from a genuine copy-open event, not every technical
                    # change of the owner-drawn window. Manual diagnostics
                    # retain /api/native/ai/prepare.
                    from .document_service import THREAD as document_thread
                    if not (document_thread and document_thread.is_alive()):
                        from ..native_ai import schedule
                        from ..native_bridge import context
                        schedule(context())
                except Exception as exc:
                    (DATA/'win32-bridge-status.json').write_text(json.dumps({'state':'read_error','message':str(exc)[:400]}))
                STOP.wait(4)
    THREAD=threading.Thread(target=worker,daemon=True);THREAD.start()
