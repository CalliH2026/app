import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from . import family

SAVED = family.FAMILY['saved_digest']


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(family, 'STATE', tmp_path / 'family' / 'live.json')
    monkeypatch.delenv(family.LIVE_FLAG, raising=False)


def digest(**changes):
    value = deepcopy(SAVED)
    value.update(changes)
    return value


def test_demo_family_is_an_explicit_two_child_allowlist():
    assert [c['child_id'] for c in family.children()] == ['alex', 'lucas']
    assert 'fictive' in family.FAMILY['notice'] and 'Aucun lien familial' not in family.FAMILY['notice']
    with pytest.raises(ValueError):
        family.child_updates('s05')
    assert {s['child_id'] for s in family.child_updates('lucas')['sources']} == {'lucas'}


def test_saved_digest_is_grounded():
    assert family.validate(SAVED) == []


def test_rejects_cross_child_evidence():
    bad = digest(points=[dict(SAVED['points'][0], child_id='lucas')] + SAVED['points'][1:])
    assert any('autre enfant' in e for e in family.validate(bad))
    bad = digest(points=SAVED['points'] + [{'child_id': 'lucas', 'source_id': 'A-RDV'}])
    assert any('A-RDV d’un autre enfant' in e for e in family.validate(bad))


def test_rejects_free_quote_text_from_the_provider():
    # Root live smoke: H reworded a quote ('réutilis') after validation; quotes are no longer accepted at all.
    for quote in ('Nous reprendrons l’exercice 2 et nous définirons une méthode de rédaction qu’Alex pourra réutilis',
                  'Note de l’exercice : 3/6.'):
        point = dict(SAVED['points'][1], quote=quote)
        assert any('Format invalide' in e for e in family.validate(digest(points=[point] + SAVED['points'][2:])))


def test_saved_points_are_source_ids_and_page_shows_trusted_text():
    assert all(set(p) == {'child_id', 'source_id'} for p in SAVED['points'])
    shown = [p for c in family.page()['children'] for p in c['points']]
    assert [p['source']['text'] for p in shown] == [family.SOURCES[p['source_id']]['text'] for p in SAVED['points']]


def test_rejects_duplicate_and_too_many_points_per_child():
    assert any('Source en double' in e for e in family.validate(digest(points=SAVED['points'] + SAVED['points'][:1])))
    alex = [{'child_id': 'alex', 'source_id': s} for s in ('A-COPIE', 'A-MSG-1', 'A-RDV', 'A-MSG-3')]
    assert any('Plus de 3 points' in e for e in family.validate(digest(points=alex + SAVED['points'][2:])))


def test_rejects_unsupported_free_text_summary():
    value = deepcopy(SAVED)
    value['points'][0]['summary'] = 'Cet élève doit être exclu de la classe.'
    assert family.validate(value)


def test_rejects_arbitrary_payment_suggestion():
    value = deepcopy(SAVED)
    value['actions'] = [{'text': 'Payer immédiatement les frais obligatoires.', 'source_ids': ['L-SORTIE']}]
    assert family.validate(value)
    assert any('Action hors' in e for e in family.validate(digest(action_ids=['ACT-PAYER-FRAIS'])))
    assert not any('pay' in a['text'].lower() for a in family.FAMILY['actions'])


def test_rejects_fabricated_unknowns():
    value = deepcopy(SAVED)
    value['unknowns'] = ['Lucas risque le redoublement.']
    assert family.validate(value)
    assert family.validate(digest(missing_ids=['M-INVENTE']))


def test_rejects_invented_deadline_untrusted_link_and_too_many_actions():
    assert any('Échéance hors' in e for e in family.validate(digest(deadline_ids=['D-PAIEMENT'])))
    point = dict(SAVED['points'][3], url='https://www.example.com/payer')
    assert any('Format invalide' in e for e in family.validate(digest(points=SAVED['points'][:3] + [point])))
    assert any('Plus de 3' in e for e in family.validate(digest(action_ids=list(family.ACTIONS))))
    assert any('en double' in e for e in family.validate(digest(action_ids=['ACT-SORTIE-LUCAS'] * 2)))


def test_reviewed_actions_and_missing_records_are_sourced():
    for action in family.FAMILY['actions']:
        assert action['source_ids'] and all(family.SOURCES[s]['child_id'] == action['child_id'] for s in action['source_ids'])
    for missing in family.FAMILY['missing']:
        assert missing['source_id'] is None or family.SOURCES[missing['source_id']]['child_id'] == missing['child_id']


