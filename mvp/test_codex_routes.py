"""Route activation needs an observed public path, not model confidence."""
import copy
import json
import subprocess

import pytest

from . import codex_routes


@pytest.fixture
def observations():
    return {
        'source_url': 'https://demo.index-education.net/pronote/professeur.html?fd=1',
        'app_version': '2026.2.8',
        'observed_at': '2026-11-07T13:00:00+00:00',
        'views': [{
            'id': 'notes', 'label': 'Saisie des notes', 'expected_heading': 'Notes',
            'observation_id': 'public-notes-01', 'visible_text': 'Notes · Classe',
            'controls': [{'selector': '[role="tab"][data-id="notes"]', 'role': 'tab',
                          'label': 'Notes', 'tag': 'div', 'read_only': True}],
            'navigation': [{'selector': '[role="tab"][data-id="notes"]',
                            'observation_id': 'public-notes-01', 'action': 'click'}],
        }],
    }


def proposal(observations):
    view = observations['views'][0]
    return {'routes': [{'id': view['id'], 'label': view['label'],
                        'observation_id': view['observation_id'],
                        'steps': copy.deepcopy(view['navigation']), 'explanation': 'Observed tab.'}],
            'limitations': ['No copy or marking scheme was opened.']}


def test_unknown_selector_or_url_never_activates_a_route(observations):
    candidate = proposal(observations)
    candidate['routes'][0]['steps'][0]['selector'] = '#invented'
    assert not codex_routes.validate_proposal(observations, candidate)['valid']
    candidate = proposal(observations)
    candidate['routes'][0]['url'] = 'https://invented/notes'
    assert not codex_routes.validate_proposal(observations, candidate)['valid']


def test_observed_control_without_observed_path_is_insufficient(observations):
    candidate = proposal(observations)
    observations['views'][0].pop('navigation')
    assert not codex_routes.validate_proposal(observations, candidate)['valid']


@pytest.mark.parametrize('change', [{'label': 'Enregistrer'}, {'read_only': False},
                                    {'type': 'submit'}, {'tag': 'input'}])
def test_write_or_input_control_is_rejected_even_when_captured(observations, change):
    observations['views'][0]['controls'][0].update(change)
    result = codex_routes.validate_proposal(observations, proposal(observations))
    assert not result['valid'] and result['routes'] == []


def test_only_public_demo_evidence_enters_codex(tmp_path, observations):
    observations['source_url'] = 'https://my-school.example/pronote/professeur.html'
    path = tmp_path / 'observations.json'
    path.write_text(json.dumps(observations))
    with pytest.raises(ValueError, match='public PRONOTE'):
        codex_routes.load_observations(path)


def test_real_cli_shape_and_trace_but_catalog_still_needs_python_validation(tmp_path, observations, monkeypatch):
    path = tmp_path / 'observations.json'
    path.write_text(json.dumps(observations))
    monkeypatch.setattr(codex_routes.shutil, 'which', lambda name: '/test/codex')
    captured = []

    def run(command, **kwargs):
        captured.append((command, kwargs))
        candidate_path = command[command.index('--output-last-message') + 1]
        from pathlib import Path
        Path(candidate_path).write_text(json.dumps(proposal(observations)))
        kwargs['stdout'].write('{"type":"turn.completed"}\n')
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(codex_routes.subprocess, 'run', run)
    report = codex_routes.establish(path)
    command, kwargs = captured[0]
    assert command[:4] == ['/test/codex', 'exec', '--json', '--sandbox']
    assert command[4] == 'read-only' and '--model' not in command
    assert '--output-schema' in command and '--ephemeral' in command
    assert kwargs['timeout'] == 180
    assert report['state'] == 'established' and report['runtime_verified'] is False
    route = report['catalog']['routes']['notes']
    assert route['steps'][0]['selector'] == observations['views'][0]['controls'][0]['selector']
    assert route['verification']['evidence_id'] == 'public-notes-01'
    assert len(route['verification']['snapshot_sha256']) == 64


def test_timeout_leaves_no_candidate_catalog(tmp_path, observations, monkeypatch):
    path = tmp_path / 'observations.json'
    path.write_text(json.dumps(observations))
    monkeypatch.setattr(codex_routes.shutil, 'which', lambda name: '/test/codex')

    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(codex_routes.subprocess, 'run', run)
    report = codex_routes.establish(path, timeout_seconds=1)
    assert report['state'] == 'failed' and 'catalog' not in report
    assert 'timeout' in report['errors'][0]


def selection_observations(observations):
    view = observations['views'][0]
    selector = '[role="combobox"][aria-label="Classe"]'
    view['controls'].append({'selector': selector, 'role': 'combobox', 'tag': 'div',
                             'label': 'Classe', 'read_only': True})
    view['selection_observations'] = [{'selector': selector, 'text': '3A', 'tag': 'div',
                                      'role': 'combobox', 'visible': True, 'method': 'rendered_text'}]
    view['expected_selections'] = [{'selector': selector, 'text': '3A'}]
    return view


def test_selection_postcondition_is_copied_only_from_captured_visible_text(observations):
    selection_observations(observations)
    result = codex_routes.validate_proposal(observations, proposal(observations))
    assert result['valid']
    catalog = codex_routes.build_catalog(observations, result['routes'])
    assert catalog['routes']['notes']['expected_selections'][0]['text'] == '3A'


@pytest.mark.parametrize('change', ['text', 'selector', 'hidden', 'input_value'])
def test_selection_postcondition_cannot_invent_text_or_read_an_input_value(observations, change):
    view = selection_observations(observations)
    if change == 'text':
        view['expected_selections'][0]['text'] = '3B'
    elif change == 'selector':
        view['expected_selections'][0]['selector'] = '#invented'
    elif change == 'hidden':
        view['selection_observations'][0]['visible'] = False
    else:
        view['selection_observations'][0]['method'] = 'input.value'
    result = codex_routes.validate_proposal(observations, proposal(observations))
    assert not result['valid'] and result['routes'] == []
