"""Calli review of upstream 349bd28: payment previews stay simulated for odd budgets and pre-upgrade saved states."""
from copy import deepcopy

import pytest

from . import outings_operations as ops
from .test_outings_operations import job  # noqa: F401  (fixture)


@pytest.mark.parametrize('amount', ['abc', True, '', '1e400', '-0', 'sNaN', [6], {'v': 6}])
def test_unusual_budget_values_never_generate_a_link(job, amount):  # noqa: F811
    job['budget']['per_student'] = amount
    ops.prepare_parent_messages(job)
    payments = job['operations']['payments']
    assert payments['status'] == 'budget_required' and payments['entries'] == []
    assert payments['actual_collected'] == '0.00'
    assert all('checkout.example.invalid' not in m['body'] for m in job['operations']['messages'])


def test_saved_state_from_before_payments_keeps_working_without_links(job):  # noqa: F811
    ops.prepare_parent_messages(job)
    legacy = deepcopy(job['operations'])
    legacy.pop('payments')
    for message in legacy['messages']:
        message['body'] = message['body'].split('\n\nParticipation de')[0].split('\n\nCollecte Stripe')[0]
    job['operations'] = legacy
    ops.simulate_family_responses(job)
    ops.prepare_targeted_reminders(job)
    state = job['operations']
    assert state['payments'] == {}
    assert not any(m['kind'] == 'payment_reminder' for m in state['messages'])
    assert all('checkout.example.invalid' not in m['body'] for m in state['messages'])
    assert ops.summary(job)['payments'] == {'provider': 'Stripe', 'status': 'not_started',
                                            'links': 0, 'actual_collected': '0.00'}


def test_payment_entries_never_claim_real_effects(job):  # noqa: F811
    ops.prepare_parent_messages(job)
    payments = job['operations']['payments']
    assert payments['simulated'] is True and payments['external_effects'] is False
    assert all(e['url'].startswith('https://checkout.example.invalid/') and e['simulated'] is True
               for e in payments['entries'])