def test_rejects_unknown_child_and_missing_child_coverage():
    point = dict(SAVED['points'][0], child_id='s05')
    errors = family.validate(digest(points=[point]))
    assert any('hors famille' in e for e in errors) and any('Aucun point' in e for e in errors)


def test_page_is_saved_mode_with_dates_staleness_and_missing_sources():
    body = family.page()
    assert body['mode'] == 'saved' and body['live']['state'] == 'idle' and body['live']['enabled'] is False
    assert [d['date'] for d in body['deadlines']] == sorted(d['date'] for d in body['deadlines'])
    lucas = next(c for c in body['children'] if c['child_id'] == 'lucas')
    assert lucas['missing'] and any(s['stale'] for s in lucas['sources'])
    assert all(p['source']['child_id'] == 'lucas' for p in lucas['points'])
    assert len(body['actions']) <= 3 and all(a['sources'] for a in body['actions'])
    assert [a['text'] for a in body['actions']] == [family.ACTIONS[i]['text'] for i in SAVED['action_ids']]
    alex = next(c for c in body['children'] if c['child_id'] == 'alex')
    assert [m['missing_id'] for m in alex['missing']] == ['M-NOTE-ALEX']
    assert all(p['source']['title'] for c in body['children'] for p in c['points'])


class FakeSession:
    id = 'session-fake'

    def __init__(self, tools, answer, read=('alex', 'lucas')):
        self.tools, self.answer, self.read = {t.__name__: t for t in tools}, answer, read

    def wait_for_completion(self, timeout_seconds, wait_for_seconds):
        self.tools['list_family_children']()
        for child in self.read:
            self.tools['read_child_updates'](child)
        self.check = json.loads(self.tools['validate_family_digest'](json.dumps(self.answer)))
        return SimpleNamespace(answer=self.answer, status='completed')


class FakeClient:
    def __init__(self, answer, read=('alex', 'lucas')):
        self.answer, self.read, self.sessions = answer, read, []

    def start_session(self, agent, messages, tools, answer_schema):
        assert answer_schema is family.FamilyDigest and agent['environments'] == []
        session = FakeSession(tools, self.answer, self.read)
        self.sessions.append(session)
        return session


def test_live_run_calls_tools_validates_and_is_cached(monkeypatch):
    monkeypatch.setenv(family.LIVE_FLAG, '1')
    fake = FakeClient(deepcopy(SAVED))
    state = family.start_live(lambda: fake, background=False)
    assert state['state'] == 'live' and fake.sessions[0].check == {'ok': True, 'errors': []}
    assert [c['name'] for c in state['tool_calls']] == ['list_family_children', 'read_child_updates',
                                                        'read_child_updates', 'validate_family_digest']
    assert family.page()['mode'] == 'live'
    family.start_live(lambda: fake, background=False)
    assert len(fake.sessions) == 1


def test_invalid_live_answer_fails_visibly_and_keeps_saved_digest(monkeypatch):
    monkeypatch.setenv(family.LIVE_FLAG, '1')
    bad = digest(deadline_ids=['D-INVENTEE'])
    state = family.start_live(lambda: FakeClient(bad), background=False)
    assert state['state'] == 'failed' and any('Échéance hors' in e for e in state['errors'])
    assert family.page()['mode'] == 'saved'


def test_live_answer_without_reading_each_child_is_rejected(monkeypatch):
    monkeypatch.setenv(family.LIVE_FLAG, '1')
    state = family.start_live(lambda: FakeClient(deepcopy(SAVED), read=('alex',)), background=False)
    assert state['state'] == 'failed' and 'chaque enfant' in state['errors'][0]


def test_provider_error_is_failed_not_success(monkeypatch):
    monkeypatch.setenv(family.LIVE_FLAG, '1')
    def broken():
        raise RuntimeError('Clé manquante : H_COMPANY_API_KEY')
    state = family.start_live(broken, background=False)
    assert state['state'] == 'failed' and family.page()['mode'] == 'saved'


def test_live_is_disabled_unless_explicitly_enabled():
    called = []
    state = family.start_live(lambda: called.append(1), background=False)
    assert state['state'] == 'disabled' and not called


def test_routes_ignore_query_identity_and_are_read_only():
    from .app import app
    client = TestClient(app)
    body = client.get('/api/family?child_id=s05&family_id=other').json()
    assert [c['child_id'] for c in body['children']] == ['alex', 'lucas'] and body['mode'] == 'saved'
    assert client.post('/api/family/digest').json()['state'] == 'disabled'
    assert client.get('/api/family/sources/L-SORTIE').json()['child_id'] == 'lucas'
    assert client.get('/api/family/sources/s05').status_code == 404
    assert client.put('/api/family').status_code == 405


