"""François plays the teacher in a film of a verified, fictional PRONOTE run."""
import hashlib
import json
from pathlib import Path

import yaml


NAME = 'Parallèle — François professeur — appels réels'
PRESENTER = '646507f4-0c10-48d2-b747-b8f4ce84b63a'


def config(base, presenter_id=PRESENTER):
    """Use DemoBro's packaged four-scene starter with the teacher preset."""
    template_dir = Path(__file__).parent / 'templates'
    value = yaml.safe_load((template_dir / 'demobro-starter.yaml').read_text())
    preset = yaml.safe_load((template_dir / 'professeur.yaml').read_text())
    value['metadata'].update(title=preset['name'], description=(
        'François joue le professeur avec son profil personnel consenti. '
        'Relecture d’une exécution réelle sur données fictives : onze appels, six outils. '
        'Modèle officiel DemoBro « Ma première démo — succès garanti », effets d’origine.'))
    value['languages'] = {'default': preset['language'], 'targets': []}
    value['voice'] = {'engine': 'custom', 'voice_id': presenter_id, 'speed': 1.0,
                      'collision_strategy': 'shift'}
    scenario = value['scenarios'][0]
    scenario.update(name=preset['name'], url=base + '/')
    scenario['avatar'] = {'enabled': True, 'provider': 'heygen', 'presenter_id': presenter_id,
                          'position': 'bottom-left', 'size': 180, 'shape': 'circle'}
    for step in scenario.get('pre_steps', []):
        if step.get('action') == 'navigate':
            step['url'] = base + '/'
    for step, path, narration in zip(scenario['steps'], preset['pages'], preset['narrations'], strict=True):
        step.update(action='navigate', url=base + path, narration=narration)
        for field in ('direction', 'pixels', 'smooth_scroll'):
            step.pop(field, None)
    value['output'].update(filename='Parallele-Francois-Professeur.mp4', branding=False)
    return value


def personalize_snapshot(output):
    """Change film presentation only; keep all recorded evidence untouched."""
    replacements = {'Bonjour, Madame Laurent.': 'Bonjour, Monsieur Amat.',
                    'Mme Laurent': 'M. Amat'}
    changed = []
    for name in ('workspace.js', 'workspace.html'):
        path = output / 'snapshot-static' / name
        text = path.read_text()
        for before, after in replacements.items():
            text = text.replace(before, after)
        path.write_text(text)
        changed.append(path)
    manifest_path = output / 'snapshot-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for path in changed:
        manifest['files'][str(path.relative_to(output))] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest['presentation_overrides'] = {'role': 'François dans le rôle du professeur',
                                           'greeting_and_profile': 'M. Amat',
                                           'recorded_evidence_modified': False}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
