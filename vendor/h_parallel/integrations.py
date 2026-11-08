import time
import mimetypes
from pathlib import Path
from urllib.parse import urlparse
import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).parent
CONFIG={**dotenv_values(ROOT.parent/'credentials/.env.hackathon'),**dotenv_values(ROOT/'.env')}
DOMAINS=['eduscol.education.fr','education.fr','reseau-canope.fr','ac-grenoble.fr','ac-versailles.fr']

def key(name):
    import os
    value=os.getenv(name) or CONFIG.get(name)
    if not value: raise RuntimeError(f'Clé manquante : {name}')
    return value

def transcribe(path):
    headers={'x-gladia-key':key('GLADIA_API_KEY')}
    with httpx.Client(timeout=90) as client:
        with path.open('rb') as f:
            content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            upload=client.post('https://api.gladia.io/v2/upload',headers=headers,files={'audio':(path.name,f,content_type)})
        upload.raise_for_status()
        job=client.post('https://api.gladia.io/v2/pre-recorded',headers=headers,json={'audio_url':upload.json()['audio_url'],'language_config':{'languages':['fr']}})
        job.raise_for_status(); info=job.json()
        for _ in range(90):
            response=client.get(info['result_url'],headers=headers); response.raise_for_status(); data=response.json()
            if data['status']=='done':
                transcription=data['result']['transcription']
                return {'provider':'Gladia','job_id':info['id'],'text':transcription['full_transcript'],'utterances':transcription.get('utterances',[])}
            if data['status']=='error': raise RuntimeError('La transcription Gladia a échoué.')
            time.sleep(2)
    raise TimeoutError('Gladia : transcription non terminée après trois minutes.')

def search(query):
    response=httpx.post('https://api.linkup.so/v1/search',headers={'Authorization':'Bearer '+key('LINKUP_API_KEY')},json={'q':query,'depth':'standard','outputType':'searchResults','includeDomains':DOMAINS,'maxResults':4},timeout=90)
    response.raise_for_status()
    sources=[]
    for item in response.json().get('results',[]):
        u=urlparse(item.get('url','')); host=(u.hostname or '').lower()
        if u.scheme in ('https','http') and any(host==d or host.endswith('.'+d) for d in DOMAINS):
            sources.append({'id':f'web-{len(sources)+1}','title':item.get('name',host),'url':item['url'],'excerpt':item.get('content','')[:2200],'type':'external'})
    return {'provider':'Linkup','query':query,'sources':sources}
