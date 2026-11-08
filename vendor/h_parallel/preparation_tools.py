"""Tools through which H prepares, validates and renders one frozen school case."""
import hashlib
import json
import math
import subprocess
from copy import deepcopy
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

from . import engine
from .tool_calls import ToolCallTracker


class PreparedCapsule(BaseModel):
    validated_dossier_id: str
    render_id: str


def inspect_media(folder, output):
    """Probe only a renderer output inside this job, never an agent-supplied path."""
    expected = f'/outputs/{folder.name}/'
    url = output.get('video', '')
    filename = url.removeprefix(expected)
    if not url.startswith(expected) or filename not in ('capsule.mp4', 'capsule-demobro.mp4'):
        raise ValueError('La vidéo ne correspond pas au dossier courant.')
    target = folder / filename
    if not target.is_file() or target.is_symlink() or target.stat().st_size == 0:
        raise ValueError('Le fichier vidéo est absent ou vide.')
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(target)],
        capture_output=True, text=True, timeout=30, check=True)
    metadata = json.loads(probe.stdout)
    streams = metadata.get('streams', [])
    seconds = float(metadata.get('format', {}).get('duration', 0))
    video = any(item.get('codec_type') == 'video' for item in streams)
    audio = any(item.get('codec_type') == 'audio' for item in streams)
    if not video or not audio or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('La capsule doit contenir une vidéo, une piste audio et une durée lisible.')
    embedded = any(item.get('codec_type') == 'subtitle' for item in streams)
    sidecar = folder / 'captions.vtt'
    captions = bool(output.get('captions') == expected + 'captions.vtt'
                    and sidecar.is_file() and not sidecar.is_symlink()
                    and sidecar.read_text().startswith('WEBVTT') and '-->' in sidecar.read_text())
    warnings = []
    if not 60 <= seconds <= 100:
        warnings.append('La durée est hors de la cible de 60 à 100 secondes.')
    if not embedded and not captions:
        warnings.append('Les sous-titres incrustés éventuels restent à vérifier lors de la relecture.')
    return {'valid': True, 'duration_seconds': round(seconds, 2), 'has_video': video,
            'has_audio': audio, 'subtitles_verified': embedded or captions,
            'subtitle_track': embedded, 'webvtt': captions, 'warnings': warnings,
            'video': url, 'requires_teacher_review': True}


