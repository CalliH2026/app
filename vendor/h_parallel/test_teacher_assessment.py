"""Current teacher grading reaches evidence and film without rewriting a copy."""
from copy import deepcopy
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from .teacher_assessment import (
    SOURCE_ID, TeacherAssessment, apply_teacher_assessment,
    assessment_document, bind_teacher_assessment, grade_label,
)


@pytest.fixture
def context():
    return json.loads((Path(__file__).parent / 'fixtures/alex.json').read_text())


@pytest.fixture
def assessment():
    return {
        'student_id': 'alex', 'evaluation_id': 'source-alex',
        'title': 'Devoir de mathématiques', 'date': '2026-11-07',
        'score': 12, 'maximum': 20,
        'appreciation': 'Calcul maîtrisé. Justifie le théorème et soigne la conclusion.',
        'graded_at': '2026-11-07T17:00:00+01:00',
    }


@pytest.fixture
def dossier():
    return {
        'question': 'Pourquoi ces points perdus ?', 'intent': 'points',
        'summary': 'Trois points manquants sur six.',
        'evidence': [
            {'claim': 'Le calcul est exact.', 'quote': 'BC = 5 cm', 'source_ids': ['copie']},
            {'claim': 'La rédaction est demandée.', 'quote': 'Justifier', 'source_ids': ['consigne']},
        ],
        'unknowns': ['La rédaction a-t-elle été travaillée en classe ?'],
        'scenes': [
            {'title': 'Question', 'body': 'Pourquoi ?', 'narration': 'La question des parents.', 'source_ids': ['audio']},
            {'title': 'Barème', 'body': 'Les critères.', 'narration': 'Les critères de l’exercice.', 'source_ids': ['bareme']},
            {'title': 'Ancienne note : 3/6', 'body': '3/6', 'narration': 'La note est trois sur six.', 'source_ids': ['copie']},
            {'title': 'Progresser', 'body': 'Rédiger.', 'narration': 'Un entraînement à la rédaction.', 'source_ids': ['methode']},
        ],
    }


@pytest.mark.parametrize('field,value', [
    ('score', -1), ('score', 20.01), ('score', float('nan')),
    ('score', float('inf')), ('score', True),
    ('maximum', 0), ('maximum', -2), ('maximum', float('inf')),
    ('maximum', float('nan')), ('maximum', False),
    ('title', '  '), ('title', 'x' * 151),
    ('student_id', ''), ('evaluation_id', ''),
    ('appreciation', 'x' * 2001), ('date', 'not-a-date'),
])
def test_invalid_teacher_assessment_is_rejected(assessment, field, value):
    with pytest.raises(ValidationError):
        TeacherAssessment.model_validate({**assessment, field: value})


def test_teacher_assessment_rejects_unexpected_fields(assessment):
    with pytest.raises(ValidationError):
        TeacherAssessment.model_validate({**assessment, 'source_text': 'overwrite copy'})


@pytest.mark.parametrize('score,maximum,label', [(0, 20, '0/20'), (12.5, 20, '12,5/20'), (6, 6, '6/6')])
def test_zero_decimal_and_full_marks_are_preserved(assessment, score, maximum, label):
    value = TeacherAssessment.model_validate({**assessment, 'score': score, 'maximum': maximum})
    assert value.score == score
    assert value.maximum == maximum
    assert grade_label(value) == label


def test_binding_freezes_current_grade_and_preserves_original_sources(context, assessment):
    original = deepcopy(context)
    frozen = bind_teacher_assessment(context, assessment)
    assert context == original
    assert frozen['documents'][:-1] == original['documents']
    assert frozen['teacher_assessment']['score'] == 12
    document = frozen['documents'][-1]
    assert document['id'] == SOURCE_ID
    assert document['assessment'] == frozen['teacher_assessment']
    assert 'Note attribuée par le professeur : 12/20.' in document['text']
    assert assessment['appreciation'] in document['text']
    assert document['source']['native_synced'] is False
    assessment['score'] = 18
    context['documents'][0]['text'] = 'Concurrent source edit'
    assert frozen['teacher_assessment']['score'] == 12
    assert frozen['documents'][0] == original['documents'][0]
    rebound = bind_teacher_assessment(frozen, {**assessment, 'score': 15})
    assert len([item for item in rebound['documents'] if item['id'] == SOURCE_ID]) == 1
    assert rebound['teacher_assessment']['score'] == 15
    assert frozen['teacher_assessment']['score'] == 12


