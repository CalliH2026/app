"""Origin-bound PRONOTE Web views and DOM reads for a dedicated browser.

PRONOTE's views share one SPA URL.  Internal tab numbers found in its public
JavaScript are research hints, not routes that this module invokes.  A view can
only be navigated after Codex has observed and recorded its actual DOM controls.
The module never starts a browser, logs in, executes app internals or uses the
desktop.  Its caller owns the dedicated browser and its lifetime.
"""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .browser_text import READ_VISIBLE

DEMO_URL = 'https://demo.index-education.net/pronote/professeur.html?fd=1'
DEMO_VERSION = '2026.2.8'
SOURCE_SHA256 = 'e642125943debfb154574db6350382674d53ea1e9566c1129214ec91c48cc342'
OBSERVATION_SESSION = 'b65a3ad5-0b49-4b4a-89d5-cb8f6804076c'
_READ_MAIN = READ_VISIBLE.replace(
    '''if (document.querySelector('input[type="password"]'))''',
    '''// PRONOTE retains its hidden login form after authentication.
if ([...document.querySelectorAll('input[type="password"]')].some(input => {
    const style = getComputedStyle(input);
    return input.getClientRects().length && style.display !== 'none'
        && style.visibility !== 'hidden';
}))''').replace(
    'const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);',
    '''const main = document.querySelector('main[role="main"]');
if (!main || !main.getClientRects().length) return {login:false,text:'',scope:'main_missing'};
const walker=document.createTreeWalker(main,NodeFilter.SHOW_TEXT);''')
READ_VIEW = "const result = (() => {" + _READ_MAIN + r'''})();
if (result.login) return result;
result.scope = result.scope || 'main[role="main"]';
const breadcrumb = document.querySelector('#breadcrumbBandeau');
result.breadcrumb = breadcrumb && breadcrumb.getClientRects().length
    ? breadcrumb.innerText.trim() : '';
return result;
'''