class PreparationTools:
    def __init__(self, job, context, audio_path):
        self.job, self.context = job, context
        self.tracker = ToolCallTracker(job, lambda: engine.save(job), engine.LOCK)
        self.memo = {}
        self.validated = {}
        self.rendered = None
        self.inspected = None
        self.read_ids = set()
        self.queries = {}
        self.sources = []
        self.source_urls = {}
        self.purposes = set()
        self.catalog = engine.quote_catalog(context['documents'])
        student = context['student']
        private_terms = {word.casefold() for field in ('name', 'teacher')
                         for word in student.get(field, '').split()
                         if len(word) > 2 and word.casefold() not in ('mme', 'monsieur', 'madame')}
        private_terms.add(student.get('class', '').casefold())

        @self.tracker.tool
        def get_evidence_catalog(document_ids: list[str]) -> str:
            """Lire les extraits exacts des pièces scolaires sélectionnées après navigation. Utiliser leurs identifiants affichés ; une liste vide lit toutes les pièces du dossier figé."""
            known = {item['id'] for item in context['documents']}
            selected = set(document_ids or known)
            if 'teacher-assessment' in known:
                selected.add('teacher-assessment')
            if not selected <= known:
                raise ValueError('Une pièce demandée est absente du dossier figé.')
            self.read_ids.update(selected)
            return json.dumps({'documents': [{'id': item['id'], 'title': item.get('title', item['id'])}
                                            for item in context['documents'] if item['id'] in selected],
                               'teacher_assessment': deepcopy(context.get('teacher_assessment')),
                               'quote_catalog': {key: value for key, value in self.catalog.items()
                                                 if value['source_id'] in selected}}, ensure_ascii=False)

        @self.tracker.tool
        def transcribe_audio() -> str:
            """Transcrire avec Gladia le vocal parental figé de ce dossier, avec repères temporels. Un second appel réutilise la transcription existante."""
            if 'transcription' in self.memo:
                self.tracker.mark_cached()
            else:
                engine.event(job, 'gladia', 'Gladia transcrit le vocal joint au dossier.')
                result = engine.transcribe(audio_path)
                if not result.get('text', '').strip():
                    raise ValueError('Gladia n’a retourné aucun texte exploitable.')
                self.memo['transcription'] = result
                engine.update(job, transcription=result)
                engine.event(job, 'gladia', 'Transcription reçue ; les repères temporels sont accessibles.', job_id=result.get('job_id'))
            return json.dumps(self.memo['transcription'], ensure_ascii=False)

        @self.tracker.tool
        def search_resources(topic: str, purpose: Literal['reference', 'exercise'] = 'reference') -> str:
            """Chercher avec Linkup une référence pédagogique (reference) ou un exercice adapté (exercise). Faire deux requêtes distinctes adaptées à la question. Aucun nom, classe ou établissement dans topic. Le cache est propre à chaque requête et objectif."""
            topic = ' '.join(topic.split())
            if purpose not in ('reference', 'exercise') or not topic or len(topic) > 600:
                raise ValueError('Préciser une requête pédagogique et un objectif reference ou exercise.')
            if any(word and word in topic.casefold() for word in private_terms):
                raise ValueError('Reformuler la recherche sans donnée personnelle.')
            query_key = (purpose, topic.casefold())
            if query_key in self.queries:
                self.tracker.mark_cached()
                return json.dumps(self.queries[query_key], ensure_ascii=False)
            if len(self.queries) >= 4:
                raise ValueError('Quatre recherches ciblées au maximum par préparation.')
            engine.event(job, 'linkup', 'Linkup recherche ' + ('un exercice adapté.' if purpose == 'exercise' else 'une référence pédagogique.'), query=topic, purpose=purpose)
            result = engine.search(topic)
            selected = []
            for item in result.get('sources', []):
                parts = urlsplit(item.get('url', ''))
                canonical_url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ''))
                if canonical_url not in self.source_urls:
                    source = deepcopy(item)
                    source['id'] = f'web-{len(self.sources) + 1}'
                    self.source_urls[canonical_url] = source
                    self.sources.append(source)
                selected.append(deepcopy(self.source_urls[canonical_url]))
            response = {**result, 'query': topic, 'purpose': purpose, 'sources': selected}
            self.queries[query_key] = response
            self.purposes.add(purpose)
            self.memo['search'] = {'provider': 'Linkup', 'query': ' · '.join(item['query'] for item in self.queries.values()),
                                   'queries': deepcopy(list(self.queries.values())), 'sources': deepcopy(self.sources)}
            engine.update(job, search=self.memo['search'])
            engine.event(job, 'linkup', f'{len(selected)} sources conservées pour cette recherche.', purpose=purpose)
            return json.dumps(response, ensure_ascii=False)

        @self.tracker.tool
        def validate_dossier(dossier: engine.AgentDossier) -> str:
            """Vérifier le dossier et ses citations contre les preuves figées. En cas d’erreur, corriger puis rappeler cet outil. Le résultat fournit un identifiant autorisant le rendu ; aucune note n’est modifiée."""
            self.require_evidence()
            checked = engine.checked_answer(dossier, self.sources, context['documents'])
            used = {item['quote_id'] for item in checked['evidence'] if item.get('quote_id')}
            if any(self.catalog[key]['source_id'] not in self.read_ids for key in used):
                raise ValueError('Lire les extraits cités avec get_evidence_catalog avant de les valider.')
            identifier = 'dossier-' + hashlib.sha256(json.dumps(checked, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            if identifier in self.validated:
                self.tracker.mark_cached()
            self.validated[identifier] = checked
            engine.event(job, 'validation', 'Dossier soumis par H : citations et sources vérifiées.')
            return json.dumps({'valid': True, 'validated_dossier_id': identifier,
                               'evidence_count': len(checked['evidence']), 'scenes': len(checked['scenes'])}, ensure_ascii=False)

        @self.tracker.tool
        def render_capsule(validated_dossier_id: str) -> str:
            """Créer la capsule du dossier validé, avec narration et sous-titres. Utiliser exclusivement l’identifiant retourné par validate_dossier. Aucun envoi aux parents. Un rendu réussi est réutilisé sans nouveau coût."""
            checked = self.validated.get(validated_dossier_id)
            if checked is None:
                raise ValueError('Valider ce dossier avant de lancer le rendu.')
            if self.rendered:
                if self.rendered['validated_dossier_id'] != validated_dossier_id:
                    raise ValueError('Une capsule existe déjà pour un autre dossier validé ; ouvrir une nouvelle préparation.')
                self.tracker.mark_cached()
                return json.dumps(self.rendered, ensure_ascii=False)
            dossier = self.decorate(checked)
            engine.update(job, dossier=dossier, status='rendering')
            engine.event(job, 'video', 'H lance la création de la capsule, de la narration et des sous-titres.')
            folder = engine.DATA / job['id']
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'dossier.json').write_text(json.dumps(dossier, ensure_ascii=False, indent=2))
            if job.get('video_provider') == 'demobro':
                from .demobro import render_capsule as render_demobro
                output = render_demobro(dossier, folder, lambda text: engine.event(job, 'demobro', text))
            else:
                output = engine.render(dossier, folder)
            engine.update(job, **output)
            # The renderer's draft is available, but readiness requires H's inspection.
            self.rendered = {'render_id': 'capsule-' + job['id'], 'validated_dossier_id': validated_dossier_id,
                             'video': output['video'], 'duration': output.get('duration'), 'output': output}
            return json.dumps(self.rendered, ensure_ascii=False)

        @self.tracker.tool
        def inspect_capsule(render_id: str) -> str:
            """Contrôler réellement le MP4 produit : vidéo, piste audio, durée et disponibilité des sous-titres. Appeler après render_capsule, avant de terminer. Le professeur garde la validation finale."""
            if not self.rendered or render_id != self.rendered['render_id']:
                raise ValueError('Aucune capsule de ce dossier ne correspond à cet identifiant.')
            inspection = inspect_media(engine.DATA / job['id'], self.rendered['output'])
            self.inspected = render_id
            engine.update(job, capsule_inspection=inspection)
            return json.dumps({'render_id': render_id, **inspection}, ensure_ascii=False)

        self.tools = [get_evidence_catalog, transcribe_audio, search_resources,
                      validate_dossier, render_capsule, inspect_capsule]

    def require_evidence(self):
        if not self.read_ids or 'transcription' not in self.memo or self.purposes != {'reference', 'exercise'}:
            raise ValueError('Lire les preuves, transcrire le vocal et effectuer une recherche reference puis exercise avant de valider.')
        if len({query for _, query in self.queries}) < 2:
            raise ValueError('Les recherches reference et exercise doivent utiliser deux requêtes distinctes.')

    def decorate(self, checked):
        return {**deepcopy(checked), 'sources': deepcopy(self.context['documents']) + deepcopy(self.sources),
                'mode': self.job['mode'], 'transcription': deepcopy(self.memo['transcription']),
                'appointment': deepcopy(self.context['appointment']),
                'display_label': self.context['student']['name'] + ' · ' + self.context['student']['class']}

    def finish(self, answer):
        if isinstance(answer, str):
            answer = json.loads(answer)
        if isinstance(answer, BaseModel):
            answer = answer.model_dump()
        answer = PreparedCapsule.model_validate(answer)
        if not self.rendered or answer.render_id != self.rendered['render_id'] or answer.validated_dossier_id != self.rendered['validated_dossier_id']:
            raise ValueError('H doit retourner les identifiants du dossier validé et de sa capsule réellement créée.')
        if self.inspected != answer.render_id:
            raise ValueError('H doit inspecter la capsule avant de terminer la préparation.')
        checked = engine.checked_answer(self.validated[answer.validated_dossier_id], self.sources, self.context['documents'])
        # Keep a final server-side check even though H already called validation.
        return self.decorate(checked), self.rendered['output']
