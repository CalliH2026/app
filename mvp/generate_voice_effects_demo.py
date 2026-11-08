"""Render a private DemoBro film through real, recorded H custom-tool calls.

Without flags, prepare the connected render and keep its isolated snapshot
online until ``launch-reviewed`` appears in the output directory. This marker
coordinates the caller's technical review; it is not a second user approval.
``--prepare-only`` is offline. ``--follow`` never submits another render.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

from hai_agents import Client
from pydantic import BaseModel
import yaml

from .demobro import DemoBro
from .generate_workspace_demo import (ROOT, freeze_snapshot, snapshot_server,
                                     public_tunnel, follow, log)
from .tool_calls import ToolCallTracker, summarize_tool_calls

PRESENTER = '646507f4-0c10-48d2-b747-b8f4ce84b63a'
NAME = 'Parallèle — Professeur François — voix et effets'


def write_json(path, value):
    """An acknowledged remote action must never have a half-written ledger."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def render_identifier(result):
    if not isinstance(result, dict):
        return None
    return result.get('render_id') or result.get('id') or (result.get('render') or {}).get('id')


def without_debug(value):
    """The H brief needs the estimate, never the account/debug envelope."""
    if isinstance(value, dict):
        return {key: without_debug(item) for key, item in value.items()
                if key not in ('mcp_debug', 'credentials', 'headers', 'authorization')}
    if isinstance(value, list):
        return [without_debug(item) for item in value]
    return value


def require_presenter(presenters, presenter_id=PRESENTER):
    if isinstance(presenters, dict):
        presenters = presenters.get('presenters') or presenters.get('items') or []
    presenter = next((item for item in presenters if item.get('id') == presenter_id), None)
    if not presenter or not all(presenter.get(field) for field in ('is_active', 'consented', 'is_owner')):
        raise ValueError('Le présentateur doit être actif, consenti et appartenir au compte.')
    return presenter


class DemoRenderReceipt(BaseModel):
    render_id: str


class RenderTools:
    """The model may submit this prepared film once, never arbitrary YAML."""

    def __init__(self, output, client, raw_yaml, project_id, brief):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.client = client
        self.raw_yaml = raw_yaml
        self.project_id = project_id
        self.prepared_id = 'demo-' + hashlib.sha256(raw_yaml.encode()).hexdigest()[:20]
        self.brief = without_debug(brief)
        self.read = False
        self.ledger = self.output / 'submission.json'
        self.lock = threading.RLock()
        state_file = self.output / 'h-tool-state.json'
        self.state = json.loads(state_file.read_text()) if state_file.exists() else {'tool_calls': []}
        self.state.update(prepared_demo_id=self.prepared_id, source='H custom tools → DemoBro MCP')
        self.tracker = ToolCallTracker(self.state, lambda: write_json(state_file, self.state), self.lock)

        @self.tracker.tool
        def read_demo_brief() -> str:
            """Lire le brief vérifié de cette vidéo : voix et avatar consentis, effets, sources fictives, coût et durée estimés. Les données sont figées et ne peuvent pas être remplacées."""
            self.read = True
            return json.dumps({'prepared_demo_id': self.prepared_id, 'brief': self.brief}, ensure_ascii=False)

        @self.tracker.tool
        def render_demobro_demo(prepared_demo_id: str) -> str:
            """Lancer une seule fois la vidéo DemoBro préparée et vérifiée. Utiliser exclusivement l’identifiant de read_demo_brief. Réutiliser un identifiant de rendu déjà confirmé, sans nouveau débit."""
            if not self.read:
                raise ValueError('Lire le brief de la vidéo avant son lancement.')
            if prepared_demo_id != self.prepared_id:
                raise ValueError('Cet identifiant ne désigne pas la vidéo vérifiée.')
            with self.lock:
                if self.ledger.exists():
                    existing = json.loads(self.ledger.read_text())
                    if existing.get('prepared_demo_id') != self.prepared_id:
                        raise ValueError('Ce dossier de sortie appartient à une autre vidéo.')
                    if not existing.get('render_id'):
                        raise RuntimeError('Une soumission existe sans identifiant confirmé ; vérifier le compte, ne pas renvoyer.')
                    self.tracker.mark_cached()
                    return json.dumps({'render_id': existing['render_id'], 'reused': True})
                write_json(self.ledger, {'state': 'submitting', 'prepared_demo_id': self.prepared_id,
                                         'project_id': self.project_id, 'submitted_at': time.time()})
                result = self.client.call('render_demo_from_yaml', {
                    'name': NAME, 'project_id': self.project_id, 'yaml_config': self.raw_yaml,
                    'description': 'Données fictives ; relecture d’une exécution H enregistrée. Voix et présentateur du propriétaire du compte.',
                    'interactive': True, 'draft': False})
                render_id = render_identifier(result)
                write_json(self.ledger, {'state': 'submitted' if render_id else 'unconfirmed',
                                         'prepared_demo_id': self.prepared_id, 'project_id': self.project_id,
                                         'render_id': render_id, 'response': result})
                if not render_id:
                    raise RuntimeError('DemoBro n’a pas confirmé de render_id ; aucun nouvel envoi automatique.')
                return json.dumps({'render_id': render_id, 'prepared_demo_id': self.prepared_id}, ensure_ascii=False)

        self.tools = [read_demo_brief, render_demobro_demo]

    def validate_receipt(self, answer):
        if isinstance(answer, str):
            answer = json.loads(answer)
        if isinstance(answer, BaseModel):
            answer = answer.model_dump()
        receipt = DemoRenderReceipt.model_validate(answer)
        ledger = json.loads(self.ledger.read_text()) if self.ledger.exists() else {}
        if not self.read or not ledger.get('render_id') or receipt.render_id != ledger['render_id']:
            raise ValueError('La réponse H doit correspondre au rendu réellement confirmé par DemoBro.')
        return receipt.render_id


