"""Browser proof must come from provider events, without retaining raw images."""
import base64
import json
from types import SimpleNamespace

import pytest

from .outings_holo import browser_evidence, extract_browser_evidence


URL = 'https://www.musee-orsay.fr/fr/scolaires?token=private#section'


def observation(url=URL, image=True, kind='web'):
    return {'type': 'AgentEvent', 'timestamp': '2026-11-07T15:00:00Z', 'data': {
        'kind': 'observation_event', 'type': kind,
        'metadata': {'url': url, 'title': 'Visites scolaires', 'text': 'do not retain page text'},
        'image': {'type': 'url', 'source': 'https://images.example/signed?secret=private'} if image else None}}


def action(name='scroll_web', args=None, result=None, proposed=False):
    request = {'tool_name': name, 'args': args or {'direction': 'down'}, 'id': 'call-1'}
    return {'type': 'AgentEvent', 'timestamp': '2026-11-07T15:00:01Z', 'data': {
        'kind': 'policy_event' if proposed else 'tool_result',
        **({'tool_reqs': [request], 'reasoning_content': 'must never retain'} if proposed else
           {'tool_req': request, 'result': result})}}


def test_actual_visual_and_action_evidence_is_sanitized():
    result = extract_browser_evidence([observation(), action()], 'musee-orsay.fr')
    assert result['verified'] is True
    assert result['visual_observation_count'] == result['executed_action_count'] == 1
    assert result['urls'] == ['https://www.musee-orsay.fr/fr/scolaires']
    assert result['actions'][0]['tool'] == 'scroll_web'
    rendered = json.dumps(result)
    for forbidden in ('private', 'signed', 'image', 'retain page text', 'must never retain'):
        # Only the literal image payload/URL is sensitive; evidence_source names images.
        if forbidden != 'image':
            assert forbidden not in rendered
    assert 'source' not in result['observations'][0]


@pytest.mark.parametrize('events', [
    [observation()],
    [observation(), action(proposed=True)],
    [observation(image=False), action()],
    [observation(url='https://musee-orsay.fr.evil.example'), action()],
    [observation(), action(result={'error': 'blocked'})],
    [observation(), action(result={'success': False})],
    [observation(), action(name='fill_administrative_dossier')],
    [observation(), observation(url='https://another.example'), action()],
    [observation(), action(args={'url': 'https://another.example'})],
    [observation(kind='desktop'), action()],
])
def test_configuration_text_foreign_or_failed_actions_do_not_prove_computer_use(events):
    assert extract_browser_evidence(events, 'musee-orsay.fr')['verified'] is False


def test_navigation_target_can_precede_first_official_observation():
    result = extract_browser_evidence([
        action(name='goto', args={'url': URL}), observation()], 'musee-orsay.fr')
    assert result['verified'] is True


def test_inline_image_is_validated_but_not_saved():
    event = observation()
    event['data']['image'] = {'type': 'base64', 'source': base64.b64encode(b'\x89PNG\r\n\x1a\nbytes').decode()}
    assert extract_browser_evidence([event, action()], 'musee-orsay.fr')['verified'] is True
    event['data']['image']['source'] = 'not a screenshot'
    assert extract_browser_evidence([event, action()], 'musee-orsay.fr')['verified'] is False


def test_provider_pagination_and_model_objects_are_supported():
    calls = []
    pages = [{'first_index': 0, 'new_events': [observation()] * 100},
             {'first_index': 100, 'new_events': [action()]}]
    def changes(session_id, **kwargs):
        calls.append((session_id, kwargs))
        return SimpleNamespace(model_dump=lambda **_: pages.pop(0))
    client = SimpleNamespace(sessions=SimpleNamespace(get_session_changes=changes))
    result = browser_evidence(client, 'session', 'musee-orsay.fr')
    assert result['verified'] is True
    assert result['events_checked'] == 101
    assert len(result['observations']) == 24
    assert calls[1][1]['from_index'] == 100
    assert all(call[1]['wait_for_seconds'] == 0 for call in calls)


def test_domain_and_userinfo_cannot_expand_scope():
    with pytest.raises(ValueError):
        extract_browser_evidence([], 'https://musee-orsay.fr')
    for url in ('https://musee-orsay.fr@evil.example', 'https://user:pass@musee-orsay.fr',
                'http://musee-orsay.fr', 'https://musee-orsay.fr:444'):
        assert not extract_browser_evidence([observation(url=url), action()], 'musee-orsay.fr')['verified']


@pytest.mark.parametrize('title', [
    'Accès refusé | Musée d’Orsay', 'ACCESS DENIED', '403 Forbidden',
    'Captcha | Musée d’Orsay', 'Just a moment...', 'Vérification de sécurité',
])
def test_blocked_page_images_and_clicks_do_not_qualify(title):
    blocked = observation()
    blocked['data']['metadata']['title'] = title
    result = extract_browser_evidence([blocked, action()], 'musee-orsay.fr')
    assert result['verified'] is False
    assert result['visual_observation_count'] == 0
    assert result['captured_visual_observation_count'] == 1
    assert result['blocked_observation_count'] == 1
    assert result['observations'][0]['blocked'] is True
    assert title in result['access_warnings'][0]


def test_valid_followup_after_blocked_page_preserves_the_warning():
    blocked = observation()
    blocked['data']['metadata']['title'] = 'Accès refusé | Musée d’Orsay'
    accessible = observation(url='https://www.musee-orsay.fr/fr/vous-etes')
    result = extract_browser_evidence([blocked, action(), accessible, action()], 'musee-orsay.fr')
    assert result['verified'] is True
    assert result['visual_observation_count'] == 1
    assert result['captured_visual_observation_count'] == 2
    assert result['executed_action_count'] == 1
    assert len(result['access_warnings']) == 1
    assert result['observations'][1]['blocked'] is False
    assert 'navigation uniquement' in result['scope']


def test_http_status_can_mark_an_otherwise_generic_title_as_blocked():
    blocked = observation()
    blocked['data']['metadata']['status_code'] = 403
    assert not extract_browser_evidence([blocked, action()], 'musee-orsay.fr')['verified']
