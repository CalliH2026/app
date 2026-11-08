// Calli additions to this workspace: fictional AI portraits, the native Calli roster in "Mes élèves",
// and the optional Appreciations module (Calli's own app, mounted at /calli by the server).
(function () {
  // Tile of the Calli atlas (5x2, reading order s01..s10). Explicit and stable: this workspace's fictional Alex uses
  // tile 9 (also the native pupil s10's photo); any other pupil (e.g. added by the teacher) keeps initials.
  const PORTRAITS = {alex: 9};
  const ATLAS_COLUMNS = 5;
  const NATIVE_TILE = /^s(0[1-9]|10)$/;
  const SELECTED = 'calli-appreciations-student';
  let native = {available: false, course: '', roster: []};
  window.CALLI_PHOTO_NOTE = 'Photos d’élèves fictives, générées par IA.';
  window.calliNativeStudents = [];

  function tileOf(student) {
    if (!student) return null;
    if (student.native) return NATIVE_TILE.test(student.nativeId) ? Number(student.nativeId.slice(1)) - 1 : null;
    return Object.prototype.hasOwnProperty.call(PORTRAITS, student.id) ? PORTRAITS[student.id] : null;
  }
  window.studentAvatar = function (student, extra = '') {
    const name = (student && student.name) || '';
    const tile = tileOf(student);
    if (tile === null) {
      const initials = (student && student.initials) || name.split(/\s+/).map(part => part[0] || '').slice(0, 2).join('').toUpperCase();
      return `<span class="avatar sage ${extra}">${esc(initials)}</span>`;
    }
    const x = (tile % ATLAS_COLUMNS) * 25, y = Math.floor(tile / ATLAS_COLUMNS) * 100;
    return `<span class="avatar calli-photo ${extra}" role="img" aria-label="${esc('Photo fictive générée par IA : ' + name)}" style="background-position:${x}% ${y}%"></span>`;
  };

  function courseLabel(course) {
    const [classe, subject, period] = String(course || '').split(',').map(part => part.trim());
    return subject ? `Classe ${classe} · ${subject} · ${period || ''}` : String(course || '');
  }
  function selectedId() {
    const id = sessionStorage.getItem(SELECTED);
    return native.roster.some(s => s.student_id === id) ? id : (native.roster[0] || {}).student_id || '';
  }
  window.openCalliStudent = function (id) {
    if (native.roster.some(s => s.student_id === id)) sessionStorage.setItem(SELECTED, id);
    showPage('appreciations');
  };
  // Rows of the native roster in "Mes élèves": read-only, never stored with the local records.
  window.calliNativeRow = function (item) {
    return `<tr class="calli-native-row"><td>${studentAvatar(item, 'small')}<strong>${esc(item.name)}</strong><small>Élève de la liste Calli · ${esc(item.nativeId)}</small></td>` +
      `<td>${esc(item.class)}</td><td>${esc(courseLabel(native.course))}</td>` +
      `<td><div class="row-actions"><button class="text-button" data-calli-open="${esc(item.nativeId)}">Appréciations</button></div></td></tr>`;
  };

  async function loadNative() {
    try {
      const status = await (await fetch('/api/calli/status', {cache: 'no-store'})).json();
      if (!status.available) { native = {available: false, status}; return; }
      const config = await (await fetch('/calli/api/config', {cache: 'no-store'})).json();
      native = {available: true, status, course: config.course, roster: config.roster || []};
      const classe = String(config.course || '').split(',')[0].trim();
      window.calliNativeStudents = native.roster.map(s => ({id: 'calli:' + s.student_id, nativeId: s.student_id,
        name: s.display_name, class: classe, native: true, archived: false}));
    } catch (_) {
      native = {available: false, status: {available: false, reason: 'Le module Appréciations ne répond pas.', detail: ''}};
    }
  }
  const ready = loadNative().then(() => {
    if (document.getElementById('management-results')) showPage('management', {preserveScroll: true});
  });

  window.appreciationsPage = function () {
    return title('Appréciations', 'Dictez l’appréciation de l’élève ; l’agent Calli la saisit dans PRONOTE et relit chaque cellule.') +
      '<section id="calli-module" class="calli-module"><p class="local-note">Chargement du module…</p></section>';
  };
  window.setupAppreciations = async function () {
    const box = document.getElementById('calli-module');
    if (!box) return;
    await ready;
    if (!document.body.contains(box)) return;
    if (!native.available) {
      const s = native.status || {};
      box.innerHTML = `<div class="panel calli-unavailable"><h3>Module Appréciations indisponible</h3><p>${esc(s.reason || '')}</p>` +
        '<p class="local-note">Aucune appréciation n’est envoyée et rien n’est synchronisé avec PRONOTE.</p>' +
        (s.detail ? `<details><summary>Détails techniques</summary><p class="local-note">${esc(s.detail)}</p></details>` : '') + '</div>';
      return;
    }
    const id = selectedId();
    const options = native.roster.map(s => `<option value="${esc(s.student_id)}"${s.student_id === id ? ' selected' : ''}>${esc(s.display_name)}</option>`).join('');
    box.innerHTML = `<div class="management-toolbar calli-toolbar"><label>Élève<select id="calli-student">${options}</select></label>` +
      '</div>' +
      `<iframe class="calli-frame" title="Appréciations · ${esc(native.course)}" src="${esc(native.status.url + '&student=' + encodeURIComponent(id))}" allow="microphone"></iframe>` +
      '<details class="calli-tech"><summary>Détails techniques</summary><p class="local-note">Module Calli local monté sur ce serveur (/calli). ' +
      'L’agent d’écriture tourne à part sur le poste PRONOTE ; ce panneau affiche sa file, la relecture exacte et STOP.</p></details>';
    document.getElementById('calli-student').onchange = (event) => {
      sessionStorage.setItem(SELECTED, event.target.value);
      document.querySelector('.calli-frame').src = native.status.url + '&student=' + encodeURIComponent(event.target.value);
    };
  };
})();