def test_cli_checks_saved_digest_offline(capsys):
    assert family.main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['state'] == 'saved' and out['errors'] == [] and out['source_key'] == family.source_key()


def test_family_view_is_seen_by_the_fictional_parent_not_the_teacher():
    parent = family.page()['parent']
    assert parent == {'initials': 'GM', 'name': 'Grégory Martin', 'role': 'Parent', 'relation': 'Père d’Alex et de Lucas Martin',
                      'space': 'Espace parent'}
    assert 'Laurent' not in json.dumps(parent, ensure_ascii=False)
    assert 'Grégory Martin et ses deux enfants' in family.FAMILY['notice']
    assert all(s['author'] != parent['name'] for s in family.FAMILY['sources'])


def test_persona_switches_only_on_the_family_page():
    from pathlib import Path
    static = Path(family.__file__).parent / 'static'
    js = (static / 'family.js').read_text(encoding='utf-8')
    assert "next === 'family' && parent" in js and 'role-tag">${esc(p.role)}' in js and 'teacher.who' in js and 'teacher.space' in js
    assert 'window.applyPersona?.(next)' in (static / 'workspace.js').read_text(encoding='utf-8')
    html = (static / 'workspace.html').read_text(encoding='utf-8')
    assert '<span class="avatar lilac">ML</span><span>Mme Laurent <em class="role-tag">Enseignante</em><small>Mathématiques</small></span>' in html
    assert '<small>Espace professeur</small>' in html


def test_brief_comes_first_from_the_current_digest_and_links_only_same_child_sources():
    body = family.page()
    briefs = {b['child_id']: b for b in body['briefs']}
    assert list(briefs) == ['alex', 'lucas']
    for cid, brief in briefs.items():
        linked = [s for p in brief['points'] for s in p['sources']] + (brief['deadline'] or {}).get('sources', []) + \
            (brief['action'] or {}).get('sources', []) + [s for m in brief['missing'] for s in m['sources']]
        assert linked and {s['child_id'] for s in linked} == {cid}
        assert len(brief['points']) <= family.MAX_BRIEF_POINTS
        assert not any(k in json.dumps(brief, ensure_ascii=False) for k in ('moyenne', 'Moyenne', '/20'))
    alex, lucas = briefs['alex'], briefs['lucas']
    for brief in (alex, lucas):
        for point in brief['points']:
            assert point['text'] in point['sources'][0]['text'] and point['text'].endswith(('.', '!', '?', '…'))
            assert len(point['text']) <= family.BRIEF_CHARS
    assert alex['points'][0]['text'].startswith('Calcul exact.')
    assert alex['action']['text'] == family.ACTIONS['ACT-CONCLUSION-ALEX']['text']
    assert alex['deadline']['label'] == family.DEADLINES['D-RDV-ALEX']['label']
    assert [m['topic'] for m in alex['missing']] == ['Note globale du contrôle']
    assert lucas['deadline']['date'] == '2026-11-13' and lucas['action']['text'].startswith('Signer l’autorisation')
    assert lucas['missing'] and lucas['missing'][0]['sources'] == []


def test_brief_follows_the_selection_and_reports_past_or_missing_records(monkeypatch):
    picked = digest(points=[{'child_id': 'alex', 'source_id': 'A-RDV'}, {'child_id': 'lucas', 'source_id': 'L-REUNION'}],
                    deadline_ids=['D-SORTIE-LUCAS'], action_ids=['ACT-METHODE-ALEX'])
    assert family.validate(picked) == []
    briefs = {b['child_id']: b for b in family.view(picked, 'live')['briefs']}
    assert [p['text'] for p in briefs['alex']['points']] == [family.SOURCES['A-RDV']['text']]
    assert briefs['alex']['deadline'] is None and briefs['alex']['action']['text'].startswith('Demander à Alex')
    assert briefs['lucas']['action'] is None and briefs['lucas']['deadline']['label'].startswith('Rendre l’autorisation')
    assert briefs['lucas']['stale'] is True and briefs['alex']['stale'] is False
    monkeypatch.setitem(family.FAMILY, 'as_of', '2026-11-20')
    later = {b['child_id']: b for b in family.view(family.FAMILY['saved_digest'], 'saved')['briefs']}
    assert later['alex']['deadline'] is None and later['lucas']['deadline'] is None


