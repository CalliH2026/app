"""Prepare clearly fictional PDFs for an observed native PRONOTE import.

This creates files only. It never edits a PRONOTE database, simulates an import,
or registers the documents as native sources. The separate import step must be
observed before these files can enter the native evidence registry.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
from pathlib import Path, PureWindowsPath
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'data/native-demo-documents'
BOTTLE_OUTPUT = ROOT / 'data/pronote-demo-bottle/drive_c/H-Demo/Pieces'
CASE_ID = 'fanny-pythagore-demo'
FONT = ROOT / 'static/h-kit/fonts/PlusJakartaSans.ttf'
INK = colors.HexColor('#25202E')
MUTED = colors.HexColor('#726A7F')
PURPLE = colors.HexColor('#5A04BC')
PALE = colors.HexColor('#F5F0FB')
LINE = colors.HexColor('#E6DFEC')
PAGE_W, PAGE_H = A4
LEFT, RIGHT = 48, PAGE_W - 48
WIDTH = RIGHT - LEFT

CRITERIA = [
    ('Théorème et justification', 'Nommer le théorème de Pythagore et rappeler que le triangle ABC est rectangle en A.', 0),
    ('Hypoténuse', 'Identifier explicitement BC comme l’hypoténuse, opposée à l’angle droit en A.', 0),
    ('Égalité', 'Écrire BC² = AB² + AC² ou une substitution correcte : BC² = 3² + 4².', 1),
    ('Calcul', 'Calculer correctement le carré de la longueur : BC² = 25.', 1),
    ('Racine carrée et unité', 'Déduire la longueur correcte et son unité : BC = 5 cm.', 1),
    ('Conclusion rédigée', 'Conclure par une phrase : « La longueur BC est donc égale à 5 cm. »', 0),
]

PARENT_AUDIO_TEXT = (
    'Bonjour. Merci de nous recevoir pour faire le point sur le travail de Fanny. '
    'Nous avons regardé ensemble sa copie de mathématiques. Dans l’exercice du triangle, '
    'elle trouve bien cinq centimètres, et ce résultat semble juste. Pourtant, elle obtient '
    'trois points sur six. Pourquoi perd-elle ces points alors que son calcul est correct ? '
    'Nous aimerions comprendre ce qui est attendu pour justifier le théorème, reconnaître '
    'l’hypoténuse et rédiger une conclusion. Comment pouvons-nous lui expliquer les critères '
    'sans la décourager ? Et quelle petite méthode ou quel exercice pourrait l’aider à '
    'progresser avant le prochain contrôle ? Merci beaucoup.'
)

AUDIO_NOTICE = (
    'Vocal de test synthétisé localement avec la voix Thomas : il ne provient pas '
    'd’un parent réel et n’est pas importé dans PRONOTE.'
)


def _paragraph(canvas, text, x, top, width=WIDTH, size=10, color=INK, leading=None):
    style = ParagraphStyle('body', fontName='Jakarta', fontSize=size,
                           leading=leading or size * 1.6, textColor=color,
                           alignment=TA_LEFT, spaceAfter=0)
    paragraph = Paragraph(escape(text).replace('\n', '<br/>'), style)
    _, height = paragraph.wrap(width, PAGE_H)
    paragraph.drawOn(canvas, x, top - height)
    return top - height


def _label(canvas, text, x, y, color=MUTED, size=8):
    canvas.setFont('Jakarta', size)
    canvas.setFillColor(color)
    canvas.drawString(x, y, text)


def _heading(canvas, text, y):
    _label(canvas, text, LEFT, y, PURPLE, 11)
    return y - 18


def _page(path, title, document_id, subtitle):
    canvas = Canvas(str(path), pagesize=A4, invariant=1, pageCompression=1)
    canvas.setTitle(title)
    canvas.setAuthor('Calli - dossier fictif de démonstration')
    canvas.setSubject('Données fictives - préparation à un import PRONOTE vérifié')
    _label(canvas, 'PRONOTE / MATHÉMATIQUES', LEFT, PAGE_H - 49, PURPLE, 9)
    canvas.setFillColor(PALE)
    canvas.roundRect(RIGHT - 189, PAGE_H - 62, 189, 24, 6, fill=1, stroke=0)
    _label(canvas, 'DÉMONSTRATION - DONNÉES FICTIVES', RIGHT - 180, PAGE_H - 53, PURPLE, 7)
    canvas.setStrokeColor(LINE)
    canvas.line(LEFT, PAGE_H - 82, RIGHT, PAGE_H - 82)
    _label(canvas, title, LEFT, PAGE_H - 120, INK, 23)
    _label(canvas, subtitle, LEFT, PAGE_H - 145, MUTED, 9)
    canvas.setStrokeColor(LINE)
    canvas.line(LEFT, 70, RIGHT, 70)
    _label(canvas, 'Dossier de test : ' + CASE_ID, LEFT, 54, MUTED, 7)
    _label(canvas, 'Document : ' + document_id, LEFT, 41, MUTED, 7)
    _label(canvas, 'Pièce fictive de démonstration - ne concerne aucun élève réel.', LEFT, 28, MUTED, 7)
    _label(canvas, '1 / 1', RIGHT - 22, 42, MUTED, 7)
    return canvas


def _triangle(canvas, x, y, scale=1):
    # AB = 3 and AC = 4: the drawing uses a consistent 3:4 ratio.
    height, width = 75 * scale, 100 * scale
    canvas.setLineWidth(1.2)
    canvas.setStrokeColor(INK)
    path = canvas.beginPath()
    path.moveTo(x, y)
    path.lineTo(x, y + height)
    path.lineTo(x + width, y)
    path.close()
    canvas.drawPath(path)
    canvas.setStrokeColor(PURPLE)
    canvas.rect(x, y, 9 * scale, 9 * scale, fill=0, stroke=1)
    _label(canvas, 'A', x - 13, y - 14, INK, 10)
    _label(canvas, 'B', x - 13, y + height + 4, INK, 10)
    _label(canvas, 'C', x + width + 5, y - 9, INK, 10)
    _label(canvas, '3 cm', x - 38, y + height / 2, MUTED, 9)
    _label(canvas, '4 cm', x + width / 2 - 9, y - 20, MUTED, 9)


def _copy(path):
    document_id = CASE_ID + '-copy'
    canvas = _page(path, 'Copie de Fanny BERNARD', document_id,
                   'Classe 3A | Exercice 2 | Théorème de Pythagore')
    top = _heading(canvas, 'EXERCICE 2 - CALCULER UNE LONGUEUR', 665)
    _paragraph(canvas, 'ABC est un triangle rectangle en A. AB = 3 cm et AC = 4 cm. Calculer BC et justifier le raisonnement.', LEFT, top)
    _triangle(canvas, LEFT + 42, 518)
    _paragraph(canvas, 'Note de cet exercice', LEFT + 245, 592, 220, 9, MUTED)
    _label(canvas, '3 / 6', LEFT + 245, 545, PURPLE, 32)
    _paragraph(canvas, 'Aucune note globale du contrôle n’est fournie.', LEFT + 245, 526, 220, 8.5, MUTED)
    canvas.setFillColor(PALE)
    canvas.roundRect(LEFT, 426, WIDTH, 61, 8, fill=1, stroke=0)
    _label(canvas, 'RÉPONSE ÉCRITE DE L’ÉLÈVE', LEFT + 16, 468, MUTED, 8)
    _label(canvas, 'BC² = 3² + 4² = 25 ; BC = 5 cm', LEFT + 16, 441, INK, 15)
    _heading(canvas, 'ANNOTATION DU PROFESSEUR', 403)
    _paragraph(canvas, 'Calcul exact. Préciser pourquoi le théorème s’applique, identifier l’hypoténuse et rédiger la conclusion.', LEFT, 384, size=10)
    _heading(canvas, 'ATTRIBUTION DES POINTS', 327)
    rows = [['Critère', 'Points obtenus']]
    rows += [[title, f'{earned} / 1'] for title, _, earned in CRITERIA]
    rows += [['TOTAL DE L’EXERCICE', '3 / 6']]
    table = Table(rows, colWidths=[WIDTH - 112, 112], rowHeights=[25] + [23] * 6 + [27])
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Jakarta'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), INK),
        ('BACKGROUND', (0, 0), (-1, 0), PALE),
        ('BACKGROUND', (0, -1), (-1, -1), PALE),
        ('TEXTCOLOR', (0, -1), (-1, -1), PURPLE),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -2), .4, LINE),
    ]))
    _, height = table.wrap(WIDTH, 300)
    table.drawOn(canvas, LEFT, 307 - height)
    canvas.save()
    return document_id


def _rubric(path):
    document_id = CASE_ID + '-rubric'
    canvas = _page(path, 'Barème de l’exercice 2', document_id,
                   'Classe 3A | Théorème de Pythagore | Total : 6 points')
    _paragraph(canvas, 'Le résultat numérique est évalué avec la justification du raisonnement. Les six critères ci-dessous valent chacun un point.', LEFT, 666, size=10.5)
    top = 600
    for index, (title, description, _) in enumerate(CRITERIA, 1):
        canvas.setFillColor(PALE)
        canvas.roundRect(LEFT, top - 60, WIDTH, 64, 7, fill=1, stroke=0)
        _label(canvas, f'{index:02}  {title}', LEFT + 14, top - 16, PURPLE, 10)
        _label(canvas, '1 POINT', RIGHT - 56, top - 16, PURPLE, 8)
        _paragraph(canvas, description, LEFT + 14, top - 27, WIDTH - 28, 9, INK, 13)
        top -= 76
    _paragraph(canvas, 'Attribution prévue pour la copie fictive de Fanny : égalité 1/1, calcul 1/1, racine carrée et unité 1/1. Les trois autres critères ne sont pas explicités dans sa réponse : 0/1 chacun. Total : 3/6.', LEFT, 129, size=8.5, leading=13)
    canvas.save()
    return document_id


def _instructions(path):
    document_id = CASE_ID + '-instructions'
    canvas = _page(path, 'Consigne de l’exercice 2', document_id,
                   'Classe 3A | Mathématiques | Théorème de Pythagore')
    _heading(canvas, 'ÉNONCÉ', 665)
    _paragraph(canvas, 'ABC est un triangle rectangle en A. AB = 3 cm et AC = 4 cm. Calculer la longueur BC.', LEFT, 642, size=12)
    _triangle(canvas, LEFT + 58, 462, 1.5)
    _paragraph(canvas, 'Figure indicative\nAB = 3 cm\nAC = 4 cm\nLongueur BC à déterminer', LEFT + 275, 564, 200, 11, MUTED, 21)
    _heading(canvas, 'ATTENDUS DE RÉDACTION', 390)
    lines = [
        '1. Justifier le choix du théorème en rappelant la nature du triangle.',
        '2. Identifier l’hypoténuse.',
        '3. Écrire l’égalité et détailler le calcul.',
        '4. Donner la longueur obtenue avec son unité.',
        '5. Conclure par une phrase.',
    ]
    _paragraph(canvas, '\n'.join(lines), LEFT, 365, size=11, leading=23)
    canvas.setFillColor(PALE)
    canvas.roundRect(LEFT, 162, WIDTH, 53, 8, fill=1, stroke=0)
    _paragraph(canvas, 'L’exercice est noté sur 6 points. Le barème détaillé est fourni dans une pièce séparée.', LEFT + 16, 200, WIDTH - 32, 10)
    canvas.save()
    return document_id


def prepare():
    if not FONT.is_file():
        raise FileNotFoundError('Police locale Plus Jakarta Sans introuvable.')
    pdfmetrics.registerFont(TTFont('Jakarta', str(FONT)))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    BOTTLE_OUTPUT.mkdir(parents=True, exist_ok=True)
    specifications = [
        ('Copy_Fanny_Pythagore.pdf', 'copy', _copy),
        ('Bareme_Pythagore.pdf', 'rubric', _rubric),
        ('Consigne_Pythagore.pdf', 'instructions', _instructions),
    ]
    sources = []
    for filename, role, author in specifications:
        path = OUTPUT / filename
        identifier = author(path)
        destination = BOTTLE_OUTPUT / filename
        shutil.copy2(path, destination)
        sources.append({'id': identifier, 'role': role, 'path': str(path),
                        'bottle_path': str(destination), 'windows_import_path': str(PureWindowsPath('C:/H-Demo/Pieces') / filename),
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'provenance': {'kind': 'prepared_demo_document', 'imported_into_native': False}})
    manifest = {'state': 'prepared_only', 'case_id': CASE_ID,
                'student': {'name': 'BERNARD Fanny', 'class': '3A', 'fictional': True},
                'native_import_verified': False, 'sources': sources,
                'limitations': ['Ces fichiers ne sont pas encore des pièces natives PRONOTE.',
                                'L’import et l’ouverture devront être observés dans le vrai client avant tout enregistrement comme sources natives.']}
    previous = OUTPUT / 'manifest.json'
    if previous.is_file():
        old = json.loads(previous.read_text())
        audio = old.get('parent_audio') if old.get('case_id') == CASE_ID else None
        if audio and Path(audio.get('path', '')).is_file():
            raw = Path(audio['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest() == audio.get('sha256'):
                manifest['parent_audio'] = audio
                manifest['limitations'].append(AUDIO_NOTICE)
    (OUTPUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def prepare_audio():
    """Add an external test vocal without regenerating PDFs or importing it."""
    manifest_path = OUTPUT / 'manifest.json'
    if not manifest_path.is_file():
        raise RuntimeError('Préparer les PDF avant de générer le vocal avec --audio.')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('case_id') != CASE_ID or manifest.get('state') != 'prepared_only':
        raise ValueError('Le vocal doit compléter le seul dossier de test préparé de Fanny.')
    if not Path('/usr/bin/say').is_file() or not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('La voix macOS say Thomas, FFmpeg et FFprobe sont nécessaires.')
    for source in manifest.get('sources', []):
        path = Path(source['path'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Une pièce PDF a changé depuis sa préparation ; aucun vocal ajouté.')
    script = OUTPUT / 'Question_parents_Fanny.txt'
    script.write_text(PARENT_AUDIO_TEXT + '\n')
    intermediate = OUTPUT / '.Question_parents_Fanny.aiff'
    pending = OUTPUT / '.Question_parents_Fanny.wav'
    destination = OUTPUT / 'Question_parents_Fanny.wav'
    try:
        subprocess.run(['/usr/bin/say', '-v', 'Thomas', '-r', '155',
                        '-f', str(script), '-o', str(intermediate)],
                       check=True, capture_output=True, timeout=120)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(intermediate),
                        '-map_metadata', '-1', '-ar', '16000', '-ac', '1',
                        '-c:a', 'pcm_s16le', str(pending)],
                       check=True, capture_output=True, timeout=60)
        media = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries',
            'format=duration:stream=codec_name,sample_rate,channels,bits_per_sample',
            '-of', 'json', str(pending)], text=True, timeout=20))
        duration = float(media['format']['duration'])
        streams = media.get('streams', [])
        if not 30 <= duration <= 60 or len(streams) != 1:
            raise ValueError('Le vocal de test doit durer entre 30 et 60 secondes.')
        stream = streams[0]
        if stream.get('codec_name') != 'pcm_s16le' or str(stream.get('sample_rate')) != '16000' or stream.get('channels') != 1:
            raise ValueError('Le vocal de test doit être en WAV PCM 16 bits, 16 kHz, mono.')
        pending.replace(destination)
    finally:
        intermediate.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)
    prepared_at = datetime.now(timezone.utc).isoformat()
    manifest['parent_audio'] = {
        'path': str(destination),
        'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        'duration_seconds': round(duration, 3),
        'source_text_path': str(script),
        'synthesis': {'engine': 'macOS say', 'voice': 'Thomas', 'language': 'fr_FR',
                      'words_per_minute': 155, 'synthetic': True},
        'format': {'container': 'wav', 'codec': stream['codec_name'],
                   'sample_rate': int(stream['sample_rate']), 'channels': stream['channels'],
                   'bits_per_sample': stream['bits_per_sample']},
        'provenance': {'kind': 'attached_test_dossier', 'locator': str(destination),
                       'prepared_at': prepared_at, 'imported_into_native': False},
    }
    manifest['native_import_verified'] = False
    if AUDIO_NOTICE not in manifest.setdefault('limitations', []):
        manifest['limitations'].append(AUDIO_NOTICE)
    temporary = manifest_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    temporary.replace(manifest_path)
    validation_path = OUTPUT / 'validation.json'
    validation = json.loads(validation_path.read_text()) if validation_path.is_file() else {}
    validation['parent_audio'] = {
        'state': 'codec_duration_and_hash_verified', 'duration_seconds': round(duration, 3),
        'sha256': manifest['parent_audio']['sha256'], 'format': manifest['parent_audio']['format'],
        'synthetic_voice': True, 'native_import_verified': False,
    }
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', action='store_true',
                        help='Ajouter seulement le vocal de test Fanny, sans régénérer les PDF.')
    arguments = parser.parse_args()
    print(json.dumps(prepare_audio() if arguments.audio else prepare(), ensure_ascii=False, indent=2))
