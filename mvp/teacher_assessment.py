"""Freeze the teacher's current assessment as evidence for one preparation.

The original copy remains a source document. A teacher entry is a separate,
authoritative source for the selected evaluation and is included in both the
report and the rendered capsule, even when a generated answer omits it.
"""
from copy import deepcopy
from datetime import date as Date, datetime
import hashlib

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SOURCE_ID = 'teacher-assessment'


class TeacherAssessment(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    student_id: str = Field(min_length=1, max_length=100)
    evaluation_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=150)
    date: Date | None = None
    score: float = Field(ge=0, allow_inf_nan=False)
    maximum: float = Field(gt=0, allow_inf_nan=False)
    appreciation: str = Field(default='', max_length=2000)
    graded_at: datetime | None = None

    @field_validator('score', 'maximum', mode='before')
    @classmethod
    def reject_boolean_marks(cls, value):
        if isinstance(value, bool):
            raise ValueError('Une note doit être un nombre.')
        return value

    @model_validator(mode='after')
    def valid_mark(self):
        if self.score > self.maximum:
            raise ValueError('La note doit être comprise entre 0 et le maximum.')
        return self


def format_number(value):
    """Use French decimal punctuation without rounding ordinary grade values."""
    value = float(value)
    if value.is_integer() and abs(value) < 1e12:
        return str(int(value))
    return str(value).replace('.', ',')


def grade_label(assessment):
    value = TeacherAssessment.model_validate(assessment)
    return f'{format_number(value.score)}/{format_number(value.maximum)}'


def note_quote(assessment):
    return 'Note attribuée par le professeur : ' + grade_label(assessment) + '.'


def appreciation_quote(assessment):
    value = TeacherAssessment.model_validate(assessment)
    return f'Appréciation du professeur : « {value.appreciation} ».'


def assessment_document(assessment, student):
    value = TeacherAssessment.model_validate(assessment)
    if value.student_id != student.get('id'):
        raise ValueError('Cette évaluation ne concerne pas l’élève du dossier ouvert.')
    lines = [
        f'Évaluation renseignée par le professeur : « {value.title} ».',
        f'Élève : {student["name"]} · {student.get("class", "")}.',
    ]
    if value.date:
        lines.append('Date de l’évaluation : ' + value.date.isoformat() + '.')
    lines.append(note_quote(value))
    lines.append(appreciation_quote(value) if value.appreciation else 'Aucune appréciation n’a été saisie.')
    lines.append(
        'Cette saisie est l’évaluation actuelle du professeur pour le devoir indiqué. '
        'Les notes inscrites dans les pièces jointes documentent leurs exercices d’origine ; '
        'elles ne constituent pas un nouveau détail de cette note. Aucun critère n’a été recalculé.')
    text = '\n'.join(lines)
    return {
        'id': SOURCE_ID, 'type': 'school',
        'title': 'Évaluation du professeur · ' + value.title,
        'text': text, 'assessment': value.model_dump(mode='json'),
        'role': 'teacher_assessment',
        'source': {'kind': 'teacher_entry', 'label': 'Saisie du professeur', 'native_synced': False},
        'source_locator': 'teacher:' + value.student_id + '/' + value.evaluation_id,
        'content_hash': hashlib.sha256(text.encode()).hexdigest(),
    }


def bind_teacher_assessment(context, assessment):
    """Return an isolated snapshot; never edit the copy or the caller's records."""
    result = deepcopy(context)
    if assessment is None:
        return result
    document = assessment_document(assessment, result['student'])
    result['teacher_assessment'] = deepcopy(document['assessment'])
    result['documents'] = [item for item in result['documents'] if item['id'] != SOURCE_ID] + [document]
    return result


def _excerpt(text, limit):
    if len(text) <= limit:
        return text
    shortened = text[:max(0, limit - 1)].rsplit(' ', 1)[0]
    if len(shortened) < limit // 2:
        shortened = text[:max(0, limit - 1)]
    return shortened.rstrip() + '…'


def apply_teacher_assessment(dossier, documents):
    """Include exact current marks in report evidence and the third film scene.

    Generated pedagogical guidance in the other three scenes is preserved.
    Only the current-evaluation scene and summary are supplied deterministically
    so an old fixture note cannot override the teacher's new assessment.
    """
    result = deepcopy(dossier.model_dump() if isinstance(dossier, BaseModel) else dossier)
    document = next((item for item in documents if item['id'] == SOURCE_ID), None)
    if document is None:
        return result
    value = TeacherAssessment.model_validate(document['assessment'])
    current_mark = note_quote(value)
    current_appreciation = appreciation_quote(value)
    if current_mark not in document['text'] or (value.appreciation and current_appreciation not in document['text']):
        raise ValueError('L’évaluation du professeur ne correspond pas à sa pièce source.')
    if len(result.get('scenes', [])) != 4:
        raise ValueError('La capsule doit contenir quatre scènes.')

    evidence = [{
        'claim': f'Le professeur a attribué {grade_label(value)} à « {value.title} ».',
        'quote': current_mark, 'source_ids': [SOURCE_ID],
    }]
    if value.appreciation:
        evidence.append({
            'claim': 'L’appréciation du professeur guide les prochaines étapes.',
            'quote': current_appreciation, 'source_ids': [SOURCE_ID],
        })
    result['evidence'] = evidence + [item for item in result.get('evidence', [])
                                     if SOURCE_ID not in item.get('source_ids', [])]
    result['teacher_assessment'] = value.model_dump(mode='json')
    summary = f'Pour « {value.title} », le professeur a saisi {grade_label(value)}.'
    if value.appreciation:
        summary += ' Appréciation : ' + _excerpt(value.appreciation, 600)
    result['summary'] = summary

    body_start = value.title + ' · ' + grade_label(value)
    body = body_start
    if value.appreciation:
        body += '\n' + _excerpt(value.appreciation, 420 - len(body_start) - 1)
    narration = (
        f'Pour l’évaluation « {value.title} », le professeur a attribué '
        f'{format_number(value.score)} sur {format_number(value.maximum)}. ')
    scope = ' Cette note concerne cette évaluation. Les pièces jointes aident à préparer la suite du travail.'
    if value.appreciation:
        budget = 1500 - len(narration) - len(scope)
        prefix = 'Son appréciation : '
        if len(prefix) + len(value.appreciation) > budget:
            prefix = 'Voici un extrait de son appréciation : '
        narration += prefix + _excerpt(value.appreciation, budget - len(prefix))
    else:
        narration += 'Aucune appréciation n’a été saisie. '
    result['scenes'][2] = {
        'title': 'L’évaluation du professeur', 'body': body,
        'narration': narration + scope, 'source_ids': [SOURCE_ID],
    }
    return result
