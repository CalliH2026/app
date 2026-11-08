/* The live PRONOTE connector is separate from the fictional Alex dossier. */
(() => {
  let state = null, busy = false, lastRun = '';
  const followDossier = document.getElementById('parallel-follow').onclick;
  const e = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function request(path = '', body) {
    const response = await fetch('/api/pronote/background' + path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || 'Connexion à vérifier.');
    return data;
  }
  function mount() {
    const overview = document.querySelector('.agent-overview');
    if (!overview || document.getElementById('background-pronote')) return;
    const panel = document.createElement('section');
    panel.id = 'background-pronote'; panel.className = 'background-pronote';
    overview.after(panel); render();
  }
  function render() {
    const panel = document.getElementById('background-pronote');
    if (!panel) return;
    const active = state?.active, running = state?.state === 'running', report = state?.report;
    panel.innerHTML = `<header class="background-heading"><div class="background-symbol"><img class="calli-symbol" src="/static/brand/calli-symbol.svg" alt=""></div><div><span class="overline">${sponsorBrand('hcompany')} · LE VRAI PRONOTE EN ARRIÈRE-PLAN</span><h2>Votre espace reste à vous.</h2><p>Calli consulte PRONOTE dans son propre navigateur, pendant que vous travaillez.</p></div><span class="badge ${active?'purple':'gray'}">${running?'H travaille':active?'Connecté':'À connecter'}</span></header><div class="background-body"><div><strong>${e(state?.message || 'Connecter la démonstration officielle PRONOTE.')}</strong><p class="fine">Source distincte du dossier d’Alex · site de démonstration INDEX ÉDUCATION · lecture seule.</p><div class="background-controls"><button class="button primary" data-background="${active?'read':'start'}" ${busy||running?'disabled':''}>${busy?'Connexion…':running?'Lecture en cours…':active?'Relire les vues':'Connecter PRONOTE en fond'}</button>${active?'<button class="button secondary" data-background="stop">Arrêter</button>':''}<a class="button quiet" href="/pilot" target="_blank">Connexion établissement ↗</a></div><p class="fine">Une fois connecté, l’ouverture d’une copie dans New PRONOTE déclenche aussi ce relevé, sans prompt.</p></div><aside><span class="overline">VOTRE MAC RESTE DISPONIBLE</span><ul><li>Votre souris et votre clavier restent libres.</li><li>Aucune capture de vos autres applications.</li><li>Les routes observées sont vérifiées par Codex.</li></ul></aside></div>${state?.error?`<p class="background-error" role="alert">${e(state.error)}</p>`:''}${state?.run_id?`<div class="background-tool-calls">${functionCallsPanel(state)}</div>`:''}${state?.routes?.length?`<div class="background-routes">${state.routes.map(route=>`<span class="source-chip">✓ ${e(route.id==='notes_fanny'?'Relevé individuel':route.title)}</span>`).join('')}</div>`:''}${state?.actions?.length?`<details class="background-trace" ${running?'open':''}><summary>Suivi de la lecture · ${state.actions.length} messages</summary><ol>${state.actions.map(action=>`<li><time>${new Date(action.at).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time><span>${e(action.text)}</span></li>`).join('')}</ol></details>`:''}${report?`<article class="background-report"><span class="overline">RAPPORT DU VRAI PRONOTE WEB</span><h3>Ce que Calli a relevé.</h3><p>${e(report.summary)}</p>${report.facts.map(fact=>`<div class="background-fact"><strong>${e(fact.claim)}</strong><blockquote>${e(fact.quote)}</blockquote><button class="source-chip" data-background-source="${e(fact.route_id)}">Voir la même vue ↗</button></div>`).join('')}<h4>À compléter</h4><ul>${report.unknowns.map(item=>`<li>${e(item)}</li>`).join('')}</ul>${report.next_steps?.length?`<h4>La suite proposée</h4><ul>${report.next_steps.map(item=>`<li>${e(item)}</li>`).join('')}</ul>`:''}${state.video_url?`<details class="background-video"><summary>▶ Voir le navigateur de l’agent</summary><video controls preload="none" src="${e(state.video_url)}"></video><p class="fine">${e(state.video_kind)} Source : navigateur PRONOTE de fond.</p></details>`:''}<div class="background-controls"><button class="button secondary" data-background="dismiss">Dismiss</button><button class="button primary" data-background="keep">${state.kept?'✓ Conservé':'Keep · Garder ce rapport'}</button></div></article>`:''}<p class="background-limit">Les copies et barèmes joints ne sont pas encore lus par ce connecteur. Le client Mac garde son diagnostic séparé ; les routes de chaque établissement devront être vérifiées sur sa propre interface.</p>`;
    panel.querySelectorAll('[data-background]').forEach(button => button.onclick = () => action(button.dataset.background));
    panel.querySelectorAll('[data-background-source]').forEach(button => button.onclick = () => {
      const snapshot = state.snapshots[button.dataset.backgroundSource];
      const target = document.getElementById('source-content');
      target.innerHTML = `<span class="overline">VRAI PRONOTE WEB · INSTANTANÉ</span><h2>${e(snapshot.title.split(' - ')[0])}</h2><p>${e(snapshot.source_url)}</p>${snapshot.selections?.length?`<p class="fine">${snapshot.selections.map(selection=>e(selection.label||selection.selector)+' : '+e(selection.text)).join(' · ')}</p>`:''}<pre class="background-source">${e(snapshot.visible_text)}</pre><p class="fine">Relevé du ${e(new Date(snapshot.observed_at).toLocaleString('fr-FR'))} · SHA-256 ${e(snapshot.content_sha256)}</p>`;
      document.getElementById('source-dialog').showModal();
    });
  }
  async function action(name) {
    if (busy) return; busy = true; render();
    try {
      if (name === 'start') { state = await request('/start',{source:'official_demo'}); state = await request('/read',{}); }
      else if (name === 'keep' || name === 'dismiss') state = await request('/decision',{decision:name});
      else state = await request('/'+name,{});
    } catch (error) { state = {...state,error:error.message}; }
    finally { busy = false; render(); updateDock(); }
  }
  function updateDock() {
    if (!state?.active) { document.getElementById('parallel-follow').onclick = followDossier; return; }
    const running = state.state === 'running';
    if (running || (state.report && !state.dismissed && !state.kept)) {
      document.getElementById('dock-title').textContent = running ? 'Calli consulte PRONOTE' : 'Le relevé PRONOTE est prêt';
      document.getElementById('dock-detail').textContent = state.actions?.at(-1)?.text || state.message;
      document.getElementById('parallel-dock').classList.toggle('working',running);
      if (!document.getElementById('background-pronote')) document.getElementById('parallel-dock').hidden = false;
      document.getElementById('parallel-watch').onclick = () => { document.querySelector('[data-page="agent"]').click(); };
      document.getElementById('parallel-follow').onclick = () => { document.querySelector('[data-page="agent"]').click(); };
    } else document.getElementById('parallel-follow').onclick = followDossier;
  }
  async function refresh() {
    if (busy) return;
    try {
      state = await request();
      const identity = JSON.stringify([state.run_id,state.state,state.actions?.length,state.kept,state.dismissed,state.active,state.tool_calls]);
      if (identity !== lastRun) { lastRun = identity; render(); }
      updateDock();
    } catch (_) { /* Existing dossier remains usable while the connector is offline. */ }
  }
  new MutationObserver(mount).observe(document.getElementById('main'),{childList:true});
  mount(); refresh(); setInterval(refresh,2500);
})();
