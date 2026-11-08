"""Outing tests use provider doubles; no credits or external network required."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json
import threading
import time

import httpx
import pytest

from . import outings


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(outings, 'FOLDER', tmp_path / 'outings')
    monkeypatch.setattr(outings, 'JOBS', {})
    from . import workspace
    monkeypatch.setattr(workspace, 'get_workspace', lambda: {'agenda': []})
    return outings.options()['defaults']


def visit():
    return {'opening_time': '09:30', 'closing_time': '18:00', 'closed_on_date': False,
            'student_unit_price': '0.00', 'adult_unit_price': '0.00', 'group_fee': '0.00',
            'max_group_size': 30, 'conditions': ['Réservation obligatoire'], 'sources': []}


def test_decimal_budget_and_unknowns_are_not_free(store):
    value = {**store, 'transport_total': '100.01', 'subsidy': '0.01'}
    roster = {'student_count': 28}
    budget = outings.calculate_budget(value, roster, visit())
    assert budget['total'] == '100.01'
    assert budget['family_total'] == '100.00'
    assert budget['per_student'] == '3.58'
    assert Decimal(budget['per_student']) * 28 >= Decimal(budget['family_total'])
    unknown = visit()
    unknown['group_fee'] = None
    budget = outings.calculate_budget(value, roster, unknown)
    assert budget['complete'] is False
    assert budget['total'] is None
    assert budget['per_student'] is None
    assert budget['lines'][2]['total'] is None
    pending_roster = outings.calculate_budget(value, None, visit())
    assert pending_roster['lines'][0]['quantity'] is None
    assert pending_roster['total'] is None


def test_provider_work_waits_for_holo4_tool_requests(store, monkeypatch):
    providers = []
    monkeypatch.setattr(outings, '_search_visit', lambda _: providers.append('visit'))
    monkeypatch.setattr(outings, '_route_and_calendar', lambda *_: providers.append('route'))
    monkeypatch.setattr(outings, '_read_roster', lambda _: providers.append('roster'))
    entered = threading.Event()
    release = threading.Event()
    def no_tools_called(job):
        assert not providers
        assert all(task['status'] == 'pending' for task in job['tasks'] if task['id'] != 'dossier')
        entered.set()
        assert release.wait(3)
        raise RuntimeError('Le modèle n’a demandé aucun outil.')
    monkeypatch.setattr(outings, '_fill_with_h', no_tools_called)
    job = outings.start({**store, 'objective': 'Étudier la perspective'})
    assert entered.wait(3)
    assert not providers
    assert outings.get(job['id']).get('executions', []) == []
    release.set()
    for _ in range(100):
        job = outings.get(job['id'])
        if job['status'] != 'preparing':
            break
        time.sleep(.02)
    assert job['status'] == 'partial'
    assert not providers
    assert job.get('executions', []) == []


@pytest.mark.parametrize('destination', outings.DESTINATIONS, ids=lambda item: item['id'])
def test_real_route_request_and_calendar_use_paris_and_both_legs(store, monkeypatch, destination):
    store = {**store, 'destination_id': destination['id']}
    def fake_get(url, params, timeout):
        origin = ','.join(map(str, outings.ORIGIN['coordinates']))
        target = ','.join(map(str, destination['coordinates']))
        assert url == f'https://router.project-osrm.org/route/v1/driving/{origin};{target};{origin}'
        assert params['steps'] == 'true'
        return httpx.Response(200, json={'code': 'Ok', 'routes': [{'legs': [
            {'duration': 610, 'distance': 3100, 'steps': []},
            {'duration': 910, 'distance': 4500, 'steps': []}]}]}, request=httpx.Request('GET', url))
    monkeypatch.setattr(outings.httpx, 'get', fake_get)
    agenda = [{'at': store['date'] + 'T09:45:00+01:00', 'title': 'Conseil fictif', 'duration_minutes': 30}]
    route, calendar = outings._route_and_calendar(store, agenda)
    assert route['destination']['id'] == destination['id']
    assert route['duration_minutes'] == 11
    assert route['return_duration_minutes'] == 16
    assert route['departure_at'].endswith('+01:00')
    assert datetime.fromisoformat(route['departure_at']).strftime('%H:%M') == '09:29'
    assert datetime.fromisoformat(route['return_at']).strftime('%H:%M') == '12:36'
    assert [c['title'] for c in calendar['conflicts']] == ['Conseil fictif']
    assert 'emploi du temps complet' in calendar['scope_note'] or 'disponibilité' in calendar['scope_note']


def test_failures_stay_partial_and_objective_invalidates_saved(store, monkeypatch):
    monkeypatch.setattr(outings, '_search_visit', lambda _: (_ for _ in ()).throw(httpx.ConnectError('secret-token')))
    monkeypatch.setattr(outings, '_route_and_calendar', lambda *_: (_ for _ in ()).throw(ValueError('bad')))
    monkeypatch.setattr(outings, '_fill_with_h', lambda _: (_ for _ in ()).throw(ValueError('bad')))
    job = outings.start(store)
    for _ in range(100):
        job = outings.get(job['id'])
        if job['status'] != 'preparing':
            break
        time.sleep(.02)
    assert job['status'] == 'partial'
    assert job['budget']['total'] is None
    assert 'secret-token' not in json.dumps(job)
    assert len(job['dossier']['missing_fields']) > 6
    saved = outings.save_dossier(job['id'])
    assert saved['saved'] is True
    updated = outings.update_objective(job['id'], 'Analyser un tableau et ses lignes de fuite')
    assert updated['saved'] is False
    assert 'lignes de fuite' in updated['dossier']['text']
    assert 'lignes de fuite' in updated['dossier']['family_letter']
    assert 'BROUILLON NON ENVOYÉ' in outings.export_text(job['id'])
    assert updated['revision'] == 2


def test_strict_ids_and_restart_interruption(store):
    for identifier in ('../foo', 'x' * 12, ''):
        with pytest.raises(KeyError):
            outings.get(identifier)
    job = {'id': 'a' * 12, 'status': 'preparing', 'tasks': [{'id':'visit', 'status':'running'}],
           'agent': {'status':'collecting'}, 'parallel': {'active_count':1, 'max_concurrent':1},
           'executions':[{'id':'prior-execution', 'task_id':'visit', 'status':'running', 'ended_at':None}]}
    outings._persist(job)
    result = outings.get(job['id'])
    assert result['status'] == 'failed'
    assert result['tasks'][0]['status'] == 'failed'
    assert result['executions'][0]['status'] == 'cancelled'
    assert result['executions'][0]['ended_at']
    assert result['executions'][0]['error']
    assert result['parallel']['active_count'] == 0
    assert result['agent']['status'] in ('failed', 'interrupted')


@pytest.mark.parametrize('bad', [{'adults': True}, {'subsidy': 'NaN'}, {'transport_total': '-1'},
                                {'visit_time': '27:00'}, {'destination_id': 'https://evil.test'},
                                {'objective': 'x' * 3001}])
def test_invalid_inputs(store, bad):
    with pytest.raises(ValueError):
        outings._validate({**store, **bad})


@pytest.mark.parametrize('destination', outings.DESTINATIONS, ids=lambda item: item['id'])
def test_citation_domain_required_and_missing_price_citation_stays_unknown(store, monkeypatch, destination):
    store = {**store, 'destination_id': destination['id']}
    facts = {**visit(), 'facts': [{'field': 'student_unit_price', 'value': 0, 'quote': 'Gratuit', 'url': 'https://evil.test/price'},
                                 {'field': 'closed_on_date', 'value': False, 'quote': 'Ouvert le jeudi', 'url': destination['official_url']},
                                 {'field': 'opening_time', 'value': '09:30', 'quote': '9h30', 'url': destination['official_url']}]}
    facts.pop('sources')
    monkeypatch.setattr(outings, 'key', lambda _: 'test-key')
    def fake_post(url, **kwargs):
        assert kwargs['json']['includeDomains'] == [destination['domain']]
        assert destination['name'] in kwargs['json']['q']
        return httpx.Response(200, json=facts, request=httpx.Request('POST', url))
    monkeypatch.setattr(outings.httpx, 'post', fake_post)
    result = outings._search_visit(store)
    assert result['opening_time'] == '09:30'
    assert result['student_unit_price'] is None
    assert all(s['url'] == destination['official_url'] for s in result['sources'])
    assert result['name'] == destination['name']


@pytest.mark.parametrize('destination', outings.DESTINATIONS, ids=lambda item: item['id'])
def test_closure_and_overnight_visits_are_not_marked_valid(store, destination):
    store = {**store, 'destination_id': destination['id']}
    job = {'input': {**store, 'objective': 'Observer les œuvres'}, 'revision': 1,
           'visit': {**visit(), 'closed_on_date': True, 'opening_time': None, 'closing_time': None},
           'roster': outings._read_roster(store), 'route': None, 'calendar': None}
    _, dossier, warnings = outings._build_dossier(job)
    assert f"Destination : {destination['name']} — {destination['address']}" in dossier['text']
    assert f"sortie à destination de {destination['name']}" in dossier['family_letter']
    assert any('fermé' in warning for warning in warnings)
    job['visit'] = visit()
    job['input']['visit_time'] = '23:00'
    _, _, warnings = outings._build_dossier(job)
    assert any('dépasse' in warning for warning in warnings)
    job['visit']['opening_time'] = None
    job.update(budget={'complete': True}, warnings=[])
    assert outings._incomplete(job) is True


def _linkup(monkeypatch, destination, facts):
    sent = {}
    monkeypatch.setattr(outings, 'key', lambda _: 'test-key')

    def fake_post(url, **kwargs):
        sent.update(kwargs['json'])
        return httpx.Response(200, json=facts, request=httpx.Request('POST', url))
    monkeypatch.setattr(outings.httpx, 'post', fake_post)
    return sent


def test_schema_asks_for_exact_field_keys(store, monkeypatch):
    destination = outings.DESTINATIONS[0]
    sent = _linkup(monkeypatch, destination, {**visit(), 'facts': []})
    outings._search_visit(store)
    schema = json.loads(sent['structuredOutputSchema'])
    assert schema['$defs']['VisitFact']['properties']['field']['enum'] == list(outings.FACT_FIELDS)
    assert 'max_group_size' in sent['q'] and 'exactement' in sent['q']


def test_french_labels_from_a_real_linkup_answer_support_no_field(store, monkeypatch):
    destination = outings.DESTINATIONS[0]
    url = destination['official_url']
    facts = {**visit(), 'facts': [
        {'field': 'effectif maximal groupe scolaire', 'value': 30, 'quote': 'Groupes de 30 élèves maximum', 'url': url},
        {'field': 'tarifs et réservation des groupes scolaires', 'value': 'Gratuit', 'quote': 'Gratuit pour les scolaires', 'url': url},
        {'field': 'admission des groupes scolaires', 'value': None, 'quote': 'Sur réservation', 'url': url}]}
    facts.pop('sources')
    _linkup(monkeypatch, destination, facts)
    result = outings._search_visit(store)
    assert all(result[field] is None for field in outings.FACT_FIELDS)
    assert result['unlabelled_facts'] == 3 and len(result['sources']) == 3
    assert result['unsupported_fields']['max_group_size'] == 'aucune citation officielle avec cette clé'


@pytest.mark.parametrize('field, top, cited, kept', [
    ('student_unit_price', '12.00', ['12', 12.0], '12.00'),
    ('student_unit_price', '12.00', ['12', '15'], None),
    ('max_group_size', 30, [30], 30),
    ('max_group_size', 30, ['30'], None),
    ('max_group_size', 30, [True], None),
    ('closed_on_date', False, [False], False),
    ('closed_on_date', False, ['non'], None),
    ('opening_time', '09:30', ['09:30'], '09:30'),
    ('opening_time', '09:30', ['10:00'], None),
])
def test_value_is_kept_only_when_every_citation_states_it(store, monkeypatch, field, top, cited, kept):
    destination = outings.DESTINATIONS[0]
    facts = {**visit(), field: top,
             'facts': [{'field': field, 'value': v, 'quote': 'extrait', 'url': destination['official_url']} for v in cited]}
    facts.pop('sources')
    _linkup(monkeypatch, destination, facts)
    result = outings._search_visit(store)
    assert result[field] == kept
    assert (field in result['unsupported_fields']) is (kept is None)