def test_brief_is_extractive_and_follows_changed_source_text(monkeypatch):
    monkeypatch.setitem(family.SOURCES['L-SORTIE'], 'text', 'Sortie reportée au 4 décembre. Nouvelle autorisation à rendre. ' + 'x' * 200)
    lucas = family.view(family.FAMILY['saved_digest'], 'saved')['briefs'][1]
    assert lucas['points'][1]['text'] == 'Sortie reportée au 4 décembre. Nouvelle autorisation à rendre.'
    monkeypatch.setitem(family.SOURCES['L-SORTIE'], 'text', 'Une seule phrase sans ponctuation finale ' + 'y' * 200)
    lucas = family.view(family.FAMILY['saved_digest'], 'saved')['briefs'][1]
    assert lucas['points'][1]['text'] == family.SOURCES['L-SORTIE']['title']
    assert family.excerpt({'title': 'Titre', 'text': 'Phrase un. Phrase deux.'}, limit=12) == 'Phrase un.'


def test_martin_family_names_agree_and_caveats_stay_in_details():
    from pathlib import Path
    body = family.page()
    assert [c['name'] for c in body['children']] == ['Alex Martin', 'Lucas Martin']
    assert [b['name'] for b in body['briefs']] == ['Alex Martin', 'Lucas Martin']
    assert 'fictive' not in body['label'].lower() and 'Bernard' not in json.dumps(body, ensure_ascii=False)
    lucas = next(c for c in body['children'] if c['child_id'] == 'lucas')
    assert lucas['avatar'] == {'native_id': 's01'} and {s['child_name'] for s in lucas['sources']} == {'Lucas Martin'}
    assert {d['child_name'] for d in body['deadlines'] if d['child_id'] == 'lucas'} == {'Lucas Martin'}
    js = (Path(family.__file__).parent / 'static' / 'family.js').read_text(encoding='utf-8')
    banner = js[js.index('family-banner'):js.index('family-briefs')]
    assert 'data.label' not in js and 'data.notice' not in banner and 'MODE[' not in banner
    assert 'esc(data.notice)' in js[js.index('calli-tech'):]
    brief_js = js[js.index('const briefs ='):js.index('const calls =')]
    assert 'Non fourni' not in brief_js and 'b.missing' not in brief_js
    assert 'family-missing' in js[js.index('const cards ='):js.index('const deadlines =')]
    assert "const current = box.isConnected && document.querySelector('.nav.active[data-page=\"family\"]');" in js


def test_open_family_starts_once_and_reuses_verified_summary(monkeypatch):
    monkeypatch.setenv(family.LIVE_FLAG, '1')
    fake = FakeClient(deepcopy(SAVED))
    assert family.start_live(lambda: fake, background=False, automatic=True)['state'] == 'live'
    assert family.start_live(lambda: fake, background=False, automatic=True)['state'] == 'live'
    assert len(fake.sessions) == 1


def test_open_family_does_not_retry_a_failed_provider_call(monkeypatch):
    monkeypatch.setenv(family.LIVE_FLAG, '1')
    calls = []
    def unavailable():
        calls.append(True)
        raise RuntimeError('Unavailable')
    family.start_live(unavailable, background=False, automatic=True)
    family.start_live(unavailable, background=False, automatic=True)
    assert len(calls) == 1
    family.start_live(unavailable, background=False)
    assert len(calls) == 2


def test_open_family_route_respects_opt_in():
    from .app import app
    client = TestClient(app)
    response = client.post('/api/family/open')
    assert response.status_code == 200 and response.json()['state'] == 'disabled'


def test_brief_assessment_is_exact_and_child_scoped():
    alex, lucas = family.page()['briefs']
    assert alex['assessments'][0]['text'] == 'Note de l’exercice : 3/6.'
    assert alex['assessments'][0]['sources'][0]['source_id'] == 'A-COPIE'
    assert lucas['assessments'] == []
    picked = digest(points=[{'child_id': 'alex', 'source_id': 'A-RDV'}, {'child_id': 'lucas', 'source_id': 'L-DEVOIR'}])
    assert family.view(picked, 'live')['briefs'][0]['assessments'] == []


def test_brief_assessment_tracks_source_without_inventing_a_grade(monkeypatch):
    source = family.SOURCES['A-COPIE']
    monkeypatch.setitem(source, 'text', 'Réponse exacte. Note de l’exercice : 4,5/6. À revoir demain.')
    assert family.page()['briefs'][0]['assessments'][0]['text'] == 'Note de l’exercice : 4,5/6.'
    for unsupported in ('Aucune note fournie.', 'La moyenne pourrait être 12/20.', 'Note de l’exercice : 7/6.', 'Note de l’exercice : 0/0.'):
        monkeypatch.setitem(source, 'text', unsupported)
        assert family.page()['briefs'][0]['assessments'] == []
