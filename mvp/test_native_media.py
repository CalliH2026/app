"""Only the vocal frozen for a native job is served to its transcript player."""
from fastapi.testclient import TestClient
from . import app as application


def test_frozen_vocal_is_accessible_without_exposing_other_inputs(monkeypatch, tmp_path):
    folder = tmp_path / 'native-case'
    folder.mkdir()
    (folder / 'parent-audio.wav').write_bytes(b'RIFF-test-vocal')
    (folder / 'private.wav').write_bytes(b'not-an-output')
    (folder / 'state.json').write_text('{"private":true}')
    monkeypatch.setattr(application, 'DATA', tmp_path)
    monkeypatch.setattr(application, 'JOBS', {'native-case': {
        'source_kind': 'pronote_native_dossier', 'captured_audio': 'parent-audio.wav'}})
    client = TestClient(application.app)
    response = client.get('/outputs/native-case/parent-audio.wav')
    assert response.status_code == 200 and response.content == b'RIFF-test-vocal'
    assert response.headers['content-type'].startswith('audio/')
    assert client.get('/outputs/native-case/private.wav').status_code == 404
    assert client.get('/outputs/native-case/state.json').status_code == 404
    assert client.get('/outputs/other-case/parent-audio.wav').status_code == 404
    application.JOBS['native-case']['captured_audio'] = 'private.wav'
    assert client.get('/outputs/native-case/private.wav').status_code == 404


def test_notification_feed_keeps_latest_native_case_after_job_reload(monkeypatch):
    from . import native_ai
    def job(day):
        return {'status':'ready', 'source_kind':'pronote_native_dossier', 'dossier':{'display_label':'Fanny · 3A'},
                'events':[{'stage':'ready','time':f'2027-01-{day:02d}T12:00:00+01:00'}]}
    jobs={'latest':{'id':'latest',**job(30)}}
    jobs.update({f'old-{day}':{'id':f'old-{day}',**job(day)} for day in range(1,22)})
    monkeypatch.setattr(application,'JOBS',jobs)
    monkeypatch.setattr(native_ai,'status',lambda:{'status':'waiting'})
    feed=application.notification_feed()
    assert len(feed)==20 and feed[-1]['id']=='latest'
    assert feed[-1]['url']=='/native?job=latest'
    assert feed[-1]['label']=='Fanny · 3A'


def test_failed_or_revising_job_does_not_announce_its_old_ready_event(monkeypatch):
    from . import native_ai
    record={'id':'revised','status':'failed','source_kind':'pronote_native_dossier',
            'events':[{'stage':'video','time':'2027-01-30T11:00:00+01:00'},
                      {'stage':'ready','time':'2027-01-30T12:00:00+01:00'}]}
    monkeypatch.setattr(application,'JOBS',{'revised':record})
    monkeypatch.setattr(native_ai,'status',lambda:{'status':'waiting'})
    assert application.notification_feed()==[]
    record['status']='preparing'
    assert all(item['phase']!='ready' for item in application.notification_feed())


def test_native_resume_route_checks_job_origin_and_surfaces_frozen_input_errors(monkeypatch):
    from . import native_pipeline
    calls=[]
    def resume(job_id):
        calls.append(job_id)
        raise ValueError('Le vocal figé a changé depuis l’ouverture native.')
    monkeypatch.setattr(native_pipeline,'resume_failed',resume)
    monkeypatch.setattr(application,'JOBS',{
        'modern':{'source_kind':'pronote_modern_dossier','status':'failed'},
        'native':{'source_kind':'pronote_native_dossier','status':'failed'}})
    client=TestClient(application.app)
    assert client.post('/api/native/preparations/missing/resume').status_code==404
    assert client.post('/api/native/preparations/modern/resume').status_code==404
    assert calls==[]
    response=client.post('/api/native/preparations/native/resume')
    assert response.status_code==409
    assert response.json()['detail']=='Le vocal figé a changé depuis l’ouverture native.'
    assert calls==['native']