class RouteError(ValueError):
    """A route cannot be safely resolved or its view is not the expected one."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ControlStep(StrictModel):
    selector: str = Field(min_length=1, max_length=600)
    label: str = Field(min_length=1, max_length=160)
    role: Literal['button', 'tab', 'menuitem', 'link', 'combobox', 'option', 'generic']
    purpose: Literal['navigation', 'read_selection'] = 'navigation'


class Verification(StrictModel):
    observer: Literal['codex_harness']
    recorded_at: datetime
    source_url: str
    app_version: str = Field(min_length=1, max_length=40)
    snapshot_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    # This is a local evidence identifier, never a credential or remote script.
    evidence_id: str = Field(min_length=1, max_length=300)


class SelectionCheck(StrictModel):
    selector: str = Field(min_length=1, max_length=600)
    text: str = Field(min_length=1, max_length=160)


class Route(StrictModel):
    route_id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,79}$')
    title: str = Field(min_length=1, max_length=160)
    expected_heading: str = Field(default='', max_length=160)
    expected_breadcrumb: str = Field(default='', max_length=160)
    expected_selections: list[SelectionCheck] = Field(default_factory=list, max_length=8)
    status: Literal['static_candidate', 'observed', 'verified']
    internal_tab_hint: int | None = None
    steps: list[ControlStep] = Field(default_factory=list, max_length=12)
    verification: Verification | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def require_verification(self):
        if self.status == 'verified' and (not self.verification or not self.steps):
            raise ValueError('Une route vérifiée doit inclure ses contrôles DOM et sa preuve Codex.')
        if self.status != 'verified' and self.steps:
            raise ValueError('Un contrôle non vérifié ne peut pas devenir une route exécutable.')
        return self


class Catalog(StrictModel):
    schema_version: Literal[1] = 1
    source_url: str
    app_version: str = ''
    source_kind: Literal['official_demo', 'school']
    routes: dict[str, Route] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def bind_routes(self):
        _source(self.source_url, allow_demo_query=self.source_kind == 'official_demo')
        if self.source_kind == 'official_demo' and _location(self.source_url) != _location(DEMO_URL):
            raise ValueError('La source de démonstration officielle ne peut pas désigner un autre espace.')
        for key, route in self.routes.items():
            if key != route.route_id:
                raise ValueError('La clé et l’identifiant de route diffèrent.')
            if route.verification:
                _source(route.verification.source_url, allow_demo_query=self.source_kind == 'official_demo')
                if _location(route.verification.source_url) != _location(self.source_url):
                    raise ValueError('La preuve DOM appartient à une autre source PRONOTE.')
                if not self.app_version or route.verification.app_version != self.app_version:
                    raise ValueError('La preuve DOM appartient à une autre version PRONOTE.')
        return self


def _source(url: str, *, allow_demo_query: bool = False):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or (parsed.query and not (allow_demo_query and url == DEMO_URL))):
        raise RouteError('Source HTTPS sans identifiant, jeton ou fragment requise.')
    # Accessing .port validates malformed ports as well.
    parsed.port
    return parsed


def _location(url: str):
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        raise RouteError('Aucun identifiant ne doit figurer dans une URL PRONOTE.')
    return (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else None), parsed.path)


def _public_url(url: str):
    parsed = urlsplit(url)
    return f'{parsed.scheme}://{parsed.netloc}{parsed.path}'


def _normal(value: str):
    value = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))
    return ' '.join(value.casefold().split())


def validate_catalog(catalog: Catalog | dict) -> Catalog:
    return catalog if isinstance(catalog, Catalog) else Catalog.model_validate(catalog)


def official_catalog() -> dict:
    """Seed only what the recorded official demo and public bundle establish.

    Observed views may be read when already open.  No navigation controls were
    captured by the older H screenshot recording, so none are executable yet.
    """
    definitions = [
        ('home', "Page d'accueil", 7, 'observed'),
        ('notes', 'Saisie des notes', 23, 'observed'),
        ('cahier', 'Saisie du cahier de textes', 28, 'observed'),
        ('agenda', 'Agenda', 9, 'static_candidate'),
        ('cahier_content', 'Contenu du cahier de textes', 47, 'static_candidate'),
        ('homework', 'Travail à faire', 48, 'static_candidate'),
        ('resources', 'Ressources pédagogiques', 99, 'static_candidate'),
        ('messages', 'Messagerie', 131, 'static_candidate'),
        ('assignments', 'Liste des devoirs', 194, 'static_candidate'),
        ('parent_documents', 'Documents parents', 271, 'static_candidate'),
        ('submitted_work', 'Récapitulatif des devoirs rendus', 272, 'static_candidate'),
    ]
    routes = {}
    for route_id, title, tab, status in definitions:
        limitations = []
        if status == 'static_candidate':
            limitations.append('Intitulé indicatif du code public ; vue et contrôle DOM à vérifier.')
        if route_id == 'notes':
            limitations.append('Aucune note individuelle ni pièce jointe observée dans la capture initiale.')
        if route_id == 'cahier':
            limitations.append('Aucun contenu de cours ni barème ouvert dans la capture initiale.')
        routes[route_id] = Route(route_id=route_id, title=title, expected_heading=title if status == 'observed' else '',
                                 internal_tab_hint=tab, status=status, limitations=limitations)
    return Catalog(source_url=DEMO_URL, app_version=DEMO_VERSION, source_kind='official_demo', routes=routes,
                   evidence={'public_bundle': 'mvp/pronote-reference/professeur.js',
                             'public_bundle_sha256': SOURCE_SHA256,
                             'observed_session_id': OBSERVATION_SESSION,
                             'observed_manifest': 'mvp/data/recordings/legacy-web/manifest.json'}).model_dump(mode='json')


def catalog_for_url(url: str, *, app_version: str = '') -> dict:
    """A real school's source never inherits demonstration selectors or routes."""
    if url in (DEMO_URL, _public_url(DEMO_URL)):
        return official_catalog()
    _source(url)
    return Catalog(source_url=url, app_version=app_version, source_kind='school').model_dump(mode='json')


