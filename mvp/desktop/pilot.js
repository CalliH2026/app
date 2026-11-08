const el=id=>document.getElementById(id);
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Vérifiez l’adresse saisie.');return data;}
let viewTimer=null,viewBusy=false,viewGeneration=0;
function stopViewRefresh(uncheck=false){clearTimeout(viewTimer);viewTimer=null;viewGeneration++;if(uncheck)el('authenticated').checked=false;}
function scheduleViewRefresh(){clearTimeout(viewTimer);if(el('authenticated').checked&&el('view-auto-refresh').checked&&!el('browser-panel').hidden)viewTimer=setTimeout(()=>captureBrowserView(true),10000);}
function clear(){el('result').hidden=true;el('text').textContent='';el('source').textContent='';stopViewRefresh(true);}
async function action(button,callback){el(button).disabled=true;try{await callback();}catch(e){el('status').textContent=e.message;}finally{el(button).disabled=false;}}
async function captureBrowserView(automatic=false){
  if(viewBusy)return;
  if(!el('authenticated').checked){if(!automatic)el('status').textContent='Confirmez votre connexion avant la lecture.';return;}
  if(automatic&&(!el('view-auto-refresh').checked||el('browser-panel').hidden))return;
  viewBusy=true;const generation=viewGeneration;el('capture').disabled=true;
  try{const data=await api('/api/capture',{authenticated:true});if(generation!==viewGeneration)return;el('source').textContent=`${data.source_url} · ${new Date(data.observed_at).toLocaleString('fr-FR')}`;el('text').textContent=data.visible_text;el('result').hidden=false;el('status').textContent=el('view-auto-refresh').checked?'Vue actualisée. La lecture se poursuit automatiquement.':'Relevé terminé. Vérifiez le résultat ci-dessous.';}
  catch(error){if(generation===viewGeneration){stopViewRefresh(true);el('status').textContent=error.message;}}
  finally{viewBusy=false;el('capture').disabled=false;scheduleViewRefresh();}
}
el('setup').onsubmit=e=>{e.preventDefault();action('connect',async()=>{clear();el('status').textContent='Ouverture de votre PRONOTE…';const data=await api('/api/connect',{establishment:el('establishment').value.trim(),web_url:el('web_url').value.trim(),auth_route:el('auth_route').value});el('status').textContent=data.message;});};
el('setup').oninput=()=>stopViewRefresh(true);
el('capture').onclick=()=>captureBrowserView();
el('authenticated').onchange=()=>{stopViewRefresh();scheduleViewRefresh();};
el('view-auto-refresh').onchange=()=>{stopViewRefresh();scheduleViewRefresh();};
window.addEventListener('pronote-path-change',()=>{stopViewRefresh();scheduleViewRefresh();});
el('stop').onclick=()=>action('stop',async()=>{clear();const data=await api('/api/stop',{});el('status').textContent=data.message;});
api('/api/config').then(data=>{el('establishment').value=data.establishment;el('web_url').value=data.web_url;el('auth_route').value=data.auth_route||'ent';}).catch(e=>el('status').textContent=e.message);


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
