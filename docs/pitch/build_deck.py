"""Build docs/pitch/calli-pitch-en.pptx from repository captures; numbers come from committed sources.

Usage (from the repository root): pip install python-pptx==1.0.2 && python docs/pitch/build_deck.py
Then: soffice --headless --convert-to pdf --outdir docs/pitch docs/pitch/calli-pitch-en.pptx
"""
import hashlib
import json
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/pitch'
FONT = 'Plus Jakarta Sans'
INK, MUTED, LINE, PAPER = RGBColor(0x23, 0x22, 0x2a), RGBColor(0x4a, 0x4a, 0x58), RGBColor(0xe2, 0xdf, 0xe8), RGBColor(0xf8, 0xf7, 0xfa)
GREEN, BLUE, GREY = RGBColor(0x1e, 0x7a, 0x52), RGBColor(0x1a, 0x6b, 0xbf), RGBColor(0xb8, 0xb4, 0xc2)
TIME = json.loads((ROOT / 'video/inserts/calli-time-estimate/model.json').read_text(encoding='utf-8'))
BASE = next(s for s in TIME['scenarios'] if s['typing_characters_per_minute'] == 225)
NATIONAL = json.loads((ROOT / 'video/calli-v11/national-scenario.json').read_text())

IMG = {
    'logo': 'video/calli-presentation/evidence/calli-logo-transparent.png',
    'today': 'video/explainer/public/calli-presentation/capture/np-today-2c1f5a4.png',
    'pronote': 'video/explainer/public/calli-presentation/arch/pronote-desktop-take2-t4.5.png',
    'graph': 'video/calli-orchestration/stills/graph-2475.png',
    'teacher': 'video/explainer/public/calli-presentation/capture/np-appreciations-lucas-2c1f5a4.png',
    'student': 'video/calli-v10/evidence/exercise/wrong.png',
    'parent': 'video/calli-v10/evidence/family/family.png',
}
used = {}


