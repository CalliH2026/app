"""Capture the current Parallèle frontend with François FDE in DemoBro."""
import json
import time
from pathlib import Path
import yaml
from .generate_workspace_demo import (ROOT, freeze_snapshot, snapshot_server, public_tunnel,
                                     write_json, log, follow)
from .demobro import DemoBro

OUTPUT = ROOT / 'data' / 'hackathon-francois-fde-v3'
PRESENTER = '646507f4-0c10-48d2-b747-b8f4ce84b63a'
NAME = 'Parallèle — Hackathon — François FDE — dernière interface'

def config(base):
    def nav(path, text):
        return {'action':'navigate','url':base+path,'wait':2,'narration':text}
    def click(selector, text):
        return {'action':'click','locator':{'type':'css','value':selector},'wait':2,'narration':text}
    steps = [
        nav('/', 'Bonjour, je suis François. Voici Parallèle : un agent qui prépare le rendez-vous parents-professeur pendant que le professeur travaille.'),
        nav('/?view=management', 'Dans cette nouvelle interface, on retrouve les élèves et leurs évaluations. Ces fiches de suivi restent locales, distinctes des pièces scolaires.'),
        nav('/', 'Un rendez-vous approche. Les parents demandent pourquoi Alex perd des points alors que son résultat est juste.'),
        click('#main .meeting-card [data-doc="copie"]', 'J’ouvre sa copie : la préparation démarre sans prompt. Ce film rejoue une exécution réelle sur un dossier fictif.'),
        click('#navigation [data-page="messages"]', 'Le professeur poursuit ses échanges. En parallèle, Gladia transcrit le vocal ; H consulte la copie, la consigne et le barème.'),
        nav('/film/ready', 'Voici le rapport. H rapproche les critères scolaires et la question des parents. Linkup apporte des ressources pour progresser.'),
        click('#agent-content .source-chip[data-source="bareme"]', 'Chaque citation ouvre la pièce exacte utilisée. On peut vérifier ce qui justifie l’explication, avant de la partager.'),
        click('[data-close="source-dialog"]', 'La réponse ne reste pas dans une conversation : une capsule française est préparée pour le rendez-vous.'),
        nav('/film/video', 'La vidéo rassemble l’explication personnalisée. Le professeur la relit et garde la décision finale.'),
        click('#keep', 'Avec Keep, le rapport est conservé. Parallèle prépare la suite ; le professeur garde la main.'),
        click('.rail [data-page="reports"]', 'Les rapports, leurs sources et leurs vidéos restent accessibles. C’est Parallèle, notre démonstration pour le hackathon H Company et quarante-deux AI.'),
    ]
    return {'metadata':{'title':NAME,'version':'2.0.0','description':'Frontend actuel Parallèle capturé le 7 novembre 2026. Données fictives, relecture condensée du job connecté enregistré. Présentateur François FDE avec voix du profil. Aucun compte établissement ni synchronisation native prétendus.'},
            'languages':{'default':'fr','targets':[]},
            'voice':{'engine':'custom','voice_id':PRESENTER,'speed':1.0,'collision_strategy':'shift'},
            'subtitle':{'enabled':True,'style':'classic','font_size':28,'position':'bottom','max_words_per_line':10},
            'output':{'branding':False,'filename':'Parallele-Hackathon-Francois-FDE.mp4'},
            'scenarios':[{'name':'Parallèle, avec François FDE','url':base+'/','browser':'chrome',
                          'viewport':{'width':1600,'height':1000},
                          'avatar':{'enabled':True,'provider':'heygen','presenter_id':PRESENTER,'position':'bottom-left','size':180,'shape':'circle'},
                          'steps':steps}]}

def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    if (OUTPUT/'submission.json').exists():
        raise RuntimeError('Submission exists: follow it, never submit twice.')
    freeze_snapshot('78f6163fe6ec',OUTPUT)
    with snapshot_server(OUTPUT) as local, public_tunnel(local,OUTPUT) as base:
        c=DemoBro()
        try:
            presenters=c.call('list_presenters',{})
            presenter=next(p for p in presenters if p['id']==PRESENTER)
            assert presenter['is_active'] and presenter['consented'] and presenter['name'].lower()=='françois fde'
            write_json(OUTPUT/'presenter.json',presenter)
            raw=yaml.safe_dump(config(base),allow_unicode=True,sort_keys=False)
            (OUTPUT/'demo.yaml').write_text(raw)
            validation=c.call('validate_demo_config',{'yaml_config':raw,'interactive':True})
            write_json(OUTPUT/'validation.json',validation)
            log('VALIDATION '+str(validation))
            if not validation.get('valid'):raise RuntimeError('Invalid configuration')
            # The probe's browser-only schema does not accept presenter_id.
            # Probe identical actions without the separately validated media block.
            probe_config=config(base)
            probe_config['scenarios'][0].pop('avatar')
            probe=c.call('probe_demo_config',{'yaml_config':yaml.safe_dump(probe_config,allow_unicode=True)})
            write_json(OUTPUT/'probe.json',probe)
            log('PROBE '+str(probe))
            if probe.get('resolved') is False or probe.get('unresolved',0)>0 or probe.get('ambiguous',0)>0:raise RuntimeError('Selector probe failed')
            for name in ('estimate_demo_cost','estimate_demo_duration'):
                result=c.call(name,{'yaml_config':raw});write_json(OUTPUT/(name+'.json'),result);log(name+' '+str(result))
                if result.get('affordable') is False or result.get('long_render'):raise RuntimeError('Estimate requires review before submission')
            project=c.call('create_project',{'name':NAME,'yaml_config':raw,'description':config(base)['metadata']['description']})
            write_json(OUTPUT/'project.json',project)
            project_id=project['id']
            brief=c.call('get_project_brief',{'project_id':project_id});write_json(OUTPUT/'brief.json',brief)
            log('READY TO RENDER')
            for _ in range(240):
                if (OUTPUT/'launch-reviewed').exists():break
                time.sleep(1)
            else:raise TimeoutError('Review coordination expired')
            write_json(OUTPUT/'submission.json',{'state':'submitting','project_id':project_id})
            result=c.call('render_demo_from_yaml',{'name':NAME,'project_id':project_id,'yaml_config':raw,'interactive':True})
            render_id=result.get('render_id') or result.get('id')
            write_json(OUTPUT/'submission.json',{'render_id':render_id,'project_id':project_id,'response':result})
            log('SUBMITTED '+str(render_id))
            if not render_id:raise RuntimeError('No confirmed render ID; do not retry')
            follow(c,render_id,OUTPUT,max_polls=720)
        finally:c.close()

if __name__=='__main__':main()
