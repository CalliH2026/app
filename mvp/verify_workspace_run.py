"""Verify a completed teacher-triggered run against its immutable local evidence."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from .engine import DATA, checked_answer


def verify(job_id):
    job=json.loads((DATA/job_id/'state.json').read_text())
    assert job['status']=='ready' and job['mode']=='live'
    assert job.get('workspace_origin')=='new_pronote'
    assert job['workspace_trigger']['trigger']=='modern_copy_opened'
    assert job.get('session_id')
    assert job['transcription']['provider']=='Gladia'
    assert job['search']['provider']=='Linkup'
    context=job['input_context']
    checked_answer(job['dossier'],job['search']['sources'],context['documents'])
    audio=DATA/job_id/job['captured_audio']
    assert hashlib.sha256(audio.read_bytes()).hexdigest()==context['audio'][job['scenario']]['content_hash']
    assert job['dossier']['appointment']==context['appointment']
    video=DATA/job_id/'capsule.mp4'
    media=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-show_streams','-show_format','-of','json',str(video)]))
    assert {stream['codec_type'] for stream in media['streams']} >= {'video','audio','subtitle'}
    assert len(job['dossier']['scenes'])==4
    return {'job_id':job_id,'status':'verified','trigger':'modern_copy_opened','source_kind':'local_demo',
            'session_id':job['session_id'],'transcription_provider':'Gladia','search_provider':'Linkup',
            'intent':job['dossier']['intent'],'query':job['search']['query'],
            'source_ids':sorted({id for e in job['dossier']['evidence'] for id in e['source_ids']}),
            'video_seconds':round(float(media['format']['duration']),2),'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),
            'native_synced':False,'streams':[{'type':s['codec_type'],'codec':s['codec_name']} for s in media['streams']]}

if __name__=='__main__':
    result=verify(sys.argv[1])
    (DATA/sys.argv[1]/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
