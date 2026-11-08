// Run with: node --test mvp/test_management_grading.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { randomUUID } = require('node:crypto');

const voiceSource = fs.readFileSync(path.join(__dirname, 'static/grading-voice.js'), 'utf8');
const source = fs.readFileSync(path.join(__dirname, 'static/management.js'), 'utf8');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/alex.json'), 'utf8'));
const storageKey = 'new-pronote-management-v1';
const decode = text => String(text).replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));

// Model only form controls and dialog behavior. Native HTML validation is
// deliberately bypassed by submit() to exercise the application's validation.
function harness(storage = new Map()) {
  const nodes = new Map(), notices = [], redraws = [], preparations = [];
  let currentForm;
  const attribute = (attributes, name) => attributes.match(new RegExp(`\\b${name}="([^"]*)"`))?.[1];
  function node(id) {
    if (nodes.has(id)) return nodes.get(id);
    const element = {
      id, value: '', hidden: true, open: false, elements: {}, dataset: {}, classList: { toggle() {} },
      focus() { this.focused = true; },
      showModal() { this.open = true; },
      close() { this.open = false; },
      setAttribute(name, value) { this[name] = value; },
      querySelector() { return this.elements.score || { focus() {} }; },
      querySelectorAll() { return []; },
      get innerHTML() { return this.html || ''; },
      set innerHTML(html) {
        this.html = html;
        const formId = html.match(/<form\b[^>]*id="([^"]*)"/)?.[1];
        if (formId) currentForm = node(formId);
        for (const match of html.matchAll(/<input\b([^>]*)>|<(select|textarea)\b([^>]*)>([\s\S]*?)<\/\2>/g)) {
          const attributes = match[1] || match[3], name = attribute(attributes, 'name');
          if (!name || !currentForm) continue;
          const control = node(attribute(attributes, 'id') || `${currentForm.id}:${name}`);
          if (match[2] === 'select') {
            const options = [...match[4].matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/g)];
            const option = options.find(option => /\bselected\b/.test(option[1])) || options[0];
            control.value = decode(option ? attribute(option[1], 'value') ?? option[2] : '');
          } else {
            control.value = decode(match[2] === 'textarea' ? match[4] : attribute(attributes, 'value') ?? '');
          }
          currentForm.elements[name] = control;
        }
      },
    };
    nodes.set(id, element);
    return element;
  }
  const workspace = {
    students: [{ ...fixture.student, initials: 'AM', assessment: { score: 3, maximum: 6 } }],
    documents: structuredClone(fixture.documents),
  };
  const context = vm.createContext({
    $, workspace, esc: escape, structuredClone, crypto: { randomUUID }, page: 'document',
    localStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => { if (context.storageFails) throw Error('Quota exceeded'); storage.set(key, value); },
    },
    FormData: class {
      constructor(form) { this.form = form; this.parts = []; }
      get(name) { return this.form?.elements[name]?.value ?? null; }
      append(...args) { this.parts.push(args); }
    },
    feedback: message => notices.push(message),
    prepareGradedAssessment: record => preparations.push(structuredClone(record)),
    Blob, AbortController, navigator: {}, setTimeout: () => 1, clearTimeout() {},
    showPage: (...args) => redraws.push(args),
    bindContent() {},
    document: { querySelectorAll: () => [] },
  });
  function $(id) { return node(id); }
  vm.runInContext(source, context, { filename: 'management.js' });
  return {
    context, storage, nodes, notices, redraws, preparations, workspace, node,
    enableVoice() { vm.runInContext(voiceSource, context, { filename: 'grading-voice.js' }); },
    data: () => context.getManagement(),
    open(evaluationId = 'source-alex') { context.openGrading('alex', evaluationId); return node('grading-form'); },
    submit(values = {}) {
      const form = node('grading-form');
      for (const [name, value] of Object.entries(values)) form.elements[name].value = String(value);
      form.onsubmit({ target: form, preventDefault() {} });
    },
  };
}

test('zero and decimal grades persist with appreciation, preserve source, and reopen after reload', () => {
  for (const score of [0, 4.25]) {
    const app = harness(), original = JSON.stringify(app.workspace);
    app.open();
    app.submit({ score, maximum: 6, appreciation: 'Calcul exact, préciser la justification.' });
    const saved = JSON.parse(app.storage.get(storageKey));
    assert.equal(saved.evaluations.length, 1);
    assert.equal(saved.evaluations[0].id, 'source-alex');
    assert.equal(saved.evaluations[0].source, true);
    assert.equal(saved.evaluations[0].score, score);
    assert.equal(saved.evaluations[0].maximum, 6);
    assert.equal(saved.evaluations[0].status, 'Corrigée');
    assert.ok(saved.evaluations[0].gradedAt);
    assert.equal(JSON.stringify(app.workspace), original);
    assert.equal(app.node('management-dialog').open, false);
    assert.equal(app.redraws[0][0], 'document');
    const reloaded = harness(app.storage);
    reloaded.open();
    assert.equal(Number(reloaded.node('grading-form').elements.score.value), score);
    assert.equal(reloaded.node('grading-form').elements.appreciation.value, 'Calcul exact, préciser la justification.');
    assert.equal(reloaded.context.getRecordedGrade('alex', 'source-alex').score, score);
  }
});

