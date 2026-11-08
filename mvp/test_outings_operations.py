"""Local demonstration transitions must never become external operations."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from . import outings_operations as ops


@pytest.fixture
def job():
    return {'id': 'demo-outing', 'revision': 3,
            'input': {'date': '2026-11-12', 'objective': 'Comparer deux œuvres impressionnistes.'},
            'roster': {'student_count': 28, 'adults': 2},
            'route': {'destination': {'name': 'Musée d’Orsay'},
                      'departure_at': '2026-11-12T09:27:00+01:00', 'return_at': '2026-11-12T12:31:00+01:00'},
            'budget': {'per_student': '6.43'},
            'dossier': {'text': 'DOSSIER DE DÉMONSTRATION — BROUILLON À VALIDER'}}


def complete(job):
    for action in (ops.prepare_parent_messages, ops.simulate_family_responses,
                   ops.prepare_targeted_reminders, ops.prepare_photo_permissions,
                   ops.check_equipment, ops.reserve_equipment, ops.prepare_administration):
        action(job)
    return job['operations']


def test_fake_messages_and_confirmations_are_local_and_non_routable(job):
    first = ops.prepare_parent_messages(job)
    assert first['counts']['initial_messages'] == 28
    assert first['mode'] == 'simulation' and first['external_effects'] is False
    state = job['operations']
    assert all(f['email'].endswith('@example.invalid') for f in state['families'])
    assert all(m['actual_sent'] is False and m['external_effects'] is False for m in state['messages'])
    assert all(m['state'] == 'simulated_sent' and 'NON ENVOYÉ' in m['subject'] for m in state['messages'])
    assert '6,43 €' in state['messages'][0]['body']
    assert '09:27' in state['messages'][0]['body']
    assert 'Comparer deux œuvres' in state['messages'][0]['body']
    response = ops.simulate_family_responses(job)
    assert response['counts']['confirmed'] == 20
    assert response['counts']['declined'] == 2
    assert response['counts']['pending'] == 6
    assert response['counts']['confirmation_messages'] == 20
    assert all(f['response_source'] == ops.SCENARIO_SOURCE for f in state['families'])
    assert all(m['actual_sent'] is False for m in state['messages'])


def test_reminders_target_only_nonresponders_and_do_not_repeat(job):
    ops.prepare_parent_messages(job)
    ops.simulate_family_responses(job)
    result = ops.prepare_targeted_reminders(job)
    state = job['operations']
    pending = {f['id'] for f in state['families'] if f['response'] == 'pending'}
    recipients = {m['recipient_id'] for m in state['messages'] if m['kind'] == 'reminder'}
    assert len(recipients) == result['counts']['reminders'] == 6
    assert recipients == pending
    assert not recipients & {f['id'] for f in state['families'] if f['response'] in ('confirmed', 'declined')}
    before = deepcopy(state)
    assert ops.prepare_targeted_reminders(job)['cached'] is True
    assert job['operations'] == before


def test_photo_choices_are_separate_and_refusals_are_excluded(job):
    # Preparing photos before participation responses must not entangle them.
    photo = ops.prepare_photo_permissions(job)
    assert photo['photo']['counts'] == {'authorized': 18, 'refused': 4, 'pending': 6}
    choices = {f['id']: f['photo_consent'] for f in job['operations']['families']}
    ops.prepare_parent_messages(job)
    ops.simulate_family_responses(job)
    state = job['operations']
    assert choices == {f['id']: f['photo_consent'] for f in state['families']}
    assert any(f['response'] == 'declined' and f['photo_consent'] == 'authorized' for f in state['families'])
    assert any(f['response'] == 'confirmed' and f['photo_consent'] == 'pending' for f in state['families'])
    blocked = set(state['photo']['blocked_families'])
    assert blocked == {f['id'] for f in state['families'] if f['photo_consent'] != 'authorized'}
    assert state['photo']['actual_signatures'] == 0
    assert state['photo']['document']['status'] == 'draft'
    assert 'Le refus de photo ne change pas la participation' in state['photo']['document']['text']


def test_equipment_stock_is_conserved_and_rebooking_is_idempotent(job):
    with pytest.raises(ValueError, match='equipment_check'):
        ops.reserve_equipment(job)
    ops.check_equipment(job)
    equipment = job['operations']['equipment']
    assert equipment['conflicts'][0]['missing'] == 2
    assert equipment['fallbacks'][0]['quantity'] == 4
    ops.reserve_equipment(job)
    for item in equipment['items']:
        assert item['allocated'] <= item['available']
        assert item['allocated'] <= item['requested']
    assert equipment['status'] == 'reserved_simulation'
    assert equipment['actual_reserved'] is False
    assert all(r['actual_reserved'] is False and r['external_effects'] is False for r in equipment['reservations'])
    assert next(r for r in equipment['reservations'] if r['item_id'] == 'tablets')['quantity'] == 6
    assert next(r for r in equipment['reservations'] if r['item_id'] == 'paper-kits')['quantity'] == 4
    assert all(item['remaining'] >= 0 for item in equipment['items'])
    assert all(c['resolution_state'] == 'simulated_resolved' for c in equipment['conflicts'])
    before = deepcopy(equipment)
    assert ops.reserve_equipment(job)['cached'] is True
    assert job['operations']['equipment'] == before


def test_admin_drafts_never_claim_official_approval_or_real_signatures(job):
    state = complete(job)
    assert state['completed_steps'] == list(ops.STEPS)
    assert state['counts']['admin_prepared_documents'] == 4
    assert state['counts']['admin_pending_checks'] == 4
    assert state['admin']['approval_status'] == 'not_requested'
    assert state['admin']['actual_approved'] is False
    assert state['admin']['actual_signatures'] == 0
    assert all(d['status'] == 'draft' and d['actual_approved'] is False for d in state['admin']['documents'])
    assert next(c for c in state['admin']['checklist'] if c['id'] == 'principal')['status'] == 'pending'
    assert all(c['actual_approved'] is False for c in state['admin']['checklist'])
    assert all(event['simulated'] and event['external_effects'] is False for event in state['events'])
    assert len({event['id'] for event in state['events']}) == len(ops.STEPS)
    before = deepcopy(state)
    for action in (ops.prepare_parent_messages, ops.simulate_family_responses, ops.prepare_targeted_reminders,
                   ops.prepare_photo_permissions, ops.check_equipment, ops.reserve_equipment, ops.prepare_administration):
        assert action(job)['cached'] is True
    assert job['operations'] == before


def test_administration_requires_family_followup_results_before_summary(job):
    ops.prepare_parent_messages(job)
    ops.prepare_photo_permissions(job)
    ops.check_equipment(job)
    ops.reserve_equipment(job)
    with pytest.raises(ValueError, match='family_responses'):
        ops.prepare_administration(job)
    assert job['operations']['admin'] == {}
    ops.simulate_family_responses(job)
    with pytest.raises(ValueError, match='targeted_reminders'):
        ops.prepare_administration(job)
    ops.prepare_targeted_reminders(job)
    ops.prepare_administration(job)
    assert '6 familles sans réponse' in job['operations']['admin']['summary']


def test_revision_changes_preserve_facts_but_reject_stale_actions(job):
    complete(job)
    before = deepcopy(job['operations'])
    job['revision'] += 1
    job['input']['objective'] = 'Un nouvel objectif à reprendre.'
    with pytest.raises(ValueError, match='dossier a changé'):
        ops.prepare_parent_messages(job)
    with pytest.raises(ValueError):
        ops.summary(job)
    assert job['operations'] == before


def test_root_owned_status_and_session_metadata_survive_initialisation(job):
    job['operations'] = {'status': 'running', 'session_id': 'h-session', 'snapshot_revision': job['revision'],
                         'events': [{'step': 'session', 'text': 'Session créée'}]}
    result = ops.ensure(job)
    assert result['session_id'] == 'h-session'
    assert result['status'] == 'running'
    assert result['events'][0]['step'] == 'session'


@pytest.mark.parametrize('bad_count', [None, 0, True, 61, '28'])
def test_missing_or_invalid_roster_is_not_replaced_by_28(job, bad_count):
    job['roster']['student_count'] = bad_count
    with pytest.raises(ValueError, match='liste de classe'):
        ops.prepare_parent_messages(job)
    assert job['operations']['messages'] == []


def test_incomplete_prices_stay_unknown_in_messages(job):
    job['budget']['per_student'] = None
    ops.prepare_parent_messages(job)
    assert 'Participation prévisionnelle : à confirmer' in job['operations']['messages'][0]['body']


def test_no_transport_imports_and_summary_has_no_message_payloads(job):
    tree = ast.parse(Path(ops.__file__).read_text())
    imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert set(imported) <= {'copy', 'datetime', 'decimal', 'zoneinfo'}
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    complete(job)
    response = ops.summary(job)
    assert 'messages' not in response and 'families' not in response
    assert len(json.dumps(response)) < 7000
    assert response['notice'].startswith('Tout ce suivi est simulé localement')


def test_actual_addresses_or_effect_flags_cannot_be_injected(job):
    ops.prepare_parent_messages(job)
    job['operations']['families'][0]['email'] = 'someone@example.com'
    with pytest.raises(ValueError, match='adresses fictives'):
        ops.simulate_family_responses(job)
    job['operations']['families'][0]['email'] = 'someone@example.invalid'
    job['operations']['external_effects'] = True
    with pytest.raises(ValueError, match='sans effets externes'):
        ops.check_equipment(job)


def test_payment_previews_are_individual_and_never_count_participation_as_payment(job):
    state = complete(job)
    payments = state['payments']
    assert payments['provider'] == 'Stripe'
    assert payments['actual_collected'] == '0.00'
    entries = payments['entries']
    assert len(entries) == len({e['url'] for e in entries}) == 28
    assert all(e['amount'] == '6.43' and e['actual_paid'] is False for e in entries)
    assert all(e['actual_sent'] is False and e['external_effects'] is False for e in entries)
    assert sum(e['status'] == 'cancelled' for e in entries) == 2
    for message in (m for m in state['messages'] if m['kind'] == 'invitation'):
        entry = next(e for e in entries if e['family_id'] == message['recipient_id'])
        assert entry['url'] in message['body']
        assert entry['url'].startswith('https://checkout.example.invalid/')
    reminders = [m for m in state['messages'] if m['kind'] == 'payment_reminder']
    confirmed = {f['id'] for f in state['families'] if f['response'] == 'confirmed'}
    assert len(reminders) == 20
    assert {m['recipient_id'] for m in reminders} == confirmed
    before = deepcopy(state)
    ops.prepare_targeted_reminders(job)
    assert state == before


@pytest.mark.parametrize('amount', [None, '0', '-1', 'NaN', 'Infinity', '0.001', '100001'])
def test_invalid_payment_amount_never_generates_a_link(job, amount):
    job['budget']['per_student'] = amount
    ops.prepare_parent_messages(job)
    assert job['operations']['payments']['status'] == 'budget_required'
    assert job['operations']['payments']['entries'] == []
    assert all('checkout.example.invalid' not in m['body'] for m in job['operations']['messages'])


def test_partial_budget_never_generates_payment_links(job):
    job['budget']['complete'] = False
    ops.prepare_parent_messages(job)
    assert job['operations']['payments']['entries'] == []