def text(slide, x, y, w, h, runs, size=16, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.1):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap, tf.vertical_anchor = True, anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, line in enumerate(runs if isinstance(runs, list) else [runs]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment, p.line_spacing = align, spacing
        single = isinstance(line, tuple) and len(line) == 2 and isinstance(line[1], dict)
        parts = (line,) if single or not isinstance(line, tuple) else line
        for part in parts:
            r = p.add_run()
            content, kw = (part, {}) if isinstance(part, str) else part
            r.text = content
            f = r.font
            f.name, f.size, f.bold = FONT, Pt(kw.get('size', size)), kw.get('bold', bold)
            f.color.rgb = kw.get('color', color)
            if kw.get('link'):
                r.hyperlink.address = kw['link']
    return box


def picture(slide, key, x, y, w, h, border=True):
    path = ROOT / IMG[key]
    used[key] = path
    iw, ih = Image.open(path).size
    scale = min(w / iw, h / ih)
    pw, ph = iw * scale, ih * scale
    left, top = x + (w - pw) / 2, y + (h - ph) / 2
    pic = slide.shapes.add_picture(str(path), Inches(left), Inches(top), Inches(pw), Inches(ph))
    if border:
        pic.line.color.rgb, pic.line.width = LINE, Pt(1)
    return pic


def box(slide, x, y, w, h, fill=PAPER, line=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = fill
    s.line.color.rgb = line; s.line.width = Pt(1)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.08
    s.shadow.inherit = False
    from pptx.oxml.ns import qn
    sp = s._element.spPr
    if sp.find(qn('a:effectLst')) is None:
        sp.append(sp.makeelement(qn('a:effectLst'), {}))
    s.text_frame.text = ''
    return s


def slide_base(prs, title, kicker, notes, number):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    text(s, 0.6, 0.42, 9.5, 0.3, kicker.upper(), size=11, color=MUTED, bold=True)
    text(s, 0.6, 0.72, 12.1, 1.2, title, size=32, bold=True, spacing=1.0)
    s.shapes.add_picture(str(ROOT / IMG['logo']), Inches(11.75), Inches(6.98), height=Inches(0.26))
    used['logo'] = ROOT / IMG['logo']
    text(s, 0.6, 7.02, 6, 0.25, f'{number}', size=10, color=MUTED)
    s.notes_slide.notes_text_frame.text = notes
    return s


def caption(slide, line, y=6.55):
    text(slide, 0.6, y, 11.0, 0.35, line, size=11, color=MUTED)


def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    notes = []

    def add(title, kicker, note, number):
        notes.append((number, title, note))
        return slide_base(prs, title, kicker, note, number)

    # 1
    s = add('An assistant that works alongside you.', 'Calli',
            'Calli uses the context of the current task to prepare useful work in parallel, then combines functions and computer use '
            'to carry out an explicit request in existing software. Education is the first demonstrated application; New Pronote is '
            'its role-specific interface. Observation currently covers registered document openings inside Calli, not the whole desktop. '
            'Real screenshot: New Pronote Today, commit 2c1f5a4.', 1)
    text(s, 0.6, 2.0, 4.6, 3.6, ['Observe context.', 'Prepare useful work in parallel.', 'Act through tools and computer use.', '',
                                 'First demonstrated application: education, with New Pronote.'],
         size=18, color=MUTED, spacing=1.2)
    picture(s, 'today', 5.5, 1.95, 7.25, 4.35)
    caption(s, 'One mechanism, a concrete application: the school workspace. Observation is scoped to Calli.')

    # 2
    s = add('Observe. Prepare. Act.', 'How Calli works',
            'A registered document opening inside Calli provides context. A preparation starts against a frozen case and validated sources '
            'while the user continues working. Independent school-trip collectors can run concurrently when H requests them. '
            'On explicit dictation, the native writer uses Holo and bounded functions to operate PRONOTE. These are separate flows: '
            'opening a document does not silently write a comment. Python owns the queue, checks and journal. '
            'The product demonstrates this mechanism in education; it does not claim universal desktop observation.', 2)
    stages = [('Observe', 'A document opens inside Calli.', 'Selected case and sources', BLUE),
              ('Prepare', 'Useful work starts beside you.', 'Sourced help and parallel tools', GREEN),
              ('Act', 'Carry out your explicit request.', 'Functions + Holo computer use', BLUE)]
    for i, (name, detail, sub, color) in enumerate(stages):
        x = 0.6 + i * 4.1
        text(s, x, 2.15, 3.6, 0.55, name, size=25, bold=True, color=color)
        text(s, x, 2.95, 3.6, 1.0, detail, size=19, spacing=1.2)
        text(s, x, 4.15, 3.6, 0.9, sub, size=15, color=MUTED)
    box(s, 0.6, 5.3, 12.1, 0.8, fill=PAPER)
    text(s, 0.85, 5.47, 11.6, 0.5, 'Context-bound jobs · one native item at a time · read-back comparison · STOP',
         size=15, color=MUTED)
    caption(s, 'Observation inside Calli; concurrent outing collectors; explicit native writes. docs/calli-system.md')

    # 3
    s = add('A dictated comment lands in real PRONOTE, then is read back.', 'Native writing',
            'Flow of the recorded run: the teacher dictates; Gladia transcribes; Python checks pupil, course, text and STOP; '
            'Holo (H computer use) takes one item through next_item, navigates, types, saves, reads the cell back and calls report_result; '
            'Python compares and journals. Queue to verified: 25.57 s for one recorded item (docs/calli-api-and-architecture.md). '
            'The recorded pupil is Lucas Bernard from the native trial roster. One item is not a reliability study.', 3)
    steps = [('Gladia', 'speech to text'), ('Python', 'pupil, course, text, STOP'), ('Holo 4', 'navigate, type, save'), ('Verify', 'Holo reads; Python compares and journals')]
    for i, (name, sub) in enumerate(steps):
        y = 2.0 + i * 1.05
        box(s, 0.6, y, 4.3, 0.85, fill=RGBColor(0xff, 0xff, 0xff))
        text(s, 0.85, y + 0.12, 3.9, 0.35, name, size=17, bold=True, color=GREEN if name == 'Verify' else INK)
        text(s, 0.85, y + 0.47, 3.9, 0.3, sub, size=13, color=MUTED)
    picture(s, 'pronote', 5.3, 1.95, 7.45, 4.4)
    caption(s, 'Recorded run on the real PRONOTE desktop (Windows trial build). Queue → verified comment: 25.57 s, one item.')

    # 4
    s = add('Function calling does the structured work, in parallel.', 'H function calling',
            'Structured work runs through tools, not pixels: transcription (Gladia), source search (Linkup), validation against sources '
            '(H managed agent, 97.31 s, session e1f16a50). For a school outing, Holo started three collectors concurrently: route, museum and class roster '
            '(run 23025b24ce29, partial draft in 90.22 s). Calendar and payment are separate steps; payment is a simulation and neither is part of this concurrent trace.', 4)
    for i, (name, sub) in enumerate([('Read & transcribe', 'Gladia'), ('Search sources', 'Linkup'), ('Validate', 'H managed agent · 97.31 s')]):
        y = 2.0 + i * 1.0
        text(s, 0.6, y, 3.8, 0.35, name, size=17, bold=True)
        text(s, 0.6, y + 0.38, 3.8, 0.3, sub, size=13, color=MUTED)
    text(s, 0.6, 5.05, 3.9, 1.2, [('3 collectors', {'bold': True, 'color': BLUE, 'size': 20}), 'ran concurrently for the outing draft'], size=14, color=MUTED)
    picture(s, 'graph', 4.7, 1.95, 8.05, 4.5)
    caption(s, 'Outing run 23025b24ce29: partial draft, 90.22 s, no booking or payment. Recorded tool trace, schematic timing.')

    # 5
    s = add('Education: one workspace, different needs.', 'Experience adapted to the user',
            'Same New Pronote workspace: the teacher (Mme Laurent) dictates for a pupil of the native roster; the student practice activity '
            'generated through the Devin API (about 565 s, session 71991d82) is previewed with wrong-answer feedback; the parent view shows '
            'Grégory Martin\'s two children, Alex Martin and Lucas Martin, each point linked to its source. The parent persona is a demo view, '
            'not an authorization boundary.', 5)
    for i, (key, label, sub) in enumerate([('teacher', 'Teacher', 'Mme Laurent dictates'), ('student', 'Student', 'Research-informed Devin exercise'),
                                            ('parent', 'Parent', 'Grégory Martin · Alex and Lucas')]):
        x = 0.6 + i * 4.1
        text(s, x, 1.95, 3.9, 0.35, label, size=17, bold=True)
        text(s, x, 2.32, 3.9, 0.3, sub, size=13, color=MUTED)
        picture(s, key, x, 2.75, 3.9, 3.6)
    caption(s, 'Teacher and parent views; student exercise shown in teacher preview. Administrative workflows are a next step.')

    # 6
    s = add('An estimated 43% less active entry time.', 'Impact scenario',
            '43% is the rounded median of the declared input-sensitivity model, not a measured human comparison or a share of all working hours. '
            'The annual teacher median is 6.0555 hours across selected tasks. Scaling to 485,450 secondary teachers gives 2.94 million hours; '
            'at an assumed EUR40/hour this is EUR117.6 million of gross time value, rounded to 3M hours and EUR120M. '
            'This assumes complete adoption and excludes technology costs. No cash saving or net ROI is established.', 6)
    data = CategoryChartData()
    data.categories = ['Manual entry', 'With Calli']
    data.add_series('Active time index', (100, 57))
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.6), Inches(2.0), Inches(8.2), Inches(3.9), data)
    ch = gf.chart
    ch.has_legend, ch.has_title = False, False
    plot = ch.plots[0]
    plot.gap_width, plot.has_data_labels = 60, True
    plot.data_labels.number_format, plot.data_labels.number_format_is_linked = '0', False
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    plot.data_labels.font.size, plot.data_labels.font.name = Pt(14), FONT
    ser = plot.series[0]
    for idx, color in enumerate((GREY, GREEN)):
        pt = ser.points[idx]
        pt.format.fill.solid(); pt.format.fill.fore_color.rgb = color
    ch.category_axis.tick_labels.font.size, ch.category_axis.tick_labels.font.name = Pt(14), FONT
    ch.category_axis.reverse_order = True
    ch.value_axis.visible, ch.value_axis.has_major_gridlines = False, False
    ch.value_axis.maximum_scale = 120
    text(s, 9.2, 2.2, 3.6, 3.5, [('~3M hours / year', {'bold': True, 'size': 22}),
                                 ('~€120M time value', {'bold': True, 'size': 22}), '',
                                 'Secondary teachers in France', 'Full adoption · €40/hour assumed', 'Gross time value before costs'], size=14, color=MUTED)
    caption(s, 'Scenario, not a human benchmark. DEPP 2026 headcount; national-scenario.json. 33–52% input sensitivity.')

    # 7
    s = add('Measured, with its scope.', 'Evidence',
            'Each value is one recorded run with its own scope; they are not interchangeable and they are not reliability statistics. '
            'Queue to verified 25.57 s and item 12.3 s (next_item to report_result) are different scopes of the native writer. '
            'Failed trials are kept in the repository next to the successful ones.', 7)
    rows = [('What', 'Measured', 'Scope · source'),
            ('Native queue → verified comment', '25.57 s', 'one recorded item · docs/calli-api-and-architecture.md'),
            ('Native item, next_item → report_result', '12.3 s', 'one item · video/calli-ui-demo/timeline.json'),
            ('H sourced preparation', '97.31 s', 'H session e1f16a50'),
            ('New Devin API practice generation', '~565 s', 'session 71991d82 · 23 functional checks'),
            ('Outing partial draft', '90.22 s', 'run 23025b24ce29 · 3 concurrent collectors')]
    tbl = s.shapes.add_table(len(rows), 3, Inches(0.6), Inches(2.0), Inches(12.1), Inches(3.9)).table
    for c, wdt in enumerate((4.6, 1.8, 5.7)):
        tbl.columns[c].width = Inches(wdt)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.fill.solid(); cell.fill.fore_color.rgb = PAPER if r == 0 else RGBColor(0xff, 0xff, 0xff)
            cell.margin_left = cell.margin_right = Inches(0.14)
            tf = cell.text_frame; tf.text = ''
            run = tf.paragraphs[0].add_run(); run.text = val
            run.font.name, run.font.size = FONT, Pt(13 if r == 0 else 15)
            run.font.bold = r == 0 or c == 1
            run.font.color.rgb = (GREEN if c == 1 and r else MUTED if r == 0 or c == 2 else INK)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    caption(s, 'Single recorded runs, not reliability statistics. Failed trials are retained in the repository.')

    # 8
    s = add('Your software. Less repetitive work.', 'Starting with education',
            'Close on the general mechanism and the concrete educational benefit. The team combines parallel assistance, native software integration and a role-specific experience. Video: https://www.youtube.com/watch?v=mILSh_vLQck (1:59.8). Public source: '
            'https://github.com/CalliH2026/app. Explore saved runs: https://calli-demo.leisurelychestnut.chatgpt.site (the New Pronote UI with saved H and outing reports, family sources and the interactive '
            'Devin exercise; no new provider or native execution). Team: François, Wilfred, Liqin.', 8)
    s.shapes.add_picture(str(ROOT / IMG['logo']), Inches(0.6), Inches(2.0), height=Inches(1.0))
    text(s, 0.6, 3.35, 12.0, 2.2, [(('Watch  ', {'bold': True}), 'youtu.be/mILSh_vLQck  (1:59.8)'),
                                   (('Code  ', {'bold': True}), 'github.com/CalliH2026/app'),
                                   (('Explore saved runs  ', {'bold': True}), ('calli-demo.leisurelychestnut.chatgpt.site', {'link': 'https://calli-demo.leisurelychestnut.chatgpt.site', 'color': BLUE}))],
         size=18, color=MUTED, spacing=1.5)
    text(s, 0.6, 5.55, 12.0, 0.5, [(('François · Wilfred · Liqin', {'bold': True, 'color': INK}),)], size=20)
    caption(s, 'Built with H Company (Holo, Agents API), Gladia, Linkup and the Cognition Devin API.')

    # Backup A
    s = add('Backup · National impact, with explicit assumptions.', 'Scenario method',
            'DEPP 2026 reports 47,000 primary schools, 7,000 colleges, 3,700 lycees and 485,450 secondary teachers. '
            'Establishment count is context; secondary-teacher headcount is the multiplier. Workload assumptions stay those of the previous model. '
            '100,000 input samples describe sensitivity, not statistical confidence. At 10% adoption the same scenario is about 294,000 hours '
            'and EUR11.8 million gross time value; costs and other actors are excluded. See docs/national-impact-scenario.md.', 'A')
    text(s, 0.6, 2.0, 12.0, 0.7, '485,450 teachers × 6.0555 h/year × €40/h = €117.6M/year', size=26, bold=True, color=BLUE)
    text(s, 0.6, 3.05, 5.7, 2.7, ['Official population: DEPP 2026', 'Workload: 450 comments, 20 meetings, 2 outings',
         'Setup and assisted interventions included', 'Primary and administrative work not extrapolated'], size=18, spacing=1.4)
    text(s, 6.8, 3.05, 5.7, 2.7, ['100% adoption: ~3M h / ~€120M', '10% adoption: ~294k h / ~€12M',
         '€25–60/h valuation: ~€73–176M', 'Gross value of capacity; costs not deducted'], size=18, spacing=1.4)
    caption(s, 'Scenario assumptions; not a forecast, measured saving, budget cut or net ROI. No double counting across actors.')

    # Backup B
    s = add('Backup · APIs and tools actually used.', 'Inventory',
            'Only verified integrations are listed (docs/calli-api-and-architecture.md). Stripe in the outing flow creates non-routable preview links only: '
            'no Stripe payment. A separate Checkout sandbox adapter is implemented and tested offline; account validation remains pending. A logo is not evidence of an API call.', 'B')
    rows = [('Service', 'Used for', 'Verified'),
            ('H Agents API · Holo 4', 'Operate PRONOTE through next_item / report_result', 'native write and read-back, 25.57 s'),
            ('H managed agents', 'Sourced preparation, family digest selection', 'preparation 97.31 s; family run 16.29 s'),
            ('Gladia', 'Speech to text', 'live transcription of a synthetic dictation'),
            ('Linkup', 'Educational source search', 'preparation + learning-science research'),
            ('Cognition Devin API', 'Development, Windows VMs, practice', 'new activity: 23 functional checks'),
            ('ElevenLabs', 'Fictional parent audio, narration', 'synthetic audio, labelled'),
            ('OSRM', 'Outing route estimate', 'present in the outing flow; not a booking')]
    tbl = s.shapes.add_table(len(rows), 3, Inches(0.6), Inches(2.0), Inches(12.1), Inches(4.3)).table
    for c, wdt in enumerate((3.4, 4.6, 4.1)):
        tbl.columns[c].width = Inches(wdt)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.fill.solid(); cell.fill.fore_color.rgb = PAPER if r == 0 else RGBColor(0xff, 0xff, 0xff)
            cell.margin_left = cell.margin_right = Inches(0.14)
            tf = cell.text_frame; tf.text = ''
            run = tf.paragraphs[0].add_run(); run.text = val
            run.font.name, run.font.size, run.font.bold = FONT, Pt(12 if r == 0 else 13), r == 0 or c == 0
            run.font.color.rgb = MUTED if r == 0 else INK
    caption(s, 'Stripe: Checkout sandbox adapter implemented; account test pending. Video checkout is a local illustration.')

    # Backup C
    s = add('Modernize the experience. Keep the installed application.', 'Technical appendix · UI retrofit',
            'New Pronote is a new task-oriented interface. Holo 4 drives the installed PRONOTE desktop while Python owns structured jobs, '
            'functions, validation and the journal. We do not modify the native executable or database. This is a UI retrofit, not a cloned '
            'PRONOTE backend. The demonstrated integration is one desktop writing flow, not a universal connector.', 'C')
    picture(s, 'today', 0.6, 2.05, 5.2, 3.2)
    picture(s, 'pronote', 7.5, 2.05, 5.2, 3.2)
    text(s, 5.95, 3.2, 1.4, 1.4, ['Holo 4', '+ tools', '→'], size=19, bold=True, align=PP_ALIGN.CENTER, color=BLUE)
    text(s, 0.6, 5.55, 12.0, 0.9, 'New Pronote → bounded Python jobs → Holo 4 → existing PRONOTE → read-back', size=19, bold=True)
    caption(s, 'No change to the native application code or database. A demonstrated workflow, not a complete PRONOTE replacement.')

    # Backup D
    s = add('Use the best integration for each operation.', 'Technical appendix · API, MCP or computer use?',
            'An API or CLI is preferred when a supported interface exposes the needed operation with adequate access and guarantees. '
            'MCP exposes capabilities implemented by a server; it does not create a missing vendor operation. INDEX EDUCATION documents '
            'export services and connectors. We have not established that PRONOTE has no APIs, nor that writing an MCP server is impossible. '
            'Our native demonstration operates a particular installed desktop flow through its existing UI. '
            'Sources: https://modelcontextprotocol.io/docs/learn/architecture and '
            'https://telechargement.index-education.com/fr/pronote-info1420-services-export-de-donnees.php', 'D')
    cols = [('Supported API / CLI', 'Structured operations', 'Prefer when available, licensed and adequate for the task.'),
            ('MCP server', 'Expose implemented capabilities', 'A standard tool interface; the underlying integration still needs to exist.'),
            ('Computer use', 'Operate an existing interface', 'Useful when the required operation is accessible through the installed UI.')]
    for i, (label, sub, detail) in enumerate(cols):
        x = 0.6 + i * 4.1
        box(s, x, 2.1, 3.8, 3.8)
        text(s, x + .22, 2.4, 3.36, .8, label, size=23, bold=True, color=BLUE)
        text(s, x + .22, 3.35, 3.36, .9, sub, size=18, bold=True)
        text(s, x + .22, 4.45, 3.36, 1.1, detail, size=16, color=MUTED)
    caption(s, 'MCP architecture and INDEX EDUCATION export-service documentation; direct source links in speaker notes.')

    # Backup E
    s = add('Learning science informs the activity. Tests check its behavior.', 'Linkup → Devin',
            'Linkup helped locate learning-science guidance, checked against IES and EEF sources. The product adds optional worked examples, '
            'attempts before correction, explanatory feedback and retry. Devin session 71991d82 generated the new interactive artifact; '
            '23 independent functional checks and 450 generated triangle cases passed. These checks do not demonstrate better learning outcomes. '
            'Devin was also used throughout development and for Windows VM setup. See docs/learning-science-and-impact.md.', 'E')
    picture(s, 'student', 6.7, 1.95, 6.0, 4.45)
    text(s, 0.6, 2.05, 5.6, 3.8, ['Linkup: source the principles', 'Devin: build the interactive exercise',
          'Try → explain → practise again', '', '23 functional checks · 450 triangle cases'], size=22, spacing=1.4)
    caption(s, 'Real new API output, sandboxed preview. Functional verification is separate from a learning-effectiveness study.')

    out = OUT / 'calli-pitch-en.pptx'
    prs.save(out)
    md = ['# Calli pitch deck: speaker notes', '', 'Generated by `docs/pitch/build_deck.py`; slide text and notes live there.', '']
    for number, title, note in notes:
        md += [f'## {number}. {title}', '', note, '']
    (OUT / 'speaker-notes.md').write_text('\n'.join(md), encoding='utf-8')
    prov = {'generator': 'docs/pitch/build_deck.py', 'python_pptx': '1.0.2', 'font': FONT,
            'positioning': {'promise': 'An assistant that works alongside you',
                            'mechanism': 'Observe context, prepare useful work in parallel, act through tools and computer use',
                            'first_demonstrated_application': 'Education / New Pronote',
                            'observation_scope': 'Registered document openings inside Calli',
                            'core_slide_order': ['promise', 'mechanism', 'native proof', 'parallel tools', 'roles',
                                                 'time estimate', 'measured evidence', 'links and team']},
            'images': {k: {'path': str(p.relative_to(ROOT)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for k, p in sorted(used.items())},
            'facts': {'national_scenario': NATIONAL, 'current_entry_reduction_percent': 43, 'historical_base_time_model': {'path': 'video/inserts/calli-time-estimate/model.json', 'scenario_cpm': 225,
                                     'manual_s': BASE['manual_human_active_s_estimated'], 'calli_s': BASE['calli_human_active_s_estimated'],
                                     'saved_percent': BASE['human_active_percent_saved_estimated'], 'classification': TIME['classification']},
                      'native_queue_to_verified_s': {'value': 25.57, 'source': 'docs/calli-api-and-architecture.md'},
                      'native_item_s': {'value': 12.3, 'source': 'video/calli-ui-demo/timeline.json'},
                      'h_preparation_s': {'value': 97.31, 'source': 'video/calli-presentation/provenance.json (H session e1f16a50)'},
                      'devin_generation_s': {'value': 565, 'source': 'video/calli-v10/evidence/exercise/practice-state.json (session 71991d82, rounded)'},
                      'outing_partial_s': {'value': 90.22, 'source': 'video/calli-ui-demo/provenance.json (run 23025b24ce29)'},
                      'video': {'url': 'https://www.youtube.com/watch?v=mILSh_vLQck', 'duration': '1:59.8',
                                'file': None,
                                'sha256': 'c9bc36fa842ebae5607b0ecfdd39cfb369d15595e2598cb8b7e2d8ba3fed65e0'},
                      'explore_saved_runs': {'url': 'https://calli-demo.leisurelychestnut.chatgpt.site', 'scope': 'saved runs only, no new provider or native execution'}}}
    (OUT / 'provenance.json').write_text(json.dumps(prov, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return out


if __name__ == '__main__':
    print(build())
