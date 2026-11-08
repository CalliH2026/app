"""Gladia dictation for a focused teacher grading form.

Only transcription and extraction happen here. The browser keeps the selected
student/evaluation and lets the teacher review the resulting grade before saving.
Gladia transport follows https://docs.gladia.io/chapters/pre-recorded-stt/quickstart.
"""
from pathlib import Path
import math
import re
from tempfile import TemporaryDirectory
import unicodedata

import httpx
from fastapi import File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from .integrations import transcribe


MAX_AUDIO_BYTES = 20 * 1024 * 1024
MAX_TRANSCRIPT_CHARS = 10_000
AUDIO_SUFFIXES = {'.wav', '.mp3', '.m4a', '.mp4', '.webm', '.ogg', '.opus', '.flac', '.aac'}
WORD_VALUES = {
    'zero': 0, 'un': 1, 'une': 1, 'deux': 2, 'trois': 3, 'quatre': 4,
    'cinq': 5, 'six': 6, 'sept': 7, 'huit': 8, 'neuf': 9, 'dix': 10,
    'onze': 11, 'douze': 12, 'treize': 13, 'quatorze': 14, 'quinze': 15,
    'seize': 16, 'vingt': 20, 'vingts': 20, 'trente': 30, 'quarante': 40,
    'cinquante': 50, 'soixante': 60, 'cent': 100, 'cents': 100,
}
NUMBER_WORD = '|'.join(sorted((*WORD_VALUES, 'zéro', 'moins', 'virgule', 'point', 'et'), key=len, reverse=True))
NUMBER = rf'(?:-?\d+(?:[.,]\d+)?|(?:{NUMBER_WORD})(?:[\s-]+(?:{NUMBER_WORD}))*)'
MARK = re.compile(rf'(?<![\w.,])(?P<score>{NUMBER})\s*(?:/|\bsur\b)\s*(?P<maximum>{NUMBER})(?!\w|[.,]\d)', re.I)
APPRECIATION = re.compile(
    r"\b(?:(?:ajoute|ajouter|mets|mettre|et)\s+)?(?:(?:comme|une|son)\s+|l[’'])?appr[eé]ciation\s*[:：,]?\s*(.*)$",
    re.I | re.S,
)


def _normal(text):
    return ''.join(char for char in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(char))


def _number(raw):
    text = _normal(raw).strip()
    if re.fullmatch(r'-?\d+(?:[.,]\d+)?', text):
        return float(text.replace(',', '.'))
    tokens = text.replace('-', ' ').split()
    negative = bool(tokens and tokens[0] == 'moins')
    if negative:
        tokens.pop(0)
    # A conjunction following the maximum belongs to the next instruction.
    while tokens and tokens[-1] == 'et':
        tokens.pop()
    decimal = next((index for index, token in enumerate(tokens) if token in ('virgule', 'point')), None)
    fractional = tokens[decimal + 1:] if decimal is not None else []
    if decimal is not None:
        tokens = tokens[:decimal]
        if not fractional:
            raise ValueError('La décimale dictée est incomplète.')
    if not tokens or any(token not in WORD_VALUES and token != 'et' for token in tokens):
        raise ValueError('Le nombre dicté n’est pas reconnu.')
    words = [token for token in tokens if token != 'et']
    # French scores and usual maxima, including soixante-dix/quatre-vingts.
    value = 0
    index = 0
    while index < len(words):
        word = words[index]
        if word == 'quatre' and index + 1 < len(words) and words[index + 1] in ('vingt', 'vingts'):
            value += 80
            index += 2
        elif word in ('cent', 'cents') and value and value < 10:
            value *= 100
            index += 1
        else:
            value += WORD_VALUES[word]
            index += 1
    if fractional:
        digits = []
        for token in fractional:
            if token not in WORD_VALUES or WORD_VALUES[token] > 9:
                raise ValueError('Dictez la décimale chiffre par chiffre, par exemple douze virgule cinq.')
            digits.append(str(WORD_VALUES[token]))
        value += float('0.' + ''.join(digits))
    return float(-value if negative else value)


