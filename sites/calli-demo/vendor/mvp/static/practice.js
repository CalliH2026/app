/* Practice generation is separate from H's source analysis. Simulation is explicit. */
(() => {
  'use strict';
  const states = new Map();
  const escape = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const endpoint = id => '/api/jobs/' + encodeURIComponent(id) + '/practice';
  const card = id => document.querySelector('.practice-card[data-practice-job="'+CSS.escape(id)+'"]');
  const model = id => {if(!states.has(id))states.set(id,{value:null,loading:false,busy:false,error:'',timer:null,revision:0,sourceKey:null,element:null});return states.get(id);};
  function localUrl(value,id,suffix){try{const url=new URL(value,location.origin);return url.origin===location.origin&&url.pathname===endpoint(id)+'/'+suffix&&!url.hash?url.pathname+url.search:'';}catch{return '';}}
  function sessionUrl(value){try{const u=new URL(value);return u.protocol==='https:'&&u.hostname==='app.devin.ai'?u.href:'';}catch{return '';}}
  async function request(id,body,suffix=''){
    const response=await fetch(endpoint(id)+suffix,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    let value;try{value=await response.json();}catch{throw Error('La réponse de préparation est illisible. Réessayez.');}
    if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'La préparation n’est pas disponible. Réessayez.');
    return value;
  }
  function markup(id){
    const s=model(id),v=s.value,simulation=v?.mode!=='live',running=v?.status==='running',ready=v?.status==='ready';
    const source=v?.source_analysis==='scenario'?'Analyse scénarisée':v?.source_analysis==='h'?'Analyse de la copie par H':'Compétence à travailler issue du rapport';
    const error=s.error||((v?.status==='failed'&&v.message)?v.message:'');
    const unavailable=v&&v.available===false;
    const canCreateLive=v?.configured===true&&v.source_analysis==='h'&&v.mode!=='live'&&!running&&!s.busy&&!s.loading&&!unavailable;
    const message=s.loading&&!v?'Vérification de l’entraînement…':v?.message||'Trois étapes guidées pour repérer l’hypoténuse, appliquer Pythagore et conclure avec une unité.';
    const preview=ready?localUrl(v.preview_url,id,'preview'):'',download=ready&&v.approved?localUrl(v.download_url,id,'download'):'';
    const session=sessionUrl(v?.session_url);
    return `<div class="practice-card-head"><div><h3>Un entraînement pour progresser</h3><p>Pythagore · trois étapes · à essayer en autonomie</p></div><span class="practice-badge">${sponsorBrand('devin')}<br>${simulation?'Simulation · aucun appel':'Création avec API'}</span></div><p class="practice-description">${escape(source)}. L’activité travaille le repérage, la justification et la conclusion.</p><p class="practice-card-status ${error?'is-error':''}" role="status" aria-live="polite">${running?'<span class="practice-loading-mark" aria-hidden="true"></span>':''}${escape(message)}</p>${error?`<p class="practice-error" role="alert">${escape(error)}</p>`:''}<div class="practice-actions">${preview?`<button class="button primary" type="button" data-practice-action="preview">${v.approved?'Ouvrir l’entraînement':'Prévisualiser l’entraînement'}</button>${download?`<a class="button secondary" href="${escape(download)}" download="entrainement-pythagore.html">Télécharger le HTML ↓</a>`:'<button class="button secondary" type="button" data-practice-action="review">Relire et valider</button>'}`:!unavailable?`<button class="button primary" type="button" data-practice-action="start" ${s.busy||running||s.loading?'disabled':''}>${s.busy||running?'Préparation en cours…':v?.status==='failed'?'Réessayer l’entraînement':simulation?'Essayer l’entraînement':'Créer avec Devin'}</button>`:''}${canCreateLive?'<button class="button secondary" type="button" data-practice-action="start-live">Créer avec Devin</button>':''}${s.error&&!running?'<button class="button secondary" type="button" data-practice-action="refresh">Actualiser ↻</button>':''}${session?`<a class="practice-session" href="${escape(session)}" target="_blank" rel="noopener noreferrer">Voir la session Devin ↗</a>`:''}</div><p class="practice-fine">${simulation?'Activité de démonstration préparée localement.'+(v?.configured?'':' L’intégration réelle à Devin attend son accès API.'):'Devin construit l’activité ; le professeur la vérifie avant de la télécharger.'}${ready&&!v.approved?' Prévisualisez puis validez pour autoriser le téléchargement.':''}</p>${v?.events?.length?`<details class="practice-details"><summary>Étapes de la préparation</summary><ol class="practice-events">${v.events.slice(-8).map(event=>`<li><time>${escape(new Date(event.at).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'}))}</time>${escape(event.text)}</li>`).join('')}</ol></details>`:''}`;
  }
  function paint(id){const root=card(id);if(root){const open=root.querySelector('.practice-details')?.open;root.innerHTML=markup(id);if(open&&root.querySelector('.practice-details'))root.querySelector('.practice-details').open=true;bindActions(id,root);}updateDialog(id);}
  function schedule(id){const s=model(id);clearTimeout(s.timer);s.timer=null;if(s.value?.status==='running'&&card(id))s.timer=setTimeout(()=>load(id),1800);}
  async function load(id){const s=model(id);if(s.loading)return;const revision=s.revision;s.loading=true;paint(id);try{const value=await request(id);if(revision===s.revision){s.value=value;s.error='';}}catch(error){if(revision===s.revision)s.error=error.message;}finally{if(revision===s.revision){s.loading=false;paint(id);schedule(id);}}}
  async function start(id,mode='simulation'){const s=model(id);if(s.busy||s.value?.status==='running')return;const revision=s.revision;s.busy=true;s.error='';paint(id);try{const value=await request(id,{mode,retry:s.value?.status==='failed'});if(revision===s.revision)s.value=value;}catch(error){if(revision===s.revision)s.error=error.message;}finally{if(revision===s.revision){s.busy=false;paint(id);schedule(id);}}}
  async function approve(id){const s=model(id);if(s.busy||s.value?.approved)return;const revision=s.revision;s.busy=true;s.error='';paint(id);try{const value=await request(id,{},'/approve');if(revision===s.revision)s.value=value;}catch(error){if(revision===s.revision)s.error=error.message;}finally{if(revision===s.revision){s.busy=false;paint(id);}}}
  function bindActions(id,root){root.querySelectorAll('[data-practice-action]').forEach(button=>button.onclick=()=>{const action=button.dataset.practiceAction;if(action==='start')start(id,model(id).value?.mode==='live'?'live':'simulation');else if(action==='start-live')start(id,'live');else if(action==='refresh')load(id);else openPreview(id);});}
  function ensureDialog(){
    let dialog=document.getElementById('practice-preview-dialog');if(dialog)return dialog;
    dialog=document.createElement('dialog');dialog.id='practice-preview-dialog';dialog.className='practice-preview-dialog';dialog.setAttribute('aria-labelledby','practice-preview-title');
    dialog.innerHTML='<div class="practice-preview-shell"><header class="practice-preview-head"><div><h2 id="practice-preview-title">Entraînement Pythagore</h2><p id="practice-preview-label"></p></div><button class="practice-preview-close" type="button" aria-label="Fermer l’entraînement"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg></button></header><iframe class="practice-preview-frame" id="practice-preview-frame" title="Prévisualisation de l’entraînement Pythagore" sandbox="allow-scripts" referrerpolicy="no-referrer" allow="camera \'none\'; microphone \'none\'; geolocation \'none\'; clipboard-read \'none\'; clipboard-write \'none\'"></iframe><footer class="practice-preview-footer"><p id="practice-preview-note" role="status"></p><div class="practice-actions" id="practice-preview-actions"></div></footer></div>';
    document.body.append(dialog);dialog.querySelector('.practice-preview-close').onclick=()=>dialog.close();
    window.addEventListener('message',event=>{const frame=document.getElementById('practice-preview-frame');if(event.source&&event.source===frame?.contentWindow&&event.data==='calli-practice-escape'&&dialog.open)dialog.close();});
    dialog.addEventListener('close',()=>{const frame=document.getElementById('practice-preview-frame');frame.removeAttribute('src');delete dialog.dataset.practiceJob;});
    return dialog;
  }
  function updateDialog(id){
    const dialog=document.getElementById('practice-preview-dialog');if(!dialog?.open||dialog.dataset.practiceJob!==id)return;
    const s=model(id),v=s.value,simulation=v?.mode!=='live',actions=document.getElementById('practice-preview-actions'),note=document.getElementById('practice-preview-note');
    document.getElementById('practice-preview-label').innerHTML=`${sponsorBrand('devin')} · ${simulation?'Simulation · aucun appel · activité locale de démonstration':'Activité produite avec API · à relire par le professeur'}`;
    note.textContent=s.error||((v?.approved)?'Activité validée. Le fichier fonctionne sans connexion et peut être transmis manuellement.':'Essayez les trois étapes et leurs corrections, puis validez l’activité pour autoriser son téléchargement.');note.setAttribute('role',s.error?'alert':'status');
    const download=v?.approved?localUrl(v.download_url,id,'download'):'';
    actions.innerHTML=download?`<a class="button primary" href="${escape(download)}" download="entrainement-pythagore.html">Télécharger le HTML ↓</a>`:`<button class="button primary" id="practice-approve" type="button" ${s.busy?'disabled':''}>${s.busy?'Validation…':'Valider l’entraînement'}</button>`;
    const approveButton=document.getElementById('practice-approve');if(approveButton)approveButton.onclick=()=>approve(id);
  }
  function openPreview(id){
    const v=model(id).value,url=localUrl(v?.preview_url,id,'preview');if(v?.status!=='ready'||!url)return;
    const dialog=ensureDialog(),frame=document.getElementById('practice-preview-frame');
    if(dialog.dataset.practiceJob!==id||frame.getAttribute('src')!==url)frame.src=url;
    dialog.dataset.practiceJob=id;if(!dialog.open)dialog.showModal();updateDialog(id);
  }
  window.renderPracticeCard=job=>job?.status==='ready'&&job.dossier?`<section class="practice-card" data-practice-job="${escape(job.id)}" aria-label="Entraînement interactif Pythagore">${markup(job.id)}</section>`:'';
  function sourceKey(job){const dossier=job.dossier||{},documents=job.input_context?.documents||dossier.sources||[];return JSON.stringify([job.status,job.mode,job.dossier_h_session_id||job.session_id,dossier.summary,dossier.evidence,dossier.scenes,documents.filter(d=>d&&d.type!=='external'&&!String(d.id||'').startsWith('web-')).map(d=>[d.id,d.title,d.text])]);}
  window.bindPractice=job=>{
    const root=card(job.id);if(!root)return;
    const s=model(job.id),key=sourceKey(job),changed=s.sourceKey!==null&&s.sourceKey!==key,newElement=s.element!==root;
    s.sourceKey=key;s.element=root;
    if(changed){s.revision++;s.value=null;s.error='';s.loading=false;s.busy=false;clearTimeout(s.timer);s.timer=null;const dialog=document.getElementById('practice-preview-dialog');if(dialog?.open&&dialog.dataset.practiceJob===job.id)dialog.close();paint(job.id);}
    bindActions(job.id,root);
    if(!s.loading&&(!s.value||changed||newElement))load(job.id);else schedule(job.id);
  };
})();
