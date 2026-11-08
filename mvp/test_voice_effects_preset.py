"""The teacher preset keeps the official starter's four effects and timing."""
from pathlib import Path

import yaml

from .voice_effects_config import config


def test_teacher_preset_is_a_simple_four_scene_official_template():
    folder = Path(__file__).parent / 'templates'
    template = yaml.safe_load((folder / 'demobro-starter.yaml').read_text())
    preset = yaml.safe_load((folder / 'professeur.yaml').read_text())
    assert len(preset) <= 5
    value = config('https://snapshot.example', presenter_id='consented-teacher-profile')
    scenario = value['scenarios'][0]
    steps = scenario['steps']
    original = template['scenarios'][0]['steps']
    assert len(steps) == 4
    assert [step['effects'] for step in steps] == [step['effects'] for step in original]
    assert [step['effects'][0]['type'] for step in steps] == ['glow', 'perspective_tilt', 'device_frame', 'fade_in']
    assert [step['wait'] for step in steps] == [4.0, 3.5, 3.5, 4.0]
    assert all(step['action'] == 'navigate' and 'locator' not in step for step in steps)
    assert 'selector' not in yaml.safe_dump(value)
    assert [step['url'] for step in steps] == ['https://snapshot.example' + path for path in preset['pages']]
    assert 65 <= sum(len(step['narration'].split()) for step in steps) <= 85
    assert value['voice']['engine'] == 'custom' and value['voice']['voice_id'] == 'consented-teacher-profile'
    assert scenario['avatar']['presenter_id'] == 'consented-teacher-profile'
    assert scenario['avatar']['position'] == 'bottom-left'
    assert scenario['subtitle'] == template['scenarios'][0]['subtitle']
    assert scenario['subtitle']['style'] == 'karaoke'
    assert value['languages']['default'] == 'fr'
