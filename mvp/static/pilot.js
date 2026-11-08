const fields=['connection_mode','establishment','web_url','auth_route','server','port','client_path'];
const el=id=>document.getElementById(id);
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Configuration invalide : vérifiez les champs.');return data;}
let dirty=false;
let viewTimer=null,viewBusy=false,viewGeneration=0;
function stopViewRefresh(uncheck=false){clearTimeout(viewTimer);viewTimer=null;viewGeneration++;if(uncheck)el('authenticated').checked=false;}
function scheduleViewRefresh(){clearTimeout(viewTimer);if(!dirty&&el('connection_mode').value==='web'&&el('authenticated').checked&&el('view-auto-refresh').checked&&!el('browser-panel').hidden)viewTimer=setTimeout(()=>captureBrowserView(true),10000);}
function renderMode(){const web=el('connection_mode').value==='web';for(const id of ['local-config','local-actions','local-help'])el(id).hidden=web;el('web-actions').hidden=!web;el('web-config').hidden=!web;el('web_url').required=web;el('client_path').required=!web;stopViewRefresh(true);}
el('connection_mode').onchange=renderMode;
el('config').oninput=()=>{dirty=true;stopViewRefresh(true);};
async function action(path,body){try{const result=await api(path,body);el('message').textContent=result.message||'Configuration enregistrée.';return result;}catch(e){el('message').textContent=e.message;}}
el('config').onsubmit=async e=>{e.preventDefault();const config=Object.fromEntries(fields.map(k=>[k,k==='port'?Number(el(k).value):el(k).value.trim()]));if(await action('/api/pilot/config',config))dirty=false;};
function saved(){if(!dirty)return true;el('message').textContent='Enregistrez la configuration avant de démarrer.';return false;}
async function start(allow_ocr){if(saved())await action('/api/pilot/start',{allow_ocr});}
el('start').onclick=()=>start(false);el('ocr').onclick=()=>start(true);el('stop').onclick=async()=>{stopViewRefresh(true);await action('/api/pilot/stop',{});};
el('web-start').onclick=async()=>{if(!saved())return;stopViewRefresh(true);el('web-start').disabled=true;el('message').textContent='Ouverture du navigateur dédié…';try{await action('/api/pilot/web/start',{});el('authenticated').checked=false;}finally{el('web-start').disabled=false;}};
async function captureBrowserView(automatic=false){
  if(viewBusy||!saved())return;
  if(!el('authenticated').checked){if(!automatic)el('message').textContent='Confirmez votre connexion avant la lecture.';return;}
  if(automatic&&(!el('view-auto-refresh').checked||el('browser-panel').hidden||el('connection_mode').value!=='web'))return;
  viewBusy=true;const generation=viewGeneration;el('web-capture').disabled=true;
  try{await api('/api/pilot/web/capture',{authenticated:true});if(generation===viewGeneration)el('message').textContent=el('view-auto-refresh').checked?'Vue actualisée. La lecture se poursuit automatiquement.':'Vue relevée. Vérifiez le texte ci-dessous.';}
  catch(error){if(generation===viewGeneration){stopViewRefresh(true);el('message').textContent=error.message;}}
  finally{viewBusy=false;el('web-capture').disabled=false;scheduleViewRefresh();}
}
el('web-capture').onclick=()=>captureBrowserView();
el('authenticated').onchange=()=>{stopViewRefresh();scheduleViewRefresh();};
el('view-auto-refresh').onchange=()=>{stopViewRefresh();scheduleViewRefresh();};
window.addEventListener('pronote-path-change',()=>{stopViewRefresh();scheduleViewRefresh();});
async function poll(){try{if(el('connection_mode').value==='web'){const web=await api('/api/pilot/web');el('state').textContent=web.active?`Navigateur dédié ouvert · ${el('authenticated').checked&&el('view-auto-refresh').checked?'lecture automatique de la vue ouverte':'en attente de confirmation ou relevé manuel'}`:'Navigateur dédié fermé.';el('context').textContent=web.context?`${web.context.source_url}\n${web.context.observed_at}\n\n${web.context.visible_text}`:'Aucune vue web relevée.';}else{const [settings,context]=await Promise.all([api('/api/native/settings'),api('/api/native/context')]);el('state').textContent=settings.enabled&&settings.mode==='pilot'?`Lecture active · ${context.state} · ${context.observed_at||'en attente du premier relevé'}`:'Lecture du pilote arrêtée.';el('context').textContent=settings.mode==='pilot'?(context.visible_text||context.message||'Ouvrez le client et une vue pédagogique.'):'Aucun relevé du pilote.';}}catch(e){el('state').textContent=e.message;}setTimeout(poll,3500);}
api('/api/pilot').then(d=>{for(const k of fields)el(k).value=d.config[k]??(k==='auth_route'?'ent':'');renderMode();el('message').textContent=d.message;}).catch(e=>el('message').textContent=e.message);renderMode();poll();