def verified_route(catalog: Catalog | dict, route: Route | dict) -> dict:
    """Return a new catalog with a route grounded by a Codex DOM observation."""
    current = validate_catalog(catalog)
    candidate = route if isinstance(route, Route) else Route.model_validate(route)
    if candidate.status != 'verified':
        raise RouteError('La route doit porter sa preuve de vérification Codex.')
    updated = current.model_dump(mode='json')
    updated['routes'][candidate.route_id] = candidate.model_dump(mode='json')
    return validate_catalog(updated).model_dump(mode='json')


def _check_location(driver, catalog: Catalog):
    if _location(driver.current_url) != _location(catalog.source_url):
        raise RouteError('Le navigateur dédié n’affiche pas l’espace PRONOTE configuré. Aucune lecture effectuée.')


def _read(driver, catalog: Catalog):
    _check_location(driver, catalog)
    result = driver.execute_script(READ_VIEW)
    if not isinstance(result, dict) or result.get('login'):
        raise RouteError('Terminer la connexion directement dans le navigateur PRONOTE dédié.')
    text = str(result.get('text', '')).strip()
    if not text:
        raise RouteError('Aucun texte visible lisible ; le contenu peut être dessiné ou dans une iframe.')
    title = str(driver.title)
    if catalog.app_version and not re.search(r'PRONOTE\s+' + re.escape(catalog.app_version) + r'(?![\d.])', title):
        raise RouteError('La version PRONOTE a changé. Vérifier à nouveau les routes avec Codex.')
    # A redirect during extraction must not yield a falsely attributed snapshot.
    _check_location(driver, catalog)
    return title, text, str(result.get('breadcrumb', '')).strip()


def read_route(driver, route_id: str, catalog: Catalog | dict) -> dict:
    """Read the expected view; a current-view read never navigates or clicks."""
    catalog = validate_catalog(catalog)
    route = catalog.routes.get(route_id)
    if route is None or route.status == 'static_candidate':
        raise RouteError('Cette vue PRONOTE n’a pas encore été observée.')
    title, text, breadcrumb = _read(driver, catalog)
    if route.expected_breadcrumb and _normal(route.expected_breadcrumb) != _normal(breadcrumb):
        raise RouteError('Le fil d’Ariane PRONOTE ne correspond pas à la vue attendue.')
    if not route.expected_breadcrumb and _normal(route.title) not in _normal(title):
        raise RouteError('La vue affichée ne correspond pas à la route attendue.')
    if route.expected_heading and _normal(route.expected_heading) not in _normal(text):
        raise RouteError('Le titre de la vue ne suffit pas : son contenu attendu est absent.')
    selections = []
    for check in route.expected_selections:
        elements = [element for element in driver.find_elements('css selector', check.selector)
                    if element.is_displayed() and element.is_enabled()]
        if len(elements) != 1:
            raise RouteError('Sélection de lecture absente ou ambiguë.')
        element = elements[0]
        # Read the displayed label of the already selected control, never a
        # text-input/select value, hidden option, or editable content.
        if (str(element.tag_name).lower() not in ('div', 'span')
                or element.get_attribute('role') != 'combobox'
                or element.get_attribute('contenteditable') == 'true'):
            raise RouteError('Le contrôle de sélection n’est plus un libellé de lecture vérifié.')
        selected = element.text.strip()
        if _normal(selected) != _normal(check.text):
            raise RouteError('La classe ou l’élève affiché ne correspond pas à la sélection attendue.')
        selections.append({'selector': check.selector, 'label': element.get_attribute('aria-label') or '',
                           'text': selected})
    _check_location(driver, catalog)
    return {'state': 'observed', 'source_kind': 'pronote_web', 'method': 'visible_dom',
            'route_id': route_id, 'title': title, 'breadcrumb': breadcrumb,
            'selections': selections,
            'read_selector': 'main[role="main"]',
            'source_url': _public_url(driver.current_url),
            'app_version': catalog.app_version, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'visible_text': text, 'content_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'route_verification': route.verification.model_dump(mode='json') if route.verification else None,
            'limitations': ['Texte visible de la zone principale uniquement ; pièces jointes et iframes non lues.',
                            'Aucune note, copie ou barème déduit à partir du seul nom de la vue.'] + route.limitations}


