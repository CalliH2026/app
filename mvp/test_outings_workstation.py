"""Only executed workstation commands with attached visual evidence qualify."""
import base64
from io import BytesIO
from types import SimpleNamespace
import pytest
from PIL import Image

from .outings_workstation import (extract_workstation_evidence, workstation_environment,
                                  workstation_evidence)

_image = BytesIO()
Image.new('RGB', (2, 2), 'white').save(_image, format='PNG')
PNG = base64.b64encode(_image.getvalue()).decode()
URL = 'https://www.musee-orsay.fr/fr/vous-etes'
PATH = '/tmp/screenshots/0001.png'
SESSION = 'session-workstation'
RESOURCE = f'https://agp.eu.hcompany.ai/api/v1/trajectories/{SESSION}/resources/bucket-1/{SESSION}/screenshot-abc123.png'


def event(command=None, output=None, **result):
    command = command or f'web goto {URL} && web scroll down 3; web screenshot'
    output = output or (f"[web goto {URL}] url={URL} title='Vous êtes' tab=t1\n"
                        '[web scroll down 3] changed=20%\n'
                        f"[web screenshot] #0001 url={URL} title='Vous êtes' saved={PATH}\n@@attach {PATH}")
    return {'type':'AgentEvent','timestamp':'2026-11-07T16:00:00Z','data':{
        'kind':'tool_result','tool_req':{'tool_name':'shell','args':{'command':command}},
        'result':{'state':'completed','exit_code':0,'output':output,'attachments':{PATH:PNG},**result}}}


def proof(value):
    return extract_workstation_evidence([value], 'musee-orsay.fr')


def cloud_event():
    """Observed H cloud wire format: execution receipt, then scoped image."""
    value = event(command=f'web goto {URL} && web screenshot')
    execution = value['data']['result']
    execution['output'] = execution['output'].replace('[web scroll down 3] changed=20%\n', '').replace('@@attach '+PATH, '')
    execution['attachments'] = {}
    value['data']['result'] = [execution, {'source':RESOURCE, 'type':'url', 'media_type':'image/png'}]
    return value


def test_environment_is_explicitly_cloud_and_ephemeral():
    env = workstation_environment()
    assert env == {'id':'outing-workstation','kind':'workstation','host':'cloud','storage':{'ephemeral':True}}
    assert 'session_id' not in env and 'use_default_volume' not in env['storage']


def test_matching_web_receipts_and_attachment_prove_execution_without_retaining_raw_data():
    result = proof(event())
    assert result['verified'] is True
    assert result['visual_observation_count'] == 1
    assert result['executed_action_count'] == 2
    assert result['environment'] == 'workstation' and result['storage'] == 'ephemeral'
    assert PNG not in str(result) and 'command' not in result
    assert all(item['url'].startswith('https://www.musee-orsay.fr/') for item in result['actions'])


@pytest.mark.parametrize('change', [
    {'exit_code':1}, {'state':'running'}, {'timed_out':True}, {'failure':{'message':'failed'}},
    {'isError':True}, {'success':False}, {'status':'failed'},
    {'attachments':{}}, {'attachments':{'/tmp/other.png':PNG}}, {'attachments':{PATH:'not-base64'}},
    {'attachments':{PATH:base64.b64encode(b'\x89PNG\r\n\x1a\nfake').decode()}},
])
def test_failed_or_unattached_results_never_qualify(change):
    assert proof(event(**change))['verified'] is False


@pytest.mark.parametrize('command', [
    f'echo "{URL}"', f'printf "[web screenshot] url={URL}"',
    f'python3 -c "print(\"{URL}\")"', f'web goto {URL} | cat',
    f'web goto {URL}; echo fake; web screenshot', f'web goto {URL} && web js "return 1"',
    f'web goto {URL} && web screenshot > /tmp/out', f'web goto {URL}\nweb screenshot',
])
def test_arbitrary_shell_or_forged_text_is_not_visual_execution(command):
    assert proof(event(command=command))['verified'] is False


def test_receipt_with_no_marker_or_foreign_domain_is_not_verified():
    value = event()
    value['data']['result']['output'] = value['data']['result']['output'].replace('@@attach '+PATH, '')
    assert proof(value)['verified'] is False
    value = event()
    value['data']['result']['output'] = value['data']['result']['output'].replace(URL, 'https://evil.test/')
    assert proof(value)['verified'] is False