test('invalid grades and maxima never enter storage', () => {
  for (const [score, maximum] of [['', '6'], [' ', '6'], ['-1', '6'], ['6.01', '6'], ['NaN', '6'], ['Infinity', '6'], ['1', '0'], ['0', '-1'], ['1', ''], ['1', 'NaN'], ['1', 'Infinity']]) {
    const app = harness();
    app.open();
    app.submit({ score, maximum });
    assert.equal(app.storage.has(storageKey), false, `Unexpected save for ${score}/${maximum}`);
    assert.equal(app.context.getRecordedGrade('alex'), null);
    assert.equal(app.node('management-dialog').open, true);
    assert.equal(app.node('grading-error').hidden, false);
    assert.ok(app.node('grading-error').textContent);
  }
});

test('cancel and unavailable storage preserve both durable and current grade', () => {
  const app = harness();
  app.open();
  app.submit({ score: 4, appreciation: 'Première note' });
  const durable = app.storage.get(storageKey);
  app.open();
  app.node('grading-form').elements.score.value = '5';
  app.node('cancel-grading').onclick();
  assert.equal(app.storage.get(storageKey), durable);
  assert.equal(app.context.getRecordedGrade('alex').score, 4);
  app.open();
  app.context.storageFails = true;
  app.submit({ score: 5, appreciation: 'Ne doit pas être enregistré' });
  assert.equal(app.storage.get(storageKey), durable);
  assert.equal(app.context.getRecordedGrade('alex').score, 4);
  assert.equal(app.node('management-dialog').open, true);
  assert.match(app.notices.at(-1), /Enregistrement impossible/);
});

test('appreciation is escaped when reopened and excessively long text is rejected', () => {
  const app = harness(), appreciation = '</textarea><script>window.pwned=true</script>';
  app.open();
  app.submit({ score: 3, appreciation });
  app.open();
  assert.equal(app.node('grading-form').elements.appreciation.value, appreciation);
  assert.ok(app.node('grading-fields').innerHTML.includes('&lt;/textarea&gt;&lt;script&gt;'));
  assert.equal(app.node('grading-fields').innerHTML.includes('<script>'), false);
  const durable = app.storage.get(storageKey);
  app.submit({ appreciation: 'a'.repeat(2001) });
  assert.equal(app.storage.get(storageKey), durable);
  assert.equal(app.node('grading-error').hidden, false);
});

test('only explicitly recorded, active grades are surfaced and identity remains fixed', () => {
  const app = harness();
  assert.equal(app.context.getRecordedGrade('alex'), null);
  app.open();
  app.submit({ score: 2 });
  assert.equal(app.context.getRecordedGrade('someone-else'), null);
  assert.equal(app.context.getRecordedGrade('alex', 'different-evaluation'), null);
  app.data().evaluations[0].archived = true;
  assert.equal(app.context.getRecordedGrade('alex'), null);
  app.context.openGrading('alex', 'source-alex');
  assert.equal(app.node('management-dialog').open, false);
  app.data().students[0].archived = true;
  app.context.openGrading('alex');
  assert.equal(app.node('management-dialog').open, false);
  assert.match(app.notices.at(-1), /restaurez/);
});

test('a new evaluation records a separate grade for the selected student', () => {
  const app = harness();
  app.open();
  const select = app.node('grading-evaluation');
  select.value = '';
  select.onchange();
  app.submit({ title: 'Travail autonome', date: '2026-11-07', score: '15.5', maximum: '20', appreciation: 'Bonne progression' });
  const saved = JSON.parse(app.storage.get(storageKey));
  assert.equal(saved.evaluations.length, 2);
  assert.equal(saved.evaluations[0].score, 3);
  assert.equal(saved.evaluations[0].gradedAt, undefined);
  const recorded = app.context.getRecordedGrade('alex');
  assert.equal(recorded.title, 'Travail autonome');
  assert.equal(recorded.studentId, 'alex');
  assert.equal(recorded.class, '4e B');
  assert.equal(recorded.score, 15.5);
  assert.equal(recorded.maximum, 20);
  assert.equal(recorded.source, undefined);
  app.context.openGrading('alex');
  assert.equal(app.node('grading-evaluation').value, recorded.id);
});

test('editing a source evaluation keeps its student and grading shortcuts intact', () => {
  const app = harness();
  app.data().students.push({ id: 'lea', name: 'Léa Durand', class: '4e B', archived: false });
  vm.runInContext("managementTab='evaluations'", app.context);
  app.context.editManagement('source-alex');
  const form = app.node('record-form');
  form.elements.studentId.value = 'lea';
  form.elements.score.value = '4';
  form.onsubmit({ target: form, preventDefault() {} });
  assert.equal(app.context.getRecordedGrade('alex', 'source-alex').score, 4);
  assert.equal(app.context.getRecordedGrade('lea'), null);
  app.open();
  assert.equal(app.node('management-dialog').open, true);
});

