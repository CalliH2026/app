// "Ma famille": read-only parent view of two fictional children. Every element links to its dated source.
(function () {
  const MODE = {
    saved: 'Résumé enregistré de démonstration, vérifié source par source',
    live: 'Point rédigé par H à partir des sources, vérifié source par source',
  };
  const LIVE = {
    idle: 'Aucune lecture H lancée pour ces sources.',
    pending: 'H lit les dossiers…',
    failed: 'Dernière lecture H refusée ou en échec ; le résumé enregistré reste affiché.',
    disabled: 'Lecture H non activée sur ce serveur.',
  };
  const day = iso => new Date(iso + 'T12:00:00').toLocaleDateString('fr-FR', {weekday: 'short', day: 'numeric', month: 'long'});
  const sourceLink = s => `<a class="family-source${s.stale ? ' stale' : ''}" href="#family-source-${esc(s.source_id)}" data-family-source="${esc(s.source_id)}">${esc(s.kind)} · ${esc(day(s.date))}${s.stale ? ' · ancienne' : ''}</a>`;
  const avatar = c => window.studentAvatar ? studentAvatar(c.avatar?.native_id ? {native: true, nativeId: c.avatar.native_id, name: c.name} : {id: c.avatar?.id || c.child_id, name: c.name}, 'small') : '';

  // Demo persona only (no authentication): Ma famille is seen by the fictional parent, every other page by the teacher.
  let parent = null, teacher = null;
  const chip = () => ({space: document.querySelector('.school-switch small'), avatar: document.querySelector('.profile .avatar'),
    who: document.querySelector('.profile > span:nth-child(2)')});
  window.applyPersona = function (next) {
    const el = chip();
    if (!el.space || !el.avatar || !el.who) return;
    if (!teacher) teacher = {space: el.space.textContent, avatar: el.avatar.textContent, avatarClass: el.avatar.className, who: el.who.innerHTML};
    const p = next === 'family' && parent;
    el.space.textContent = p ? p.space : teacher.space;
    el.avatar.textContent = p ? p.initials : teacher.avatar;
    el.avatar.className = p ? 'avatar sage' : teacher.avatarClass;
    el.who.innerHTML = p ? `${esc(p.name)} <em class="role-tag">${esc(p.role)}</em><small>${esc(p.relation)}</small>` : teacher.who;
    document.querySelector('.profile')?.setAttribute('data-persona', p ? 'parent' : 'teacher');
  };
  fetch('/api/family').then(r => r.json()).then(data => { parent = data.parent; if (document.querySelector('.nav.active[data-page="family"]')) applyPersona('family'); }).catch(() => {});

  window.familyPage = function () {
    return title('Ma famille', 'L’essentiel pour vos enfants, au même endroit.') +
      '<section id="family-view" class="family-view"><p class="local-note">Chargement…</p></section>';
  };

  function render(box, data) {
    parent = data.parent;
    applyPersona('family');
    const live = data.live || {};
    const cards = data.children.map(c => `<article class="panel family-child"><header>${avatar(c)}<div><strong>${esc(c.name)}</strong><small>${esc(c.class)} · ${esc(c.origin)}</small></div></header>` +
      '<ul>' + c.points.map(p => `<li><p><strong>${esc(p.source.title)}</strong></p><blockquote>« ${esc(p.source.text)} »</blockquote>${sourceLink(p.source)}</li>`).join('') + '</ul>' +
      (c.missing.length ? c.missing.map(m => `<p class="family-missing"><strong>Non disponible · ${esc(m.topic)}</strong> ${esc(m.reason)}${m.source_id ? ` <a href="#family-source-${esc(m.source_id)}" data-family-source="${esc(m.source_id)}">Source</a>` : ''}</p>`).join('') : '') +
      `<details><summary>Toutes les sources (${c.sources.length})</summary><ul class="family-sources">` +
      c.sources.map(s => `<li id="family-source-${esc(s.source_id)}"><span class="mono">${esc(s.source_id)}</span> ${sourceLink(s)} · ${esc(s.author)}<p>${esc(s.text)}</p></li>`).join('') +
      '</ul></details></article>').join('');
    const deadlines = data.deadlines.map(d => `<li${d.past ? ' class="past"' : ''}><time>${esc(day(d.date))}</time><span>${esc(d.label)}</span><small>${esc(d.child_name)}</small><a href="#family-source-${esc(d.source_id)}" data-family-source="${esc(d.source_id)}">Source</a></li>`).join('');
    const actions = data.actions.map(a => `<li><span class="family-tag suggestion">Suggestion</span>${esc(a.text)}<div>${a.sources.map(sourceLink).join('')}</div></li>`).join('');
    const links = list => list.map(sourceLink).join('');
    const briefs = (data.briefs || []).map(b => `<article class="panel family-brief"><header>${avatar(b)}<div><strong>${esc(b.name)}</strong><small>${esc(b.class)}${b.stale ? ' · source ancienne' : ''}</small></div></header><dl>` +
      ((b.assessments || []).length ? `<dt>Dernière évaluation</dt>${b.assessments.map(a => `<dd class="family-assessment">${esc(a.text)} ${links(a.sources)}</dd>`).join('')}` : '') +
      (b.points.length ? `<dt>Commentaires et suivi</dt>${b.points.map(p => `<dd>« ${esc(p.text)} » ${links(p.sources)}</dd>`).join('')}` : '') +
      `<dt>Prochaine échéance</dt><dd>${b.deadline ? `<time>${esc(day(b.deadline.date))}</time> · ${esc(b.deadline.label)} ${links(b.deadline.sources)}` : 'Aucune échéance à venir dans les sources.'}</dd>` +
      (b.action ? `<dt>À faire</dt><dd>${esc(b.action.text)} ${links(b.action.sources)}</dd>` : '') +
      '</dl></article>').join('');
    const calls = (live.tool_calls || []).map(t => `<li><span class="mono">${esc(t.name)}</span> ${esc(t.status)}</li>`).join('');
    const firsts = data.children.map(c => c.name.split(' ')[0]);
    const current = box.isConnected && document.querySelector('.nav.active[data-page="family"]');
    const subtitle = current && document.querySelector('.page-title p');
    if (subtitle && firsts.length) subtitle.textContent = `L’essentiel pour ${firsts.length > 1 ? firsts.slice(0, -1).join(', ') + ' et ' + firsts.at(-1) : firsts[0]}, au même endroit.`;
    box.innerHTML = `<div class="family-banner"><p class="family-parent">${esc(data.parent.space)} · <strong>${esc(data.parent.name)}</strong> <em class="role-tag">${esc(data.parent.role)}</em> · ${esc(data.parent.relation.charAt(0).toLowerCase() + data.parent.relation.slice(1))}</p>` +
      `<span class="family-mode ${esc(data.mode)}">Sources au ${esc(day(data.as_of))}</span></div>` +
      (live.state === 'pending' ? '<p class="family-preparing" role="status">Calli prépare votre synthèse. Vous pouvez consulter les échéances.</p>' : '') +
      (briefs ? `<section class="family-briefs" aria-labelledby="family-brief-title"><h3 id="family-brief-title">Mes enfants</h3><div class="family-brief-grid">${briefs}</div></section>` : '') +
      `<details class="family-evidence family-planning"><summary>Échéances et actions pour la famille</summary><div class="family-top"><section class="panel family-block"><h3>Cette semaine pour le foyer</h3><ol class="family-actions">${actions}</ol>` +
      '<p class="local-note">Les suggestions sont choisies dans une liste revue ; les citations « » sont les faits exacts des sources.</p></section>' +
      `<section class="panel family-block"><h3>Échéances communes</h3><ul class="family-deadlines">${deadlines}</ul></section></div></details>` +
      `<details class="family-evidence"><summary>Sources, citations et données manquantes</summary><div class="family-children">${cards}</div></details>` +
      `<details class="calli-tech"><summary>Détails techniques</summary><p class="local-note">${esc(MODE[data.mode] || data.mode)}. ${esc(data.notice)}</p><p class="local-note">${esc(live.message || LIVE[live.state] || '')}` +
      ` Aucune écriture : ni PRONOTE, ni file Calli, ni notes, messages ou paiements. Démonstration locale, sans authentification de production.</p>` +
      (live.enabled ? `<button class="text-button" id="family-live"${live.state === 'pending' ? ' disabled' : ''}>Demander à H de relire les sources</button>` : '') +
      (calls ? `<ul class="family-calls">${calls}</ul>` : '') +
      ((live.errors || []).length ? `<ul class="family-errors">${live.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>` : '') + '</details>';
    box.querySelectorAll('[data-family-source]').forEach(link => link.onclick = event => {
      const target = document.getElementById('family-source-' + link.dataset.familySource);
      if (!target) return;
      event.preventDefault();
      for (let d = target.closest('details'); d; d = d.parentElement.closest('details')) d.open = true;
      target.scrollIntoView({block: 'center'});
      target.classList.add('flash');
      setTimeout(() => target.classList.remove('flash'), 1200);
    });
    const button = document.getElementById('family-live');
    if (button) button.onclick = async () => {
      button.disabled = true;
      await fetch('/api/family/digest', {method: 'POST'});
      poll(box);
    };
    if (live.state === 'pending') setTimeout(() => poll(box), 4000);
  }

  async function poll(box, opened = false) {
    if (!document.body.contains(box)) return;
    try {
      const data = await (await fetch('/api/family', {cache: 'no-store'})).json();
      if (!document.body.contains(box)) return;
      render(box, data);
      // The view-opening event is opt-in and non-blocking. Saved content remains usable.
      if (opened && data.live?.enabled && data.live.state === 'idle') {
        try {
          const response = await fetch('/api/family/open', {method: 'POST'});
          if (response.ok) poll(box);
        } catch (_) { /* Keep the already rendered source-linked summary. */ }
      }
    } catch (_) {
      box.innerHTML = '<div class="panel family-block"><h3>Vue famille indisponible</h3><p class="local-note">Le serveur ne répond pas. Aucune donnée n’a été modifiée.</p></div>';
    }
  }
  window.setupFamily = function () {
    const box = document.getElementById('family-view');
    if (box) poll(box, true);
  };
})();