_WRITE_ACTION = re.compile(r'^(enregistrer|sauvegarder|supprimer|envoyer|publier|valider|confirmer|modifier|ajouter|creer|deposer|save|delete|send|submit|publish|confirm|accept)(\b|\s)', re.I)


def _click_verified(driver, step: ControlStep, catalog: Catalog, deadline: float):
    if _WRITE_ACTION.match(_normal(step.label)):
        raise RouteError('Cette action modifie les données et ne fait pas partie de la lecture PRONOTE.')
    _check_location(driver, catalog)
    matches = []
    while True:
        _check_location(driver, catalog)
        matches = [element for element in driver.find_elements('css selector', step.selector)
                   if element.is_displayed() and element.is_enabled()]
        if matches or time.monotonic() >= deadline:
            break
        time.sleep(min(.08, max(0, deadline - time.monotonic())))
    if len(matches) != 1:
        raise RouteError('Contrôle absent ou ambigu. Vérifier à nouveau la route avec Codex.')
    element = matches[0]
    tag = str(element.tag_name).lower()
    role = element.get_attribute('role') or {'button': 'button', 'a': 'link', 'select': 'combobox', 'option': 'option',
                                           'div': 'generic', 'span': 'generic'}.get(tag, '')
    # PRONOTE's desktop home icon keeps its literal label in a hidden child
    # span. The *control* must still be visible; only its observed label may
    # use textContent as the final fallback.
    label = (getattr(element, 'accessible_name', '') or element.get_attribute('aria-label')
             or element.text or element.get_attribute('title') or element.get_attribute('textContent'))
    if role != step.role or _normal(str(label)) != _normal(step.label):
        raise RouteError('Le contrôle DOM ne correspond plus à la preuve Codex.')
    if role == 'generic' and step.purpose != 'navigation':
        raise RouteError('Un contrôle générique ne peut servir qu’à la navigation vérifiée.')
    if (tag in ('input', 'textarea', 'form') or element.get_attribute('contenteditable') == 'true'
            or element.get_attribute('type') == 'submit' or element.get_attribute('download') is not None):
        raise RouteError('Contrôle de saisie, de soumission ou de téléchargement refusé.')
    href = element.get_attribute('href')
    if href and _location(href) != _location(catalog.source_url):
        raise RouteError('La route quitte l’espace PRONOTE configuré.')
    element.click()
    _check_location(driver, catalog)


def navigate_route(driver, route_id: str, catalog: Catalog | dict, *, timeout: float = 10) -> dict:
    """Replay only verified, unambiguous read/navigation controls, then read.

    The bounded wait handles PRONOTE's asynchronous menus and breadcrumb. If a
    control or postcondition changes this function fails closed; it never
    improvises clicks or invokes PRONOTE's private JavaScript methods.
    """
    catalog = validate_catalog(catalog)
    route = catalog.routes.get(route_id)
    if route is None or route.status != 'verified':
        raise RouteError('Route non vérifiée : relever ses contrôles avec le harnais Codex.')
    _read(driver, catalog)  # Auth and version guard before the first action.
    deadline = time.monotonic() + max(0, min(timeout, 30))
    for step in route.steps:
        _click_verified(driver, step, catalog, deadline)
    while True:
        try:
            return read_route(driver, route_id, catalog)
        except RouteError:
            _check_location(driver, catalog)
            if time.monotonic() >= deadline:
                raise
            time.sleep(min(.08, max(0, deadline - time.monotonic())))