def execute_h_render(tools, client_factory=None):
    from .integrations import key, CONFIG
    from .engine import finish_session_safely
    client = client_factory() if client_factory else Client(
        api_key=key('H_COMPANY_API_KEY'), base_url=CONFIG.get('H_COMPANY_BASE_URL') or None)
    session = None
    try:
        session = client.start_session(
            agent={'name': 'demobro-voice-effects-render',
                   'description': 'Déclenche la vidéo consentie par les outils métier DemoBro.', 'environments': []},
            messages='Le propriétaire a demandé de créer cette vidéo DemoBro avec sa voix et ses effets. Appelle read_demo_brief, puis render_demobro_demo avec le prepared_demo_id reçu, exactement une fois. Ne demande aucune confirmation supplémentaire. Ne modifie aucun argument, voix, avatar, narration, source ni coût ; le brief est déjà vérifié. Une soumission sans identifiant confirmé ne doit jamais être répétée. Retourne uniquement le render_id réellement reçu au schéma demandé.',
            tools=tools.tools, answer_schema=DemoRenderReceipt)
        tools.state['session_id'] = session.id
        tools.tracker.set_session_id(session.id)
        log('Session H créée : ' + session.id)
        result = session.wait_for_completion(timeout_seconds=300, wait_for_seconds=10)
        if str(result.status) not in ('completed', 'idle') or result.answer is None:
            raise RuntimeError(f'H n’a pas confirmé le lancement : {result.status}.')
        render_id = tools.validate_receipt(result.answer)
        log('H a appelé DemoBro : ' + render_id)
        return render_id
    except Exception:
        if session:
            try:
                session.cancel()
            except Exception:
                pass
        raise
    finally:
        cleanup = finish_session_safely(session)
        if cleanup:
            tools.state['session_cleanup'] = cleanup
            write_json(tools.output / 'h-tool-state.json', tools.state)


def verify_video(output, render_id):
    output = Path(output)
    metadata = json.loads((output / 'ffprobe.json').read_text())
    streams = metadata.get('streams', [])
    if not any(stream.get('codec_type') == 'video' for stream in streams) or not any(stream.get('codec_type') == 'audio' for stream in streams):
        raise RuntimeError('Le résultat doit contenir une vidéo et une piste audio.')
    seconds = float(metadata.get('format', {}).get('duration', 0))
    if seconds <= 0:
        raise RuntimeError('La vidéo n’a pas de durée lisible.')
    original = output / 'new-pronote-demo.mp4'
    target = output / 'Parallele-Professeur-Francois-Voix-Effets.mp4'
    shutil.copy2(original, target)
    state_path = output / 'h-tool-state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    verification = {'render_id': render_id, 'duration_seconds': seconds,
                    'video_file': str(target.resolve()), 'video_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                    'has_video': True, 'has_audio': True, 'h_function_calls': summarize_tool_calls(state),
                    'requires_teacher_review': True}
    write_json(output / 'verification.json', verification)
    log(json.dumps({'completed': True, 'duration_seconds': round(seconds, 2), 'file': str(target)}, ensure_ascii=False))