test('saved Alex assessment is frozen for Parallèle and generic students do not launch Alex reports', () => {
  const app = harness();
  app.open();
  app.submit({ score: 12, maximum: 20, appreciation: 'Bon travail.' });
  assert.equal(app.preparations.length, 1);
  const assessment = app.context.getTeacherAssessment();
  assert.equal(assessment.student_id, 'alex');
  assert.equal(assessment.evaluation_id, 'source-alex');
  assert.equal(assessment.score, 12);
  assert.equal(assessment.maximum, 20);
  assert.equal(assessment.appreciation, 'Bon travail.');
  app.data().evaluations[0].score = 14;
  assert.equal(assessment.score, 12);
  app.data().students.push({ id: 'lea', name: 'Léa Durand', class: '4e B', archived: false });
  app.context.openGrading('lea');
  app.submit({ title: 'Devoir', date: '2026-11-07', score: 15, maximum: 20 });
  assert.equal(app.preparations.length, 1);
});

test('Gladia upload fills 12/20 and appreciation, exposes transcript, and waits for saving', async () => {
  const app = harness(), calls = [];
  app.enableVoice();
  app.context.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ provider: 'Gladia', transcription: { text: 'Note Alex pour le devoir et mets-lui douze sur vingt.' }, command: { score: 12, maximum: 20, appreciation: 'Bon travail.', student_name: 'Alex', evaluation_title: null } }) };
  };
  app.open();
  const file = app.node('grading-audio-file');
  file.files = [{ name: 'note.webm', size: 30 }];
  await file.onchange();
  assert.equal(calls[0].url, '/api/workspace/grading/transcribe');
  assert.equal(calls[0].options.body.parts[0][0], 'audio');
  assert.equal(app.node('grading-form').elements.score.value, '12');
  assert.equal(app.node('grading-form').elements.maximum.value, '20');
  assert.equal(app.node('grading-form').elements.appreciation.value, 'Bon travail.');
  assert.equal(app.node('grading-voice-transcript').hidden, false);
  assert.match(app.node('grading-voice-transcript').textContent, /douze sur vingt/);
  assert.equal(app.storage.has(storageKey), false);
  assert.equal(app.preparations.length, 0);
  app.submit();
  assert.equal(app.preparations[0].score, 12);
});

test('voice target mismatch and failed transcription leave current grade unchanged', async () => {
  for (const result of [
    { ok: true, body: { provider: 'Gladia', transcription: { text: 'Note Léa douze sur vingt.' }, command: { score: 12, maximum: 20, student_name: 'Léa', evaluation_title: null } } },
    { ok: false, body: { detail: { message: 'Aucune note claire.', transcription: { text: 'Je ne sais pas.' } } } },
  ]) {
    const app = harness();
    app.enableVoice();
    app.context.fetch = async () => ({ ok: result.ok, json: async () => result.body });
    app.open();
    app.node('grading-audio-file').files = [{ name: 'note.wav', size: 20 }];
    await app.node('grading-audio-file').onchange();
    assert.equal(app.node('grading-form').elements.score.value, '3');
    assert.equal(app.node('grading-form').elements.maximum.value, '6');
    assert.equal(app.storage.has(storageKey), false);
    assert.ok(app.node('grading-voice-status').textContent);
    assert.equal(app.node('save-grading').disabled, false);
  }
});

test('closing dictation ignores a late Gladia response', async () => {
  const app = harness();
  let respond;
  app.enableVoice();
  app.context.fetch = () => new Promise(resolve => { respond = resolve; });
  app.open();
  app.node('grading-audio-file').files = [{ name: 'note.wav', size: 20 }];
  const pending = app.node('grading-audio-file').onchange();
  app.node('cancel-grading').onclick();
  respond({ ok: true, json: async () => ({ provider: 'Gladia', transcription: { text: '12 sur 20' }, command: { score: 12, maximum: 20, appreciation: null } }) });
  await pending;
  assert.equal(app.node('grading-form').elements.score.value, '3');
  assert.equal(app.storage.has(storageKey), false);
});

test('microphone resources are released on cancel without uploading audio', async () => {
  const app = harness();
  let stops = 0, uploads = 0;
  app.enableVoice();
  app.context.navigator.mediaDevices = { getUserMedia: async () => ({ getTracks: () => [{ stop() { stops++; } }] }) };
  app.context.MediaRecorder = class {
    static isTypeSupported() { return true; }
    constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.onstop?.(); }
  };
  app.context.fetch = async () => { uploads++; };
  app.open();
  await app.node('grading-record').onclick();
  assert.equal(app.node('grading-record').textContent, 'Arrêter et transcrire');
  assert.equal(app.node('save-grading').disabled, true);
  app.node('cancel-grading').onclick();
  assert.ok(stops >= 1);
  assert.equal(uploads, 0);
});
