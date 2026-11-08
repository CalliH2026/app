"""Critical contracts; run with pytest mvp/test_mvp.py. No paid API calls."""
import hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from . import engine
from .app import app

client=TestClient(app)

def test_synthetic_school_and_no_source_tree_exposure():
    for page in ('agenda','messages','documents','consigne','bareme','copie','methode'):
        r=client.get('/school/'+page)
        assert r.status_code==200 and 'DÉMONSTRATION INDÉPENDANTE' in r.text
    assert client.get('/school/invente').status_code==404
    assert "fetch('/api/open-copy'" not in client.get('/school/copie?agent=1').text
    assert "fetch('/api/open-copy'" in client.get('/school/copie').text
    assert client.get('/credentials/.env.hackathon').status_code==404
    assert client.get('/outputs/unknown/state.json').status_code==404
    assert client.get('/',headers={'host':'evil.example'}).status_code==403
    assert client.post('/api/open-copy',headers={'origin':'https://evil.example'},json={}).status_code==403

def test_approval_only_after_ready(monkeypatch):
    monkeypatch.setattr(engine,'save',lambda job:None)
    monkeypatch.setattr('mvp.app.save',lambda job:None)
    monkeypatch.setitem(engine.JOBS,'testjob',{'id':'testjob','status':'preparing','approved':False})
    assert client.post('/api/jobs/testjob/approve').status_code==409
    engine.JOBS['testjob']['status']='ready'
    assert client.post('/api/jobs/testjob/approve').json()['approved'] is True

def test_reopening_is_idempotent(monkeypatch,tmp_path):
    monkeypatch.setattr(engine,'save',lambda job:None)
    monkeypatch.setattr(engine,'JOBS',{})
    # A fake worker counts launches without invoking H or rendering videos.
    calls=[]
    class Worker:
        def __init__(self,**kw): calls.append(kw)
        def start(self): pass
    monkeypatch.setattr(engine.threading,'Thread',Worker)
    a=engine.launch('points','demo','http://localhost:8000')
    b=engine.launch('points','demo','http://localhost:8000')
    assert a['id']==b['id'] and len(calls)==1
    c=engine.launch('progress','demo','http://localhost:8000')
    assert c['id']!=a['id'] and len(calls)==2

def test_change_voice_changes_evidence_and_video():
    points=engine.offline_dossier('points'); progress=engine.offline_dossier('progress')
    assert points['question']!=progress['question']
    assert points['evidence']!=progress['evidence']
    assert points['scenes']!=progress['scenes']
    assert len(points['scenes'])==len(progress['scenes'])==4

def test_linkup_allowlist(monkeypatch):
    from . import integrations
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'results':[{'name':'Official','url':'https://eduscol.education.fr/exemple','content':'Raisonnement'},{'name':'Bad','url':'https://eduscol.education.fr.evil.com/example'},{'name':'JS','url':'javascript:alert(1)'}]}
    monkeypatch.setattr(integrations,'key',lambda _: 'test')
    monkeypatch.setattr(integrations.httpx,'post',lambda *a,**kw:Response())
    result=integrations.search('Pythagore justification')
    assert len(result['sources'])==1
    assert result['sources'][0]['id']=='web-1'

def test_verbatim_proofs_and_unknown_sources():
    valid=engine.offline_dossier('points')
    assert engine.checked_answer(valid,[])['intent']=='points'
    invalid=engine.offline_dossier('points')
    invalid['evidence'][0]['quote']='La note est décidée par le résultat seul.'
    with pytest.raises(ValueError,match='Citation non conforme'): engine.checked_answer(invalid,[])
    invalid=engine.offline_dossier('points')
    invalid['scenes'][0]['source_ids']=['web-invente']
    with pytest.raises(ValueError,match='source citée est inconnue'): engine.checked_answer(invalid,[])

def test_keep_then_dismiss_preserves_report(monkeypatch):
    monkeypatch.setattr('mvp.app.save',lambda job:None)
    monkeypatch.setitem(engine.JOBS,'decision-test',{'id':'decision-test','status':'ready','scenario':'points','events':[]})
    keep=client.post('/api/jobs/decision-test/decision',json={'decision':'keep'})
    assert keep.status_code==200 and keep.json()['kept'] is True
    dismissed=client.post('/api/jobs/decision-test/decision',json={'decision':'dismiss'}).json()
    assert dismissed['kept'] is True and dismissed['notification_dismissed'] is True
    assert any(j['id']=='decision-test' for j in client.get('/api/reports').json())
    assert not any(j['id']=='decision-test' for j in client.get('/api/notifications/feed').json())

def test_native_connector_authentication_and_truthful_readiness(monkeypatch,tmp_path):
    from . import native_bridge
    monkeypatch.setattr(native_bridge,'STATE',tmp_path/'context.json')
    monkeypatch.setattr(native_bridge,'read_settings',lambda:{'enabled':True,'mode':'example'})
    payload={'state':'observed','method':'win32_controls','app_name':'PRONOTE Monoposte','window_title':'PRONOTE - Base Exemple.not','visible_text':'Base Exemple','source_kind':'pronote_macos'}
    assert client.post('/api/native/context',json=payload).status_code==401
    headers={'authorization':'Bearer '+native_bridge.bridge_token()}
    r=client.post('/api/native/context',json=payload,headers=headers)
    assert r.status_code==200
    state=client.get('/api/native/context').json()
    assert state['connection_state']=='example_open'
    assert state['report']['video_ready'] is False
    assert 'notes' not in state and 'grade' not in state
    payload.update(visible_text='Identifiant : test\nMot de passe : secret-test',window_title='Connexion')
    client.post('/api/native/context',json=payload,headers=headers)
    assert 'secret-test' not in client.get('/api/native/context').text

def test_native_notification_keeps_original_context(monkeypatch,tmp_path):
    from . import native_bridge
    import json
    monkeypatch.setattr(native_bridge,'DATA',tmp_path)
    monkeypatch.setattr(native_bridge,'STATE',tmp_path/'current.json')
    old_id='a'*16;new_id='b'*16
    active={'context_id':new_id,'report':{'title':'Current native view'},'state':'observed'}
    native_bridge.STATE.write_text(json.dumps(active))
    prepared=tmp_path/'native-prepared';prepared.mkdir()
    original={'context_id':old_id,'report':{'title':'Original native view'},'h_report':{'summary':'Original H report'}}
    (prepared/(old_id+'.json')).write_text(json.dumps(original))
    kept=native_bridge.decide('keep',old_id)
    assert kept['context_id']==old_id and kept['h_report']['summary']=='Original H report'
    assert json.loads(native_bridge.STATE.read_text())['context_id']==new_id
    assert (tmp_path/'native-reports'/(old_id+'.json')).exists()
