"""No-network contracts for the H → DemoBro video transaction."""
import json
from types import SimpleNamespace

import pytest
import yaml
from hai_agents.tools import as_tools

from .generate_voice_effects_demo import (RenderTools, require_presenter,
                                          execute_h_render, DemoRenderReceipt,
                                          prepare_remote, PRESENTER)


class DemoBroStub:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response if response is not None else {'render_id': 'remote-render'}
        self.error = error

    def call(self, name, args):
        self.calls.append((name, args))
        if self.error:
            raise self.error
        return self.response


def make_tools(tmp_path, client=None):
    return RenderTools(tmp_path, client or DemoBroStub(), 'scenarios: []\n', 'project', {'voice': 'owner'})


def test_sdk_can_describe_both_real_function_calls(tmp_path):
    tools = make_tools(tmp_path)
    definitions = as_tools(tools.tools)
    assert [tool.name for tool in definitions] == ['read_demo_brief', 'render_demobro_demo']
    assert definitions[1].input_schema['required'] == ['prepared_demo_id']


def test_render_is_gated_by_read_and_exact_prepared_id(tmp_path):
    client = DemoBroStub()
    tools = make_tools(tmp_path, client)
    read, render = tools.tools
    with pytest.raises(ValueError, match='Lire le brief'):
        render(tools.prepared_id)
    read()
    with pytest.raises(ValueError, match='identifiant'):
        render('forged')
    assert client.calls == []
    assert [call['status'] for call in tools.state['tool_calls']] == ['failed', 'succeeded', 'failed']


def test_confirmed_render_is_reused_without_another_debit(tmp_path):
    client = DemoBroStub()
    tools = make_tools(tmp_path, client)
    read, render = tools.tools
    brief = json.loads(read())
    first = json.loads(render(brief['prepared_demo_id']))
    second = json.loads(render(brief['prepared_demo_id']))
    assert first['render_id'] == second['render_id'] == 'remote-render'
    assert second['reused'] is True
    assert len(client.calls) == 1
    name, arguments = client.calls[0]
    assert name == 'render_demo_from_yaml'
    assert arguments['draft'] is False and arguments['interactive'] is True
    assert 'confirm_long_render' not in arguments
    assert 'animation_style' not in arguments
    assert tools.state['tool_calls'][-1]['cached'] is True
    assert tools.validate_receipt({'render_id': 'remote-render'}) == 'remote-render'
    with pytest.raises(ValueError, match='réellement confirmé'):
        tools.validate_receipt({'render_id': 'forged'})


@pytest.mark.parametrize('response,error', [({}, None), (None, RuntimeError('network outcome unknown'))])
def test_unconfirmed_submission_never_resubmits(tmp_path, response, error):
    client = DemoBroStub(response=response, error=error)
    tools = make_tools(tmp_path, client)
    read, render = tools.tools
    read()
    with pytest.raises(RuntimeError):
        render(tools.prepared_id)
    with pytest.raises(RuntimeError, match='sans identifiant confirmé'):
        render(tools.prepared_id)
    assert len(client.calls) == 1
    assert (tmp_path / 'submission.json').exists()


def test_h_executes_tools_and_final_receipt_comes_from_the_real_ledger(tmp_path):
    tools = make_tools(tmp_path)
    class Session:
        id = 'h-session'
        def wait_for_completion(self, **kwargs):
            brief = json.loads(tools.tools[0]())
            rendered = json.loads(tools.tools[1](brief['prepared_demo_id']))
            return SimpleNamespace(status='idle', answer={'render_id': rendered['render_id']})
    class HClient:
        def start_session(self, **kwargs):
            assert kwargs['agent']['environments'] == []
            assert kwargs['answer_schema'] is DemoRenderReceipt
            assert kwargs['tools'] == tools.tools
            return Session()
    result = execute_h_render(tools, client_factory=HClient)
    assert result == 'remote-render'
    state = json.loads((tmp_path / 'h-tool-state.json').read_text())
    assert state['session_id'] == 'h-session'
    assert len(state['tool_calls']) == 2
    assert all(call['session_id'] == 'h-session' and call['status'] == 'succeeded' for call in state['tool_calls'])