// The two connection paths share no credentials or browser storage.
(() => {
  const base = '/api/pronote/connection';
  let available = false;
  let busy = false;
  let latest = null;
  let timer = null;
  let lastData = '';
  const labels = {
    profile: 'Mon compte', name: 'Nom', first_name: 'Prénom', last_name: 'Nom',
    account: 'Compte', account_type: 'Type de compte', establishment: 'Établissement',
    classes: 'Classes', class_name: 'Classe', students: 'Élèves', children: 'Enfants',
    timetable: 'Emploi du temps', lessons: 'Cours', homework: 'Travail à faire',
    grades: 'Notes', periods: 'Périodes', averages: 'Moyennes', absences: 'Absences',
    delays: 'Retards', information: 'Informations', evaluations: 'Évaluations',
    subject: 'Matière', teacher: 'Enseignant', date: 'Date', start: 'Début', end: 'Fin',
    start_time: 'Début', end_time: 'Fin', description: 'Description', content: 'Contenu',
    title: 'Intitulé', room: 'Salle', classroom: 'Salle', done: 'Terminé',
    grade: 'Note', out_of: 'Sur', coefficient: 'Coefficient', average: 'Moyenne',
    max: 'Maximum', min: 'Minimum', period: 'Période', groups: 'Groupes',
    status: 'État', canceled: 'Annulé', cancelled: 'Annulé', due_date: 'À rendre le',
    warnings: 'Informations de lecture', unavailable: 'Données indisponibles'
  };
  const sensitive = key => /password|credential|token|cookie|secret|jeton|^pin$|^login$|^id$|_id$|url/i.test(key);
  const label = key => labels[key] || key.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
  const displayDate = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('fr-FR');
  };
  function setPath(automatic) {
    el('browser-panel').hidden = automatic;
    el('automatic-panel').hidden = !automatic;
    el('choose-browser').setAttribute('aria-pressed', String(!automatic));
    el('choose-automatic').setAttribute('aria-pressed', String(automatic));
    window.dispatchEvent(new Event('pronote-path-change'));
    if (automatic && !el('auto-url').value) el('auto-url').value = el('web_url').value;
  }
  el('choose-browser').onclick = () => setPath(false);
  el('choose-automatic').onclick = () => setPath(true);
  function authFields() {
    const qr = el('auto-auth').value === 'qr';
    el('auto-password-fields').hidden = qr;
    el('auto-qr-fields').hidden = !qr;
    el('auto-username').required = !qr;
    el('auto-password').required = !qr;
    el('auto-qr').required = qr;
    el('auto-pin').required = qr;
    el('auto-remember').disabled = !qr;
    if (!qr) el('auto-remember').checked = false;
    // Do not retain the secrets of a previously selected login method.
    el('auto-password').value = '';
    el('auto-qr').value = '';
    el('auto-pin').value = '';
  }
  el('auto-auth').onchange = authFields;
  el('auto-account').onchange = () => {
    el('auto-account-help').textContent = el('auto-account').value === 'teacher'
      ? 'Pour les comptes enseignants, ce connecteur lit uniquement le profil. Utilisez « Ouvrir mon PRONOTE » pour lire automatiquement le contenu de la vue ouverte.'
      : 'Seules les informations accessibles à votre compte peuvent être synchronisées.';
  };
  el('auto-enabled').onchange = () => { el('auto-interval').disabled = !el('auto-enabled').checked; };
  function controls() {
    const pending = busy || ['connecting', 'syncing'].includes(latest?.state);
    el('auto-connect').disabled = !available || pending;
    el('auto-sync').disabled = pending || (!latest?.connected && !(latest?.state === 'error' && latest?.retryable === true));
    el('auto-disconnect').disabled = pending || (!latest?.connected && (!latest || latest.state === 'disconnected'));
  }
  function format(value, depth = 0) {
    if (value === null || value === undefined || value === '') return '';
    if (typeof value === 'boolean') return value ? 'Oui' : 'Non';
    if (typeof value !== 'object') return String(value);
    if (depth > 2) return '';
    if (Array.isArray(value)) return value.slice(0, 12).map(item => format(item, depth + 1)).filter(Boolean).join(' · ');
    return Object.entries(value).filter(([key]) => !sensitive(key)).map(([key, item]) => {
      const text = format(item, depth + 1);
      return text ? `${label(key)} : ${text}` : '';
    }).filter(Boolean).join('\n');
  }
  function datasets(data) {
    const encoded = JSON.stringify(data || {});
    if (encoded === lastData) return;
    lastData = encoded;
    el('auto-data').replaceChildren();
    const entries = data && typeof data === 'object' ? Object.entries(data).filter(([key]) => !sensitive(key)) : [];
    el('auto-results').hidden = entries.length === 0;
    for (const [key, value] of entries) {
      const section = document.createElement('section');
      section.className = 'dataset';
      const heading = document.createElement('h3');
      heading.textContent = `${label(key)}${Array.isArray(value) ? ` · ${value.length}` : ''}`;
      section.append(heading);
      if (Array.isArray(value)) {
        if (!value.length) {
          const empty = document.createElement('p');
          empty.textContent = 'Aucun élément récupéré pour cette période.';
          section.append(empty);
        } else {
          const list = document.createElement('ul');
          value.slice(0, 60).forEach(item => {
            const text = format(item);
            if (!text) return;
            const row = document.createElement('li');
            row.textContent = text;
            list.append(row);
          });
          section.append(list);
          if (value.length > 60) {
            const more = document.createElement('small');
            more.textContent = `Les 60 premiers éléments sont affichés sur ${value.length}.`;
            section.append(more);
          }
        }
      } else {
        const text = document.createElement('p');
        text.style.whiteSpace = 'pre-wrap';
        text.textContent = format(value) || 'Aucune information récupérée.';
        section.append(text);
      }
      el('auto-data').append(section);
    }
  }
  function render(status) {
    latest = status;
    el('auto-status').textContent = status.message || (status.connected ? 'Compte connecté.' : 'Aucun compte connecté.');
    const details = [];
    if (status.last_sync_at) details.push(`Dernière actualisation : ${displayDate(status.last_sync_at)}`);
    if (status.connected) details.push(status.auto_sync
      ? `Actualisation automatique toutes les ${Math.max(1, Math.round((status.interval_seconds || 300) / 60))} min`
      : 'Actualisation manuelle');
    if (status.state === 'error' && status.retryable === true && status.auto_sync) details.push('Nouvelle tentative automatique…');
    el('auto-sync-detail').textContent = details.join(' · ');
    const warnings = Array.isArray(status.warnings) ? status.warnings.map(warning => typeof warning === 'string' ? warning : format(warning)).filter(Boolean) : [];
    el('auto-warnings').textContent = warnings.join('\n');
    el('auto-warnings').hidden = warnings.length === 0;
    const capabilities = Array.isArray(status.capabilities) ? status.capabilities : [];
    el('auto-capabilities').textContent = capabilities.length
      ? `Données accessibles : ${capabilities.map(item => typeof item === 'string' ? label(item) : item.label || '').filter(Boolean).join(', ')}.`
      : 'Les informations affichées dépendent des droits du compte et des fonctions prises en charge.';
    datasets(status.data);
    controls();
  }
  function schedule() {
    clearTimeout(timer);
    if (latest?.connected || ['connecting', 'syncing'].includes(latest?.state) || (latest?.state === 'error' && latest?.retryable === true)) timer = setTimeout(refresh, 5000);
  }
  async function refresh() {
    try { render(await api(base)); }
    catch (error) { el('auto-status').textContent = error.message; }
    finally { schedule(); }
  }
  async function run(operation) {
    if (busy) return;
    busy = true;
    clearTimeout(timer);
    controls();
    try { render(await operation()); }
    catch (error) { el('auto-status').textContent = error.message; }
    finally { busy = false; controls(); schedule(); }
  }
  el('auto-setup').onsubmit = event => {
    event.preventDefault();
    run(async () => {
      el('auto-status').textContent = 'Connexion et première synchronisation…';
      const qr = el('auto-auth').value === 'qr';
      try {
        return await api(base + '/connect', {
          web_url: el('auto-url').value.trim(), account_type: el('auto-account').value,
          auth_method: el('auto-auth').value, username: qr ? '' : el('auto-username').value.trim(),
          password: qr ? '' : el('auto-password').value, qr_code: qr ? el('auto-qr').value.trim() : '',
          pin: qr ? el('auto-pin').value : '', ent: qr ? '' : el('auto-ent').value,
          remember_session: el('auto-remember').checked, auto_sync: el('auto-enabled').checked,
          interval_seconds: Number(el('auto-interval').value)
        });
      } finally {
        el('auto-password').value = '';
        el('auto-qr').value = '';
        el('auto-pin').value = '';
      }
    });
  };
  el('auto-sync').onclick = () => run(async () => {
    el('auto-status').textContent = 'Actualisation des données…';
    return await api(base + '/sync', {});
  });
  el('auto-disconnect').onclick = () => run(async () => {
    const result = await api(base + '/disconnect', {});
    el('auto-password').value = '';
    el('auto-qr').value = '';
    el('auto-pin').value = '';
    return result;
  });
  function options(id, values) {
    if (!Array.isArray(values) || !values.length) return;
    const select = el(id);
    const current = select.value;
    select.replaceChildren();
    values.forEach(value => {
      const option = document.createElement('option');
      option.value = typeof value === 'string' ? value : value.id;
      option.textContent = typeof value === 'string' ? label(value) : value.label;
      select.append(option);
    });
    if ([...select.options].some(option => option.value === current)) select.value = current;
  }
  async function initialize() {
    try {
      const settings = await api(base + '/options');
      available = settings.available === true;
      options('auto-account', settings.accounts);
      options('auto-auth', settings.auth_methods);
      options('auto-ent', [{id: '', label: 'Connexion PRONOTE directe'}, ...(settings.ents || []).filter(item => (typeof item === 'string' ? item : item.id) !== '')]);
      el('auto-options-message').textContent = settings.message || (available ? 'Choisissez votre compte et votre mode de connexion.' : 'La connexion automatique est indisponible dans cette installation. Le parcours navigateur reste accessible.');
      authFields();
      el('auto-account').onchange();
    } catch (error) {
      el('auto-options-message').textContent = `Connexion automatique indisponible : ${error.message} Le parcours navigateur reste accessible.`;
    }
    controls();
    await refresh();
  }
  authFields();
  initialize();
})();