def prepare_remote(client, output, raw_yaml):
    presenter = require_presenter(client.call('list_presenters', {}))
    write_json(output / 'presenter.json', presenter)
    validation = client.call('validate_demo_config', {'yaml_config': raw_yaml, 'interactive': True})
    write_json(output / 'validation.json', validation)
    if not validation.get('valid'):
        raise RuntimeError('La configuration DemoBro n’est pas valide ; aucun rendu lancé.')
    # The browser-only probe does not load renderer-only media/effect plugins.
    # Keep the full YAML intact for validation, pricing and rendering. Probe
    # only its browser actions; the caller checks effect selectors separately.
    browser_config = yaml.safe_load(raw_yaml)
    omissions = []
    for scenario_index, scenario in enumerate(browser_config.get('scenarios', [])):
        if 'avatar' in scenario:
            scenario.pop('avatar')
            omissions.append({'path': f'scenarios[{scenario_index}].avatar',
                              'reason': 'Renderer media block unsupported by the browser-only probe.'})
        for step_index, step in enumerate(scenario.get('steps', [])):
            if 'effects' in step:
                effects = step.pop('effects')
                omissions.append({'path': f'scenarios[{scenario_index}].steps[{step_index}].effects',
                                  'reason': 'Renderer effects plugins unavailable to the browser-only probe.',
                                  'effects': [{'type': effect.get('type'), 'preset': effect.get('preset'),
                                               'selector': effect.get('selector')}
                                              for effect in effects if isinstance(effect, dict)]
                                  if isinstance(effects, list) else [{'type': type(effects).__name__}]})
    write_json(output / 'probe-omissions.json', {
        'browser_only_probe': True, 'render_yaml_unchanged': True, 'omissions': omissions,
        'separate_check_required': 'Verify every effect selector in a real local browser before launch.'})
    probe = client.call('probe_demo_config', {'yaml_config': yaml.safe_dump(browser_config, allow_unicode=True, sort_keys=False)})
    write_json(output / 'probe.json', probe)
    if probe.get('resolved') is False or probe.get('unresolved', 0) or probe.get('ambiguous', 0):
        raise RuntimeError('Les cibles de capture ne sont pas vérifiées ; aucun rendu lancé.')
    cost = client.call('estimate_demo_cost', {'yaml_config': raw_yaml})
    duration = client.call('estimate_demo_duration', {'yaml_config': raw_yaml})
    write_json(output / 'estimate-cost.json', cost)
    write_json(output / 'estimate-duration.json', duration)
    project = client.call('create_project', {'name': NAME, 'yaml_config': raw_yaml,
                                          'description': 'MVP fictif avec preuve des vrais function calls ; voix et avatar du propriétaire.'})
    write_json(output / 'project.json', project)
    project_id = project.get('id') or project.get('project_id')
    if not project_id:
        raise RuntimeError('Le projet DemoBro n’a pas été confirmé.')
    coverage = client.call('get_project_brief', {'project_id': project_id})
    write_json(output / 'brief.json', coverage)
    blocked = ('Crédits insuffisants.' if cost.get('affordable') is False else
               'Estimation de rendu longue : accord explicite requis pour confirm_long_render.' if duration.get('long_render') else None)
    ready = {'name': NAME, 'project_id': project_id, 'presenter': {'id': presenter['id'], 'name': presenter['name']},
             'cost': cost, 'duration': duration, 'brief': coverage, 'blocked': blocked,
             'launch_marker': str(output / 'launch-reviewed')}
    write_json(output / 'ready.json', ready)
    log('PRÊT : estimations et brief enregistrés dans ' + str(output / 'ready.json'))
    return ready


def main(args):
    # Imported lazily so unit tests of the transaction guard do not need the
    # separately authored visual configuration module.
    from .voice_effects_config import config, personalize_snapshot
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.follow:
        ledger = json.loads((output / 'submission.json').read_text())
        if not ledger.get('render_id'):
            raise RuntimeError('Soumission non confirmée : ne pas recommencer le rendu.')
        client = DemoBro()
        try:
            follow(client, ledger['render_id'], output, max_polls=720)
            verify_video(output, ledger['render_id'])
        finally:
            client.close()
        return
    if (output / 'submission.json').exists():
        raise RuntimeError('Une soumission existe déjà. Utiliser --follow, jamais renvoyer le rendu.')
    freeze_snapshot(args.job_id, output)
    personalize_snapshot(output)
    (output / 'demo-preview.yaml').write_text(yaml.safe_dump(config('http://127.0.0.1:8766', PRESENTER), allow_unicode=True, sort_keys=False))
    if args.prepare_only:
        log('Snapshot et configuration préparés localement, aucun appel externe.')
        return
    with snapshot_server(output) as local, public_tunnel(local, output) as base:
        raw = yaml.safe_dump(config(base, PRESENTER), allow_unicode=True, sort_keys=False)
        (output / 'demo.yaml').write_text(raw)
        client = DemoBro()
        try:
            ready = prepare_remote(client, output, raw)
            if ready['blocked']:
                raise RuntimeError(ready['blocked'])
            if not args.launch:
                deadline = time.monotonic() + 1200
                while not (output / 'launch-reviewed').exists():
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Revue technique expirée ; aucun rendu lancé.')
                    time.sleep(1)
            tools = RenderTools(output, client, raw, ready['project_id'], {
                'name': NAME, 'source_job_id': args.job_id, 'presenter': ready['presenter'],
                'scope': 'Dossier fictif, relecture de l’exécution H enregistrée ; voix et avatar consentis du propriétaire.',
                'cost': ready['cost'], 'duration': ready['duration']})
            render_id = execute_h_render(tools)
            follow(client, render_id, output, max_polls=720)
            verify_video(output, render_id)
        finally:
            client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'professor-voice-effects')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--follow', action='store_true')
    main(parser.parse_args())