def test_h_brief_removes_account_debug_from_nested_estimates(tmp_path):
    tools = RenderTools(tmp_path, DemoBroStub(), 'scenarios: []\n', 'project', {
        'cost': {'credits': 120, 'mcp_debug': {'account': {'email': 'private@example.com'}}},
        'duration': {'seconds': 63, 'mcp_debug': {'billing': 'private-billing'}},
        'coverage': [{'scene': 'copy', 'mcp_debug': {'headers': 'private'}}],
    })
    result = tools.tools[0]()
    brief = json.loads(result)['brief']
    assert brief['cost'] == {'credits': 120}
    assert brief['duration'] == {'seconds': 63}
    assert brief['coverage'] == [{'scene': 'copy'}]
    assert 'private' not in result
    assert 'mcp_debug' not in result


@pytest.mark.parametrize('changed', [{'consented': False}, {'is_owner': False}, {'is_active': False}])
def test_voice_and_avatar_must_belong_to_the_active_consented_owner(changed):
    record = {'id': 'voice', 'consented': True, 'is_owner': True, 'is_active': True, **changed}
    with pytest.raises(ValueError, match='consenti'):
        require_presenter([record], 'voice')


def test_voice_profile_is_selected_exactly():
    record = {'id': 'voice', 'consented': True, 'is_owner': True, 'is_active': True}
    assert require_presenter([record], 'voice') is record


def test_browser_probe_omits_plugins_but_full_validation_and_render_keep_them(tmp_path):
    configuration = {'voice': {'engine': 'custom', 'voice_id': PRESENTER}, 'scenarios': [{
        'url': 'https://snapshot.example',
        'avatar': {'enabled': True, 'presenter_id': PRESENTER},
        'steps': [{'action': 'navigate', 'url': 'https://snapshot.example',
                   'effects': [{'type': 'demobro_motion', 'preset': 'camera_push', 'selector': '.tool-call-metrics'}]},
                  {'action': 'click', 'locator': {'type': 'css', 'value': '#keep'}}]}]}
    raw = yaml.safe_dump(configuration)
    class Client:
        def __init__(self):
            self.calls = []
        def call(self, name, args):
            self.calls.append((name, args))
            return {
                'list_presenters': [{'id': PRESENTER, 'name': 'François', 'is_owner': True,
                                     'is_active': True, 'consented': True}],
                'validate_demo_config': {'valid': True},
                'probe_demo_config': {'resolved': True, 'unresolved': 0, 'ambiguous': 0},
                'estimate_demo_cost': {'affordable': True},
                'estimate_demo_duration': {'long_render': False},
                'create_project': {'id': 'project'}, 'get_project_brief': {'summary': 'Verified'},
                'render_demo_from_yaml': {'render_id': 'remote-render'},
            }[name]
    client = Client()
    prepared = prepare_remote(client, tmp_path, raw)
    calls = dict(client.calls)
    assert calls['validate_demo_config']['yaml_config'] == raw
    assert calls['estimate_demo_cost']['yaml_config'] == raw
    assert calls['estimate_demo_duration']['yaml_config'] == raw
    assert calls['create_project']['yaml_config'] == raw
    assert 'animation_style' not in calls['create_project']
    probe = yaml.safe_load(calls['probe_demo_config']['yaml_config'])
    assert 'avatar' not in probe['scenarios'][0]
    assert all('effects' not in step for step in probe['scenarios'][0]['steps'])
    assert probe['scenarios'][0]['steps'][1]['locator']['value'] == '#keep'
    omissions = json.loads((tmp_path / 'probe-omissions.json').read_text())
    assert omissions['render_yaml_unchanged'] is True
    assert len(omissions['omissions']) == 2
    assert omissions['omissions'][1]['effects'][0]['selector'] == '.tool-call-metrics'
    tools = RenderTools(tmp_path, client, raw, prepared['project_id'], {})
    tools.tools[0]()
    tools.tools[1](tools.prepared_id)
    rendered = client.calls[-1][1]['yaml_config']
    assert rendered == raw
    assert yaml.safe_load(rendered) == configuration