def test_blocked_page_retains_warning_but_cannot_prove_success():
    value = event()
    value['data']['result']['output'] = value['data']['result']['output'].replace("title='Vous êtes'", "title='Access denied'")
    result = proof(value)
    assert result['verified'] is False
    assert result['access_warnings'] and result['blocked_observation_count'] == 1


def test_policy_request_and_bare_shell_success_do_not_qualify():
    value = event()
    value['data']['kind'] = 'policy_event'
    assert proof(value)['verified'] is False
    value = event()
    value['data']['result'] = 'Success: '+URL
    assert proof(value)['verified'] is False
    value = event()
    value['data']['error'] = 'provider action failed'
    assert proof(value)['verified'] is False


def test_valid_follow_up_after_blocked_page_can_qualify():
    blocked = event()
    blocked['data']['result']['output'] = blocked['data']['result']['output'].replace("title='Vous êtes'", "title='Access denied'")
    result = extract_workstation_evidence([blocked,event()], 'musee-orsay.fr')
    assert result['verified'] is True and result['access_warnings']


def test_bounded_history_reader_uses_actual_provider_changes():
    calls=[]
    def changes(identifier, **kwargs):
        calls.append(kwargs)
        return {'first_index':0,'new_events':[event()]}
    client=SimpleNamespace(sessions=SimpleNamespace(get_session_changes=changes))
    result=workstation_evidence(client,'session-workstation','musee-orsay.fr')
    assert result['verified'] is True and result['pages_checked']==1
    assert calls[0]['from_index']==0 and calls[0]['include_events'] is True


def test_observed_cloud_list_format_qualifies_without_retaining_resource_url():
    value = cloud_event()
    result = extract_workstation_evidence([value], 'musee-orsay.fr', session_id=SESSION)
    assert result['verified'] is True
    assert result['visual_observation_count'] == 1
    assert result['observations'][0]['image_provenance'] == 'provider_session_resource'
    assert RESOURCE not in str(result) and '/resources/' not in str(result)


@pytest.mark.parametrize('change', [
    {'source':RESOURCE.replace('agp.eu.hcompany.ai', 'evil.test')},
    {'source':RESOURCE.replace('https:', 'http:')},
    {'source':RESOURCE.replace('/'+SESSION+'/', '/another-session/')},
    {'source':RESOURCE.replace('/screenshot-abc123.png', '/arbitrary.png')},
    {'source':RESOURCE.replace('agp.eu.hcompany.ai', 'agp.eu.hcompany.ai.evil.test')},
    {'media_type':'text/plain'}, {'type':'text'},
])
def test_cloud_image_must_be_session_scoped_h_image_resource(change):
    value = cloud_event()
    value['data']['result'][1].update(change)
    assert extract_workstation_evidence([value], 'musee-orsay.fr', session_id=SESSION)['verified'] is False


def test_cloud_images_from_another_session_never_qualify_in_production_reader():
    client = SimpleNamespace(sessions=SimpleNamespace(get_session_changes=lambda *args, **kwargs:
                             {'first_index':0, 'new_events':[cloud_event()]}))
    assert workstation_evidence(client, 'different-session', 'musee-orsay.fr')['verified'] is False


def test_cloud_list_requires_one_unambiguous_screenshot_receipt_and_genuine_command():
    value = cloud_event()
    value['data']['tool_req']['args']['command'] = 'cat /tmp/receipt.log'
    assert extract_workstation_evidence([value], 'musee-orsay.fr', session_id=SESSION)['verified'] is False
    value = cloud_event()
    value['data']['result'][0]['output'] += f'\n[web screenshot] #0002 url={URL} saved=/tmp/screenshots/0002.png'
    assert extract_workstation_evidence([value], 'musee-orsay.fr', session_id=SESSION)['verified'] is False
    value = cloud_event()
    value['data']['result'][0]['output'] = value['data']['result'][0]['output'].replace("title='Vous êtes'", "title='Access denied'")
    assert extract_workstation_evidence([value], 'musee-orsay.fr', session_id=SESSION)['verified'] is False


def test_cloud_result_failure_is_not_rescued_by_valid_provider_image():
    value = cloud_event()
    value['data']['result'][0]['exit_code'] = 5
    assert extract_workstation_evidence([value], 'musee-orsay.fr', session_id=SESSION)['verified'] is False