def _target(text, mark):
    prefix, suffix = text[:mark.start()], text[mark.end():]
    match = re.search(r"\b(?:note|noter|[ée]value|[ée]valuer)\s+(?:l[’']élève\s+)?(.+?)(?=\s+(?:pour|au|avec|et)\b|[,;:]|$)", prefix, re.I)
    if not match:
        match = re.search(r"^(?:pour\s+)?([\wÀ-ÿ]+(?:\s+[\wÀ-ÿ]+){0,3})\s*[,;:]\s*(?:mets|mettez|donne|attribue|note)\b", prefix, re.I)
    if not match:
        match = re.search(r"\b(?:[àa]|pour)\s+(?!(?:le|la|l[’'])\b)(.+?)(?=\s+(?:pour|au|avec|et)\b|[.,;:]|$)", suffix, re.I)
    name = match.group(1).strip(' .,:;«»"') if match else None
    if name and (_normal(name) in {'de', 'la', 'une', 'lui', 'le', 'la note', 'une note de'} or len(name) > 100):
        name = None
    evaluation = re.search(r"\bpour\s+(?:(?:le|la|l[’'])\s*)?((?:devoir|contrôle|controle|évaluation|evaluation|exercice|travail)\b.*?)(?=\s+(?:et|mets|mettez|donne|attribue|note)\b|[.,;:]|$)", text, re.I)
    title = evaluation.group(1).strip() if evaluation else None
    if title and _normal(title) in {'devoir', 'controle', 'evaluation', 'exercice', 'travail'}:
        title = None
    return name, title


def parse_command(text):
    """Extract one explicit score, keeping transcript data out of instructions."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Aucune parole reconnue. Réessayez ou saisissez la note au clavier.')
    if len(text) > MAX_TRANSCRIPT_CHARS:
        raise ValueError('La dictée est trop longue. Dictez une note et une appréciation courtes.')
    appreciation_match = APPRECIATION.search(text)
    appreciation = appreciation_match.group(1).strip(' \t\n«»"') if appreciation_match else None
    instruction = text[:appreciation_match.start()] if appreciation_match else text
    marks = list(MARK.finditer(instruction))
    if len(marks) != 1:
        raise ValueError('Dictez une seule note avec son barème, par exemple « mets-lui douze sur vingt ».')
    match = marks[0]
    score, maximum = _number(match.group('score')), _number(match.group('maximum'))
    if not math.isfinite(score) or not math.isfinite(maximum) or maximum <= 0 or score < 0 or score > maximum:
        raise ValueError('La note doit être comprise entre zéro et le maximum, qui doit être positif.')
    if appreciation and len(appreciation) > 2000:
        raise ValueError('L’appréciation est limitée à 2 000 caractères.')
    name, title = _target(instruction, match)
    return {
        'score': int(score) if score.is_integer() else score,
        'maximum': int(maximum) if maximum.is_integer() else maximum,
        'appreciation': appreciation or None, 'student_name': name, 'evaluation_title': title,
    }


def install_routes(app):
    @app.post('/api/workspace/grading/transcribe')
    def grading_transcribe(audio: UploadFile = File(...)):
        suffix = Path(audio.filename or '').suffix.lower()
        content_type = (audio.content_type or '').split(';')[0].lower()
        if suffix not in AUDIO_SUFFIXES or (content_type and not (
            content_type.startswith('audio/') or content_type in ('video/mp4', 'video/webm', 'application/octet-stream')
        )):
            raise HTTPException(415, 'Choisissez un enregistrement audio WAV, MP3, M4A, MP4, WebM, OGG, Opus, FLAC ou AAC.')
        try:
            with TemporaryDirectory(prefix='pronote-grade-') as directory:
                path = Path(directory) / ('dictation' + suffix)
                total = 0
                with path.open('wb') as target:
                    while chunk := audio.file.read(64 * 1024):
                        total += len(chunk)
                        if total > MAX_AUDIO_BYTES:
                            raise HTTPException(413, 'L’enregistrement est limité à 20 Mo.')
                        target.write(chunk)
                if not total:
                    raise HTTPException(400, 'L’enregistrement audio est vide.')
                try:
                    transcription = transcribe(path)
                except RuntimeError as exc:
                    if str(exc).startswith('Clé manquante'):
                        raise HTTPException(503, 'Gladia n’est pas configuré. Ajoutez GLADIA_API_KEY côté serveur.') from exc
                    raise HTTPException(502, 'Gladia n’a pas pu transcrire cet enregistrement. Réessayez.') from exc
                except (httpx.HTTPError, TimeoutError, ValueError, KeyError) as exc:
                    raise HTTPException(502, 'Gladia n’a pas pu transcrire cet enregistrement. Réessayez.') from exc
            try:
                command = parse_command(transcription.get('text'))
            except ValueError as exc:
                raise HTTPException(422, {'message': str(exc), 'transcription': transcription}, headers={'Cache-Control': 'no-store'}) from exc
            return JSONResponse({'provider': 'Gladia', 'transcription': transcription, 'command': command}, headers={'Cache-Control': 'no-store'})
        finally:
            audio.file.close()
