/* Summary first; the complete, source-preserving report stays available on demand. */
(() => {
  'use strict';
  let detailJob = null, detailSignature = '', detailOpener = null;
  const node = id => document.getElementById(id);
  const assessment = job => job.input_context?.teacher_assessment || job.dossier?.teacher_assessment;
  function excerpt(value, limit = 420) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    if (text.length <= limit) return text;
    const cut = text.slice(0, limit), sentence = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('! '), cut.lastIndexOf('? '));
    return sentence > limit * .55 ? cut.slice(0, sentence + 1) : cut.slice(0, cut.lastIndexOf(' ')) + '…';
  }
  window.renderReportOverview = job => {
    const ready = job.status === 'ready', failed = job.status === 'failed', grade = assessment(job);
    const summary = job.dossier?.summary || (failed ? 'La préparation a été interrompue. Consultez le détail pour retrouver les étapes disponibles.' : 'Calli rassemble les pièces et prépare l’analyse. Vous pouvez poursuivre votre travail.');
    return `<section class="report-overview"><div class="report-overview-heading"><span class="overline">RAPPORT D’ÉVALUATION</span><h2 class="report-title">${ready?'L’essentiel du rapport':failed?'Une préparation à reprendre':'Préparation en cours'}</h2></div><p class="report-summary">${esc(excerpt(summary))}</p>${grade?`<p class="report-overview-grade">Note utilisée : <strong>${gradeNumber(grade.score)} / ${gradeNumber(grade.maximum)}</strong>${grade.appreciation?`<span>${esc(excerpt(grade.appreciation, 150))}</span>`:''}</p>`:''}<div class="run-status ${!ready&&!failed?'working':''}"><i></i>${ready?'Prêt à relire':failed?'Préparation interrompue':'Préparation automatique'}<span>${job.mode==='live'?'CONNECTÉ':'HORS LIGNE'}</span></div><div class="report-overview-actions"><button class="button secondary" id="report-open-details" type="button" aria-haspopup="dialog">Voir le détail ${icon('arrow')}</button>${failed?'<button class="button secondary" id="retry-run" type="button">Reprendre la préparation</button>':''}</div></section>`;
  };
  window.renderReportCapsule = job => {
    if (job.status !== 'ready' || !job.video) return '';
    return `<section class="report-part report-capsule-summary"><h3>La capsule pédagogique</h3><video class="agent-video" id="agent-video" controls preload="metadata" src="${safe(job.video)}">${job.captions?`<track default kind="subtitles" srclang="fr" label="Français" src="${safe(job.captions)}">`:''}</video><p class="fine">${job.duration?`${esc(job.duration)} secondes · `:''}À relire avant tout partage</p><button id="approve-video" class="button ${job.approved?'secondary':'primary'}" ${job.approved?'disabled':''}>${job.approved?'✓ Capsule validée':'Valider après relecture'}</button> <a class="button quiet" href="${safe(job.video)}" download="capsule-alex.mp4">MP4 ↓</a></section>`;
  };
  function fullReport(job) {
    const dossier = job.dossier, grade = assessment(job);
    let content = `<section class="report-part"><h3>L’analyse complète</h3><p class="report-summary-full">${esc(dossier?.summary || 'Le rapport se remplit au fur et à mesure de la préparation.')}</p></section>`;
    if (grade) content += `<section class="report-part report-assessment" aria-label="Évaluation utilisée par Calli"><span class="overline">VOTRE ÉVALUATION / VERSION DE CE RAPPORT</span><h3>${esc(grade.title)}</h3><strong class="grade">${gradeNumber(grade.score)}<span>/ ${gradeNumber(grade.maximum)}</span></strong>${grade.appreciation?`<p class="grading-appreciation">${esc(grade.appreciation)}</p>`:'<p class="fine">Aucune appréciation renseignée.</p>'}<p class="fine">Cette note et cette appréciation sont incluses dans le rapport et la capsule.</p><button class="source-chip" data-source="teacher-assessment">Voir la saisie utilisée ↗</button></section>`;
    if (job.transcription) content += `<section class="report-part"><span class="overline">LA QUESTION ENTENDUE</span><blockquote>${esc(dossier?.question || job.transcription.text)}</blockquote><audio controls preload="none" src="/api/jobs/${esc(job.id)}/audio"></audio><details data-report-section="transcription"><summary>Transcription et repères temporels</summary>${(job.transcription.utterances || []).map(segment=>`<p><span class="mono">${Number(segment.start || 0).toFixed(1)}–${Number(segment.end || 0).toFixed(1)} s</span><br>${esc(segment.text)}</p>`).join('')}</details><p class="fine">${job.mode==='live'?sponsorBrand('gladia',{label:job.transcription.provider || 'Gladia'}):esc(job.transcription.provider)}</p></section>`;
    if (dossier) {
      const evidence = dossier.evidence || [], scenes = dossier.scenes || [];
      const cited = new Set([...evidence, ...scenes].flatMap(item=>item.source_ids || []));
      const resources = (job.search?.sources || []).filter(source=>cited.has(source.id));
      content += `<section class="report-part"><span class="overline">CE QUE LES PIÈCES MONTRENT</span>${evidence.map(item=>`<h3>${esc(item.claim)}</h3><blockquote>${esc(item.quote)}</blockquote>${sourceLinks(item.source_ids || [], dossier)}`).join('<div class="report-evidence-gap"></div>')}<p class="fine">${grade?'La note et l’appréciation proviennent de la saisie du professeur. La copie et le barème éclairent le travail réalisé.':'La copie et le barème expliquent la note.'} La référence publique aide à comprendre et à progresser.</p></section>`;
      if (resources.length) content += `<section class="report-part"><span class="overline">POUR PROGRESSER</span>${resources.map(source=>`<h3><a href="${safe(source.url)}" target="_blank" rel="noopener">${esc(source.title)} ↗</a></h3><p>${esc(humanExcerpt(source.excerpt))}</p>`).join('')}<details data-report-section="search"><summary>Voir la recherche ${sponsorBrand('linkup')}</summary><p>${esc(job.search.query)}</p></details></section>`;
      if (dossier.unknowns?.length) content += `<section class="report-part"><span class="overline">À ÉCLAIRCIR AU RENDEZ-VOUS</span>${dossier.unknowns.map(question=>`<p>— ${esc(question)}</p>`).join('')}</section>`;
    }
    content += functionCallsPanel(job);
    content += `<section class="report-part"><span class="overline">LE SUIVI DE LA PRÉPARATION</span><div class="activity">${(job.events || []).map(event=>`<div class="activity-item"><small>${time(event.time)} · ${esc(String(event.stage || '').toUpperCase())}</small>${esc(event.text)}${activityLink(event)}</div>`).join('')}</div>${job.error?`<p class="error-note">${esc(job.error)}</p>`:''}</section><p class="fine">${job.mode==='live'?['hcompany','gladia','linkup'].map(id=>sponsorBrand(id)).join(' · ')+'. Données de démonstration locales.':'Analyse scénarisée. Aucun appel H, Gladia ou Linkup en mode hors ligne.'}</p>`;
    return content;
  }
  function ensureDialog() {
    if (node('report-details-dialog')) return node('report-details-dialog');
    const dialog = document.createElement('dialog');
    dialog.id = 'report-details-dialog'; dialog.className = 'report-details-dialog';
    dialog.setAttribute('aria-labelledby', 'report-details-title');
    dialog.innerHTML = `<div class="report-details-shell"><header class="report-details-head"><div><h2 id="report-details-title">Le rapport détaillé</h2><p id="report-details-context"></p></div><button class="icon-button" id="report-details-close" type="button" aria-label="Fermer le rapport détaillé">${icon('close')}</button></header><div id="report-details-content" class="report-details-content" tabindex="0" aria-label="Contenu détaillé du rapport"></div></div>`;
    document.body.append(dialog);
    node('report-details-close').onclick = () => dialog.close();
    dialog.addEventListener('close', () => {
      dialog.querySelectorAll('audio,video').forEach(media=>media.pause());
      document.body.classList.remove('report-details-open');
      const opener = detailOpener?.isConnected ? detailOpener : node('report-open-details');
      opener?.focus({preventScroll:true});
    });
    return dialog;
  }
  window.closeReportDetails = () => {
    const dialog = node('report-details-dialog');
    if (!dialog?.open) return;
    const source = node('source-dialog');
    if (source?.open && source.dataset.reportJob === detailJob) source.close();
    dialog.close();
  };
  window.updateReportDetails = job => {
    const dialog = node('report-details-dialog');
    if (!dialog?.open) return;
    if (!job || detailJob !== job.id) { closeReportDetails(); return; }
    const signature = JSON.stringify([job.id,job.dossier,job.transcription,job.search,job.events,job.tool_calls,job.error,assessment(job)]);
    if (signature === detailSignature) return;
    const body = node('report-details-content'), scroll = body.scrollTop;
    const opened = [...body.querySelectorAll('details[open][data-report-section]')].map(section=>section.dataset.reportSection);
    const audio = body.querySelector('audio'), audioTime = audio?.currentTime || 0, playing = audio && !audio.paused;
    body.querySelectorAll('audio,video').forEach(media=>media.pause());
    body.innerHTML = fullReport(job); detailSignature = signature;
    opened.forEach(name=>body.querySelector(`[data-report-section="${name}"]`)?.setAttribute('open',''));
    bindContent(body); body.scrollTop = scroll;
    const nextAudio = body.querySelector('audio');
    if (nextAudio && audioTime) {
      const restore = () => {try { nextAudio.currentTime = audioTime; } catch {} if (playing) nextAudio.play().catch(()=>{});};
      nextAudio.addEventListener('loadedmetadata', restore, {once:true}); nextAudio.load();
    }
  };
  window.openReportDetails = job => {
    if (!job) return;
    const dialog = ensureDialog(), changed = detailJob !== job.id;
    detailOpener = document.activeElement; detailJob = job.id; detailSignature = '';
    const student = job.input_context?.student?.name;
    node('report-details-context').textContent = `${student ? student + ' · ' : ''}${date(job.created_at)} · ${job.mode==='live'?'Analyse connectée':'Analyse scénarisée'}`;
    if (changed) node('report-details-content').scrollTop = 0;
    document.body.classList.add('report-details-open');
    if (!dialog.open) dialog.showModal();
    updateReportDetails(job);
    if (changed) node('report-details-content').scrollTop = 0;
  };
})();
