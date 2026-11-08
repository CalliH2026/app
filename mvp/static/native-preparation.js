/* Native PRONOTE preparation. This component never starts or simulates a job. */
(() => {
  'use strict';
  const STATUS_URL = '/api/native/documents';
  const ROOT_ID = 'native-preparation';
  const requestedJob = location.pathname === '/native'
    ? new URLSearchParams(location.search || '').get('job') : null;
  const hasRequestedJob = requestedJob !== null;
  const BUSY = new Set(['preparing', 'rendering']);
  const html = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[character]));
  let observed = null, connectionError = '', signature = '', timer = null, deciding = false;
  let sourceDialog = null;

  function nativeJob() {
    const job = observed?.preparation;
    return job?.id && job.source_kind === 'pronote_native_dossier' ? job : null;
  }

  function sourcesFor(job) {
    const manifest = job?.captured_case || job?.source_manifest;
    const sources = Array.isArray(manifest) ? manifest : manifest?.sources;
    return Array.isArray(sources) ? sources : [];
  }

  function clock(value) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
  }

  function localMedia(value, jobId) {
    if (!value || !jobId) return '';
    try {
      const url = new URL(value, location.origin);
      return url.origin === location.origin && url.pathname.startsWith('/outputs/' + encodeURIComponent(jobId) + '/')
        ? url.href : '';
    } catch (_) { return ''; }
  }

  function sourceURL(job, source) {
    return '/api/native/documents/' + encodeURIComponent(job.id) + '/' + encodeURIComponent(source.id);
  }

  function statusLabel(job) {
    if (connectionError) return 'Connexion à vérifier';
    if (job?.status === 'ready') return 'Prêt à relire';
    if (job?.status === 'rendering') return 'Vidéo en préparation';
    if (job?.status === 'preparing') return 'H prépare le dossier';
    if (job?.status === 'failed') return 'À vérifier';
    if (observed?.state === 'blocked' || observed?.error) return 'Pièces à vérifier';
    if (!observed?.manifest_available) return 'Import attendu';
    return observed?.active ? 'À l’écoute du client' : 'Observateur arrêté';
  }

  function mount() {
    const overview = document.querySelector('.agent-overview');
    const legacy = location.pathname === '/native' ? document.getElementById('report') : null;
    if (!overview && !legacy) return;
    let panel = document.getElementById(ROOT_ID);
    if (!panel) {
      panel = document.createElement('section');
      panel.id = ROOT_ID;
      panel.className = 'np-card';
      panel.setAttribute('aria-label', 'Préparation depuis le client PRONOTE Mac');
      if (overview) overview.after(panel); else legacy.before(panel);
      render();
    } else if (overview && overview.nextElementSibling !== panel) {
      // The Web component also mounts after this overview. Keep native first.
      overview.after(panel);
    }
  }

  function evidenceButtons(ids, job, sources) {
    return (Array.isArray(ids) ? ids : []).flatMap(id => {
      const source = sources.find(item => item.id === id);
      return source ? [`<button class="np-source-link" data-np-source="${html(source.id)}">${html(source.title || source.id)} ↗</button>`] : [];
    }).join('');
  }

  function seconds(value) {
    const total = Math.max(0, Math.floor(Number(value) || 0));
    return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
  }

  function vocalHTML(job) {
    const transcript = job.transcription;
    if (job.question_origin !== 'parent_audio' || !transcript?.text) return '';
    const audio = /^parent-audio\.[a-z0-9]+$/i.test(job.captured_audio || '')
      ? localMedia(`/outputs/${encodeURIComponent(job.id)}/${encodeURIComponent(job.captured_audio)}`, job.id) : '';
    const utterances = (transcript.utterances || []).filter(item => Number.isFinite(Number(item.start)) && Number.isFinite(Number(item.end)));
    const question = (job.dossier?.question || '').toLocaleLowerCase('fr');
    const excerpt = question && utterances.find(item => String(item.text || '').toLocaleLowerCase('fr').includes(question));
    return `<section class="np-vocal"><span class="np-eyebrow">${job.mode === 'demo' ? 'QUESTION DU VOCAL · TRANSCRIPTION DE DÉMONSTRATION' : `${sponsorBrand('gladia')} · QUESTION DU VOCAL`}</span>
      ${audio ? `<audio controls preload="metadata" src="${html(audio)}"></audio>` : ''}
      ${audio && excerpt ? `<button class="np-source-link" data-np-audio-start="${Number(excerpt.start)}" data-np-audio-end="${Number(excerpt.end)}">Écouter l’extrait · ${seconds(excerpt.start)}–${seconds(excerpt.end)}</button>` : ''}
      <details class="np-details"><summary>Transcription et repères temporels</summary>${utterances.length
        ? utterances.map(item => `<p><time>${seconds(item.start)}–${seconds(item.end)}</time> ${html(item.text)}</p>`).join('')
        : `<p>${html(transcript.text)}</p>`}</details>
      <p class="np-footnote">Vocal synthétique joint au dossier de test, distinct des pièces importées dans PRONOTE.</p></section>`;
  }

  function referencesHTML(job) {
    const references = (job.search?.sources || []).flatMap(source => {
      try {
        const url = new URL(source.url);
        return ['http:', 'https:'].includes(url.protocol) ? [{...source, url:url.href, host:url.hostname}] : [];
      } catch (_) { return []; }
    });
    if (!references.length) return '';
    return `<section class="np-references"><span class="np-eyebrow">${job.mode === 'demo' ? 'RESSOURCES DE DÉMONSTRATION' : `${sponsorBrand('linkup')} · COMPRENDRE ET PROGRESSER`}</span>
      <p class="np-footnote">La copie et le barème expliquent la note. Ces ressources complètent l’explication et le travail à proposer.</p>
      ${references.map(source => `<article><a href="${html(source.url)}" target="_blank" rel="noopener">${html(source.title || source.host)} ↗</a><small>${html(source.host)}</small><details class="np-details"><summary>Extrait de la ressource</summary><p>${html(String(source.excerpt || '').slice(0, 650))}</p></details></article>`).join('')}
      ${job.search?.query ? `<details class="np-details"><summary>Recherche pédagogique effectuée</summary><p>${html(job.search.query)}</p></details>` : ''}</section>`;
  }

  function callsHTML(job) {
    const offline = job.mode === 'demo';
    if (!offline && !Array.isArray(job.tool_calls)) {
      return '<section class="np-calls"><span class="np-eyebrow">APPELS D’OUTILS H</span><p class="np-call-empty">Non mesuré pour ce rapport</p><small>Les anciens journaux ne permettent pas de compter les appels réels.</small></section>';
    }
    const calls = offline ? [] : job.tool_calls.filter(call => call && call.kind === 'custom');
    const names = new Set(calls.map(call => call.name).filter(Boolean));
    const count = status => calls.filter(call => call.status === status).length;
    const failed = count('failed'), succeeded = count('succeeded'), running = count('running');
    const cached = calls.filter(call => call.cached).length;
    const labels = {read_native_documents:'Lire les pièces du dossier',transcribe_audio:'Transcrire le vocal parental',search_resources:'Rechercher une ressource pédagogique',read_native_repair_context:'Relire les preuves pour corriger'};
    return `<section class="np-calls" aria-label="Appels d’outils H"><header><div><span class="np-eyebrow">APPELS D’OUTILS H</span><p>Outils métier suivis · navigation non comptée</p></div><span class="np-call-tag">${offline?'HORS LIGNE':running?'EN COURS':'APPELS RÉELS'}</span></header>
      <div class="np-call-summary" role="status" aria-live="polite" aria-atomic="true"><strong>${calls.length}<span>appel${calls.length>1?'s':''}</span></strong><div><b>${names.size}</b> outil${names.size>1?'s':''} distinct${names.size>1?'s':''}<small>${succeeded} réussi${succeeded>1?'s':''} · ${running} en cours · ${failed} erreur${failed>1?'s':''} · ${cached} en cache</small></div></div>
      ${offline?'<p class="np-call-empty">Aucun appel H en mode hors ligne. Les étapes scénarisées ne sont pas comptées.</p>':calls.length?`<ol>${calls.map((call,index) => {
        const status = ['running','succeeded','failed'].includes(call.status) ? call.status : 'unknown';
        const state = {running:'En cours',succeeded:'Réussi',failed:'Échec',unknown:'État indisponible'}[status];
        const milliseconds = Number(call.duration_ms);
        const duration = status !== 'running' && Number.isFinite(milliseconds) && milliseconds >= 0
          ? milliseconds < 1000 ? `${Math.round(milliseconds)} ms` : `${(milliseconds/1000).toLocaleString('fr-FR',{maximumFractionDigits:1})} s` : '';
        const args = call.arguments == null ? '' : typeof call.arguments === 'string' ? call.arguments : JSON.stringify(call.arguments);
        return `<li class="np-call ${status}"><span class="np-call-index">${index+1}</span><div><div class="np-call-title"><h4>${html(labels[call.name]||call.name||'Appel d’outil')}</h4><span>${state}</span></div><code>${html(call.name)}</code><small>${[clock(call.started_at),duration,call.cached?'Résultat en cache':''].filter(Boolean).map(html).join(' · ')}</small>${args&&args!=='{}'?`<p class="np-call-args"><b>Paramètres</b> ${html(args)}</p>`:''}${call.result_summary?`<p class="np-call-result"><b>${status==='failed'?'Erreur':'Résultat'}</b> ${html(call.result_summary)}</p>`:status==='running'?'<p class="np-call-result pending">L’outil travaille…</p>':''}</div></li>`;
      }).join('')}</ol>`:'<p class="np-call-empty">Les appels apparaîtront ici dès leur exécution par H.</p>'}</section>`;
  }

  function reportHTML(job, sources) {
    const dossier = job.dossier;
    if (!dossier) return '';
    const questionLabel = job.question_origin === 'parent_audio' && job.transcription?.available !== false
      ? 'QUESTION DU VOCAL PARENTAL' : 'OBJECTIF DE PRÉPARATION';
    const evidence = Array.isArray(dossier.evidence) ? dossier.evidence : [];
    const unknowns = Array.isArray(dossier.unknowns) ? dossier.unknowns : [];
    return `<article class="np-explanation"><span class="np-eyebrow">${questionLabel}</span>
      ${dossier.question ? `<h3>${html(dossier.question)}</h3>` : ''}
      ${dossier.summary ? `<p>${html(dossier.summary)}</p>` : ''}
      ${job.editorial_review ? '<details class="np-details"><summary>Révision du brouillon H</summary><p>Le brouillon H a été relu et corrigé par Codex pendant la vérification de cette démonstration. Les pièces, la question transcrite et les citations sont conservées. Le professeur doit encore valider la capsule avant partage.</p></details>' : ''}
      ${evidence.map(item => `<div class="np-evidence"><strong>${html(item.claim)}</strong><blockquote>${html(item.quote)}</blockquote><div class="np-source-buttons">${evidenceButtons(item.source_ids, job, sources)}</div></div>`).join('')}
      ${unknowns.length ? `<details class="np-details"><summary>Questions restant à éclaircir · ${unknowns.length}</summary><ul>${unknowns.map(item => `<li>${html(item)}</li>`).join('')}</ul></details>` : ''}
    </article>`;
  }

  function render() {
    const panel = document.getElementById(ROOT_ID);
    if (!panel) return;
    const job = nativeJob();
    document.body.classList.toggle('np-has-case', location.pathname === '/native' && !!job);
    const sources = sourcesFor(job);
    const working = !!job && BUSY.has(job.status);
    const ready = job?.status === 'ready';
    const dossier = job?.dossier;
    const events = Array.isArray(job?.events) ? job.events : [];
    const video = ready ? localMedia(job.video, job.id) : '';
    const captions = localMedia(job?.captions, job?.id);
    const verifiedRoles = new Set((observed?.sources || []).map(source => source.role));
    const paired = ['watching', 'preparing'].includes(observed?.state)
      && verifiedRoles.has('copy') && verifiedRoles.has('rubric');
    const label = dossier?.display_label || (observed?.identity
      ? [observed.identity.student_name, observed.identity.class_name].filter(Boolean).join(' · ') : '');
    const message = connectionError || (working ? 'La copie a été ouverte dans PRONOTE. Le dossier se prépare en arrière-plan.'
      : ready ? video ? 'Le rapport et la capsule issus de cette ouverture native sont prêts à relire.'
        : 'Le rapport issu de cette ouverture native est prêt. La disponibilité de la capsule reste à vérifier.'
      : job?.status === 'failed' ? 'Cette préparation n’a pas pu aboutir. Ses pièces et ses actions restent consultables.'
      : observed?.message || 'En attente de l’import vérifié de la copie et du barème dans le client Mac.');
    const provenanceNotice = dossier?.provenance_notice || (job
      ? sources.some(source => source.provenance?.kind === 'imported_demo_document'
          || source.provenance?.import_origin_kind === 'imported_demo_document' || source.provenance?.demo_data)
        ? 'Documents fictifs importés dans le vrai PRONOTE, puis lus lors de l’ouverture de la copie.'
        : 'Les pièces de cette ouverture native sont conservées avec leurs preuves et leurs sources.'
      : 'La copie et le barème doivent être réellement joints et vérifiés dans la base PRONOTE. Leur simple présence sur le Mac ne déclenche aucune préparation.');
    const capturedIds = new Set((job?.captured_sources || []).map(source => source.id));
    const pdfList = sources.map(source => `<div class="np-document"><span class="np-document-icon" aria-hidden="true">↗</span><div><strong>${html(source.title || source.id)}</strong><small>${html({copy:'Copie',rubric:'Barème',instructions:'Consigne',method:'Méthode',message:'Échange',appointment:'Rendez-vous'}[source.role] || 'Pièce scolaire')}</small></div><button class="np-source-link" data-np-source="${html(source.id)}">Texte lu ↗</button>${capturedIds.has(source.id) ? `<a class="np-source-link" href="${html(sourceURL(job, source))}" target="_blank" rel="noopener">PDF ↗</a>` : ''}</div>`).join('');
    const detailsOpen = panel.querySelector('.np-events')?.open;
    const currentVideo = panel.querySelector('video');
    const preserveVideo = currentVideo && currentVideo.getAttribute('src') === video;
    const playback = preserveVideo ? {time:currentVideo.currentTime, paused:currentVideo.paused} : null;
    panel.innerHTML = `<header class="np-heading"><span class="np-mark"><img class="calli-symbol" src="/static/brand/calli-symbol.svg" alt="Calli, votre assistant"></span><div><span class="np-eyebrow">VRAI CLIENT PRONOTE MAC · AVEC ${sponsorBrand('hcompany')}</span><h2>${ready?'Le dossier natif est préparé.':job?'Une copie ouverte. La suite se prépare.':'La préparation suit votre copie.'}</h2>${label ? `<p>${html(label)}</p>` : ''}</div><span class="np-status ${working?'np-working':''} ${job?.status==='failed'||observed?.state==='blocked'?'np-warning':''}"><i></i>${html(statusLabel(job))}</span></header>
      <div class="np-intake"><p class="np-message" role="status">${html(message)}</p><p class="np-provenance">${html(provenanceNotice)}</p>
      ${!job ? `<div class="np-checks"><span><i>${paired?'✓':'1'}</i>${paired?'Pièces vérifiées':observed?.manifest_available?'Vérifier les pièces enregistrées':'Importer et vérifier les pièces'}</span><span><i>2</i>Ouvrir la copie dans PRONOTE</span><span><i>3</i>Relire le rapport et la capsule</span></div><p class="np-footnote">L’observation de l’ouverture, puis la lecture des fichiers se font en fond. Aucun prompt de préparation n’est nécessaire.</p>` : ''}
      ${observed?.error || job?.error ? `<details class="np-details np-error"><summary>Une vérification est nécessaire</summary><p>${html(job?.error || observed.error)}</p></details>` : ''}</div>
      ${job?.status === 'failed' ? `<p class="np-footnote">Les pièces et les résultats déjà obtenus sont conservés. La reprise garde cette ouverture de copie, sans nouvel appel Gladia ou Linkup.</p><button class="np-button np-secondary" data-np-resume ${deciding?'disabled':''}>Reprendre la préparation</button>` : ''}
      ${job ? `<div class="np-job"><details class="np-details np-tool-audit"><summary>Actions et appels d’outils H</summary>${callsHTML(job)}</details>${events.length ? `<details class="np-details np-events" ${working || detailsOpen?'open':''}><summary>Suivi de la préparation · ${events.length} messages</summary><ol>${events.map(event => `<li><time>${html(clock(event.time || event.at))}</time><span>${html(event.text || '')}</span></li>`).join('')}</ol></details>` : ''}
      ${vocalHTML(job)}${reportHTML(job, sources)}${referencesHTML(job)}
      ${sources.length ? `<details class="np-details np-files"><summary>Les pièces utilisées par H · ${sources.length}</summary>${pdfList}<p class="np-footnote">Le texte et les fichiers conservés à l’ouverture sont accessibles pour vérifier l’explication.</p></details>` : ''}
      ${ready && video ? `<section class="np-capsule"><span class="np-eyebrow">CAPSULE PERSONNALISÉE</span><h3>Prête pour votre relecture.</h3><video controls preload="metadata" src="${html(video)}">${captions ? `<track default kind="subtitles" srclang="fr" label="Français" src="${html(captions)}">` : ''}</video><p class="np-footnote">${job.duration ? `${html(job.duration)} secondes · ` : ''}Aucun envoi automatique.</p></section>` : ready ? '<p class="np-footnote">La capsule n’est pas disponible dans cet instantané.</p>' : ''}
      <div class="np-decisions"><span>${job.notification_dismissed?'Notification masquée. Le dossier reste consultable.':job.kept?'Préparation conservée.':'Le rapport reste un brouillon à relire.'}</span><button class="np-button np-secondary" data-np-decision="dismiss" ${deciding?'disabled':''}>Dismiss</button><button class="np-button np-primary" data-np-decision="keep" ${deciding?'disabled':''}>${job.kept?'✓ Conservé':'Keep'}</button></div></div>` : ''}`;
    panel.querySelectorAll('[data-np-source]').forEach(button => button.addEventListener('click', () => showSource(button.dataset.npSource)));
    panel.querySelectorAll('[data-np-audio-start]').forEach(button => button.addEventListener('click', () => {
      const audio = panel.querySelector('.np-vocal audio');
      if (!audio) return;
      const start = Number(button.dataset.npAudioStart), end = Number(button.dataset.npAudioEnd);
      audio.currentTime = start;
      audio.ontimeupdate = () => { if (audio.currentTime >= end) { audio.pause(); audio.ontimeupdate = null; } };
      audio.play().catch(() => {});
    }));
    panel.querySelectorAll('[data-np-decision]').forEach(button => button.addEventListener('click', () => decide(button.dataset.npDecision)));
    panel.querySelector('[data-np-resume]')?.addEventListener('click', resumePreparation);
    if (playback) {
      const replacement = panel.querySelector('video');
      replacement.addEventListener('loadedmetadata', () => {
        replacement.currentTime = Math.min(playback.time, replacement.duration || playback.time);
        if (!playback.paused) replacement.play().catch(() => {});
      }, {once:true});
    }
  }

  function showSource(identifier) {
    const job = nativeJob(), source = sourcesFor(job).find(item => item.id === identifier);
    if (!job || !source) return;
    if (!sourceDialog) {
      sourceDialog = document.createElement('dialog');
      sourceDialog.className = 'np-source-dialog';
      sourceDialog.setAttribute('aria-label', 'Source native utilisée par H');
      document.body.append(sourceDialog);
      sourceDialog.addEventListener('click', event => { if (event.target === sourceDialog) sourceDialog.close(); });
    }
    const captured = (job.captured_sources || []).some(item => item.id === source.id);
    sourceDialog.innerHTML = `<button class="np-dialog-close" aria-label="Fermer la source">×</button><span class="np-eyebrow">CLIENT MAC · PIÈCE CONSERVÉE DANS LE DOSSIER H</span><h2>${html(source.title || source.id)}</h2><pre>${html(source.text)}</pre>${captured ? `<a class="np-button np-secondary" href="${html(sourceURL(job, source))}" target="_blank" rel="noopener">Ouvrir le PDF conservé ↗</a>` : ''}<details class="np-details"><summary>Provenance de la pièce</summary><p>${html(job.dossier?.provenance_notice || source.provenance?.kind || '')}</p><p>Identifiant : ${html(source.id)}</p>${source.sha256 ? `<p class="np-hash">SHA-256 ${html(source.sha256)}</p>` : ''}<p>${html(source.provenance?.observed_at || '')}</p></details>`;
    sourceDialog.querySelector('.np-dialog-close').onclick = () => sourceDialog.close();
    sourceDialog.showModal();
  }

  async function resumePreparation() {
    const job = nativeJob();
    if (!job || deciding || job.status !== 'failed') return;
    deciding = true; render();
    try {
      const response = await fetch('/api/native/preparations/' + encodeURIComponent(job.id) + '/resume', {method:'POST'});
      const result = await response.json();
      if (!response.ok) throw Error(result.detail || 'La préparation n’a pas pu reprendre.');
      observed.preparation = result;
      connectionError = '';
    } catch (error) { connectionError = error.message; }
    finally { deciding = false; render(); updatePresence(); }
  }

  async function decide(decision) {
    const job = nativeJob();
    if (!job || deciding) return;
    deciding = true; render();
    try {
      const response = await fetch('/api/jobs/' + encodeURIComponent(job.id) + '/decision', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({decision})
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.detail || 'La décision n’a pas été enregistrée.');
      observed.preparation = result;
      connectionError = '';
    } catch (error) { connectionError = error.message; }
    finally { deciding = false; render(); updatePresence(); }
  }

  function updatePresence() {
    let dock = document.getElementById('np-native-dock');
    const job = nativeJob();
    const onModernWorkspace = !!document.querySelector('.workspace');
    const onAgentPage = !!document.querySelector('.agent-overview');
    const visible = onModernWorkspace && !onAgentPage && job && !job.notification_dismissed
      && (BUSY.has(job.status) || job.status === 'failed' || (job.status === 'ready' && !job.kept));
    if (!visible) { if (dock) dock.hidden = true; return; }
    if (!dock) {
      dock = document.createElement('aside');
      dock.id = 'np-native-dock'; dock.className = 'np-dock';
      dock.setAttribute('aria-label', 'Activité du dossier PRONOTE Mac');
      document.body.append(dock);
    }
    dock.hidden = false;
    dock.classList.toggle('np-working', BUSY.has(job.status));
    const event = job.events?.at(-1);
    const detail = job.status === 'ready' ? 'Rapport, sources et capsule à relire.' : event?.text || 'Lecture des pièces réellement ouvertes.';
    dock.innerHTML = `<span class="np-dock-mark"><img class="calli-symbol" src="/static/brand/calli-symbol.svg" alt=""></span><button class="np-dock-open"><small>CLIENT PRONOTE MAC</small><strong>${html(statusLabel(job))}</strong><span>${html(detail)}</span></button><button class="np-dock-close" aria-label="Masquer la notification native">×</button>`;
    dock.querySelector('.np-dock-open').onclick = () => {
      const target = document.querySelector('[data-page="agent"]');
      if (target) target.click(); else location.assign('/?view=agent');
    };
    dock.querySelector('.np-dock-close').onclick = () => decide('dismiss');
  }

  async function refresh() {
    clearTimeout(timer);
    try {
      async function readJSON(path, message) {
        const response = await fetch(path, {cache:'no-store'});
        let result;
        try { result = await response.json(); } catch (_) { throw Error(message); }
        if (!response.ok) throw Error(message);
        return result;
      }
      const [statusResult, jobResult] = await Promise.allSettled([
        readJSON(STATUS_URL, 'Le suivi du client Mac est momentanément indisponible.'),
        hasRequestedJob ? readJSON('/api/jobs/' + encodeURIComponent(requestedJob), 'Cette préparation native est introuvable ou inaccessible.') : Promise.resolve(null)
      ]);
      let result;
      if (hasRequestedJob) {
        result = statusResult.status === 'fulfilled' ? statusResult.value : {
          state:'unavailable', active:false, manifest_available:false,
          message:'Le statut de l’observateur est momentanément indisponible.'
        };
        // A notification is bound to its immutable job, never the latest case.
        result.preparation = null;
        observed = result;
        if (jobResult.status !== 'fulfilled') throw jobResult.reason;
        if (jobResult.value?.source_kind !== 'pronote_native_dossier' || !jobResult.value.id) {
          throw Error('Ce lien ne correspond pas à une préparation du client PRONOTE Mac.');
        }
        result.preparation = jobResult.value;
      } else {
        if (statusResult.status !== 'fulfilled') throw statusResult.reason;
        result = statusResult.value;
      }
      observed = result; connectionError = '';
      const job = nativeJob();
      const nextSignature = JSON.stringify([result.state, result.message, result.error, result.active,
        result.manifest_available, result.sources, job?.id, job?.status, job?.events?.length,
        job?.dossier, job?.video, job?.error, job?.kept, job?.notification_dismissed, job?.tool_calls]);
      if (nextSignature !== signature) { signature = nextSignature; render(); }
      mount(); updatePresence();
    } catch (error) { connectionError = error.message; signature = ''; render(); updatePresence(); }
    finally { timer = setTimeout(refresh, BUSY.has(nativeJob()?.status) ? 2200 : connectionError ? 10000 : 5000); }
  }

  const main = document.getElementById('main');
  if (main) new MutationObserver(() => { mount(); updatePresence(); }).observe(main, {childList:true});
  mount(); refresh();
})();