def test_an_assessment_cannot_be_bound_to_another_students_copy(context, assessment):
    with pytest.raises(ValueError, match='élève du dossier'):
        assessment_document({**assessment, 'student_id': 'lea'}, context['student'])


def test_overlay_uses_current_grade_and_appreciation_in_report_and_capsule(context, assessment, dossier):
    frozen = bind_teacher_assessment(context, assessment)
    original = deepcopy(dossier)
    result = apply_teacher_assessment(dossier, frozen['documents'])
    assert dossier == original
    assert result['teacher_assessment']['score'] == 12
    assert result['teacher_assessment']['appreciation'] == assessment['appreciation']
    assert '12/20' in result['summary']
    assert assessment['appreciation'] in result['summary']
    assert 'Trois points manquants' not in result['summary']
    scene = result['scenes'][2]
    assert '12/20' in scene['body']
    assert '12 sur 20' in scene['narration']
    assert assessment['appreciation'] in scene['narration']
    assert 'trois sur six' not in scene['narration']
    assert scene['source_ids'] == [SOURCE_ID]
    for index in (0, 1, 3):
        assert result['scenes'][index] == original['scenes'][index]
    assert len(result['scenes']) == 4
    assert len(result['evidence']) >= 2
    teacher_document = frozen['documents'][-1]
    teacher_evidence = [item for item in result['evidence'] if SOURCE_ID in item['source_ids']]
    assert len(teacher_evidence) == 2
    assert all(item['quote'] in teacher_document['text'] for item in teacher_evidence)
    assert apply_teacher_assessment(result, frozen['documents']) == result


def test_each_new_mark_or_appreciation_changes_the_rendered_script(context, assessment, dossier):
    original = apply_teacher_assessment(dossier, bind_teacher_assessment(context, assessment)['documents'])
    changed = {**assessment, 'score': 15.5, 'appreciation': 'Bonne progression ; poursuivre la rédaction.'}
    result = apply_teacher_assessment(dossier, bind_teacher_assessment(context, changed)['documents'])
    assert result['summary'] != original['summary']
    assert '15,5/20' in result['summary']
    assert '15,5 sur 20' in result['scenes'][2]['narration']
    assert changed['appreciation'] in result['scenes'][2]['narration']
    assert assessment['appreciation'] not in result['scenes'][2]['narration']


def test_long_appreciation_is_complete_in_evidence_and_bounded_in_film(context, assessment, dossier):
    appreciation = ('Préciser les hypothèses et expliquer le choix du théorème. ' * 40)[:2000]
    changed = {**assessment, 'appreciation': appreciation, 'title': 'D' * 150}
    frozen = bind_teacher_assessment(context, changed)
    result = apply_teacher_assessment(dossier, frozen['documents'])
    assert result['teacher_assessment']['appreciation'] == appreciation.strip()
    assert appreciation.strip() in result['evidence'][1]['quote']
    assert len(result['scenes'][2]['body']) <= 420
    assert len(result['scenes'][2]['narration']) <= 1500
    assert 'extrait' in result['scenes'][2]['narration']
    assert result['scenes'][2]['body'].endswith('…')
    assert apply_teacher_assessment(result, frozen['documents']) == result


def test_empty_appreciation_and_no_grade_are_explicit(context, assessment, dossier):
    original = deepcopy(dossier)
    assert bind_teacher_assessment(context, None) == context
    assert apply_teacher_assessment(dossier, context['documents']) == original
    frozen = bind_teacher_assessment(context, {**assessment, 'appreciation': ''})
    result = apply_teacher_assessment(dossier, frozen['documents'])
    assert result['teacher_assessment']['appreciation'] == ''
    assert 'Aucune appréciation' in result['scenes'][2]['narration']
    assert len([item for item in result['evidence'] if SOURCE_ID in item['source_ids']]) == 1


def test_mismatched_teacher_source_never_reaches_capsule(context, assessment, dossier):
    frozen = bind_teacher_assessment(context, assessment)
    frozen['documents'][-1]['assessment']['score'] = 18
    with pytest.raises(ValueError, match='pièce source'):
        apply_teacher_assessment(dossier, frozen['documents'])
