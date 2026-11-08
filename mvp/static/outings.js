/* One class, one destination, one date. All progress comes from server jobs. */
(() => {
  const state = {options:null, job:null, poll:null, objectiveTimer:null, objectivePending:null, saving:false, error:'', notice:'', draft:{}, revision:0, objectiveDirty:false, activeTab:'dossier', setupToken:0, liveOpenedJob:null, liveTimer:null, liveSignatures:{}, livePhase:'prepare', operationsPanel:'families', operationsFamily:null, operationsAutoRun:null, operationsStarting:false, operationsDetailSignature:'', presentationAuto:false, presentationRun:null, presentationSeen:null, presentationMoment:null, operationsMessageKind:null, operationsMessageId:null, operationsRenderedPanel:null, completeDemoRequested:false, completeDemoJob:null};
  try { state.draft = JSON.parse(localStorage.getItem('new-pronote-outing-draft') || '{}'); } catch {}
  const node = id => document.getElementById(id);
  const html = value => esc(value);
  const currency = value => value == null || value === '' ? 'À confirmer' : new Intl.NumberFormat('fr-FR', {style:'currency', currency:'EUR'}).format(Number(value));
  const formatDate = value => { const d = new Date(String(value).slice(0,10)+'T12:00:00'); return Number.isNaN(d.getTime()) ? String(value || '') : d.toLocaleDateString('fr-FR', {weekday:'long',day:'numeric',month:'long'}); };
  const stamp = value => { const d = new Date(value); return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit',second:'2-digit'}); };
  const isBusy = () => !!state.job && ['preparing','running','queued'].includes(state.job.status);
  const isOperationsBusy = () => state.job?.operations?.status==='running';
  const shouldPoll = () => isBusy()||isOperationsBusy();
  const link = (url,label) => { try { const u=new URL(url); return ['http:','https:'].includes(u.protocol)?`<a href="${html(u.href)}" target="_blank" rel="noopener noreferrer">${html(label)} ↗</a>`:''; } catch {return '';} };
  const saveDraft = () => { try {localStorage.setItem('new-pronote-outing-draft',JSON.stringify(state.draft));} catch {} };
  function serverClock(job){return Math.max(0,...[job.updated_at,job.completed_at,job.dossier?.updated_at,job.operations?.updated_at,job.operations?.started_at,job.operations?.completed_at,...(job.operations?.events||[]).map(event=>event.at),...(job.events||[]).map(event=>event.at),...(job.tasks||[]).flatMap(task=>[task.started_at,task.finished_at]),...(job.tool_calls||[]).flatMap(call=>[call.started_at,call.ended_at])].map(value=>Date.parse(value)||0));}
  function adoptJob(incoming){
    if(state.job?.id===incoming.id){
      const currentRevision=state.job.revision??0,nextRevision=incoming.revision??0;
      if(nextRevision<currentRevision)return false;
      if(nextRevision===currentRevision){
        if(serverClock(incoming)<serverClock(state.job))return false;
        if(!isBusy()&&['preparing','running','queued'].includes(incoming.status))return false;
      }
    }
    state.job=incoming;return true;
  }
  window.renderOutingsPage = () => `<div class="outings-page" id="outings-page">
    <header class="outing-heading"><div><h1>Sorties scolaires</h1><p>Préparez le trajet, le budget et les documents de votre sortie.</p></div></header>
    <div class="outing-feedback" id="outing-feedback" aria-live="polite"></div>
    <section class="outing-setup" aria-labelledby="outing-setup-title"><div class="outing-section-head"><h2 id="outing-setup-title">Votre sortie</h2><span class="outing-source-label" id="outing-roster-label">Chargement de la liste de classe…</span></div>
      <form id="outing-form" class="outing-form" aria-busy="true"><div class="outing-form-grid"><label>Classe<select name="class_id" id="outing-class" required disabled><option>Chargement…</option></select></label><label class="outing-destination-label">Destination<select name="destination_id" id="outing-destination" required disabled><option>Chargement…</option></select></label><label>Date<input type="date" name="date" id="outing-date" required disabled></label><label>Heure de visite<input type="time" name="visit_time" id="outing-time" required disabled></label></div>
      <div class="outing-objective"><div class="outing-objective-content"><div class="outing-objective-label"><label for="outing-objective">Objectif pédagogique <span class="outing-optional">(facultatif)</span></label><span id="outing-objective-status" role="status">Brouillon local</span></div><textarea id="outing-objective" rows="2" maxlength="3000" aria-describedby="outing-objective-help" placeholder="Ex. Observer, comparer et préparer un carnet de visite…"></textarea><p id="outing-objective-help">Vous pouvez continuer à l’écrire pendant la préparation.</p></div></div>
      <details class="outing-settings"><summary>Durée, accompagnateurs et budget <span aria-hidden="true">⌄</span></summary><div class="outing-form-grid outing-budget-inputs"><label>Durée de visite (min)<input name="duration_minutes" type="number" min="30" max="360" step="1" required disabled></label><label>Accompagnateurs<input name="adults" type="number" min="1" max="10" required disabled></label><label>Transport total (€)<input name="transport_total" type="number" min="0" max="100000" step="0.01" required disabled><small>Devis à confirmer</small></label><label>Financement prévu (€)<input name="subsidy" type="number" min="0" max="100000" step="0.01" required disabled></label></div></details>
      <div class="outing-form-bottom"><p id="outing-mode-note">Le trajet, le budget et les documents seront réunis ici.</p><div class="outing-form-actions"><button class="button secondary" id="outing-full-demo" type="button" disabled>${icon('play')} Démo complète</button><button class="button primary" id="outing-start" type="submit" disabled>${icon('play')} Préparer la sortie</button></div></div></form>
    </section>
    <section class="outing-work outing-work-compact" id="outing-work" aria-label="Suivi de la préparation" hidden><span class="outing-sr-only" id="outing-job-state" role="status"></span><div id="outing-live-launch"></div></section>
    <section class="outing-results" id="outing-results" aria-labelledby="outing-results-title" hidden><div class="outing-section-head"><h2 id="outing-results-title">Votre dossier</h2><span class="outing-results-count" id="outing-results-count"></span></div><div id="outing-result-content"></div></section>
    <details class="outing-trace" id="outing-trace" hidden><summary>${icon('clock')} Sources et détails <span>⌄</span></summary><div id="outing-trace-content"></div></details>
    <p class="outing-footnote">Démonstration · liste de classe et modèle fictifs. Les réservations et l’envoi aux familles restent à votre charge.</p>
  </div>`;

  const parallelTasks=[
    {id:'visit',title:'Vérifier la visite',tool:'Linkup · site officiel',icon:'search',text:'Horaires, tarif scolaire et conditions d’accueil.'},
    {id:'route',title:'Préparer le déplacement',tool:'Itinéraire + agenda',icon:'pin',text:'Trajet, heure de départ et éventuels conflits.'},
    {id:'roster',title:'Rassembler le dossier',tool:'Liste de classe + modèle',icon:'folder',text:'Effectif, pièces à prévoir et champs à compléter.'}
  ];
  function taskState(task){
    const status=task?.status||'idle';
    return ['ready','completed','done','succeeded'].includes(status)?'done':['running','preparing'].includes(status)?'running':['failed','error','partial','cancelled'].includes(status)?'error':'pending';
  }
  function outingTask(job,id){
    const tasks=Array.isArray(job?.tasks)?job.tasks:Object.entries(job?.tasks||{}).map(([id,t])=>({id,...t}));
    return tasks.find(task=>task.id===id);
  }
  function parallelFlow(job){
    const branches=parallelTasks.map(def=>({def,task:outingTask(job,def.id)}));
    const running=branches.filter(({task})=>taskState(task)==='running').length;
    const done=branches.filter(({task})=>taskState(task)==='done').length;
    const failed=branches.filter(({task})=>taskState(task)==='error').length;
    const dossier=outingTask(job,'dossier'),mergeState=taskState(dossier);
    const active=running>0||mergeState==='running';
    const orchestrationStarted=!!job&&(job.tool_calls||[]).length===0&&['preparing','running','queued'].includes(job.status);
    const model=String(job?.agent?.model||job?.model||'');
    const executor=model.startsWith('holo4')?'Holo4':'Calli';
    const originLabel=job?.status==='preparing'&&job?.agent?.provider_status==='queued'?'Holo4 attend un créneau':running>1?`${running} outils en parallèle`:running===1?'1 outil en cours':done===3?'Les trois résultats sont réunis':failed?'Des résultats sont à vérifier':orchestrationStarted?'Holo4 prépare ses appels':job?'En attente du prochain appel':'Un projet, des outils à disposition';
    const detail=mergeState==='running'?'Les résultats alimentent le dossier administratif.':mergeState==='done'?'Le dossier et le courrier sont prêts à relire.':mergeState==='error'?'Le brouillon reste disponible avec les points à vérifier.':'Le trajet, les tarifs et l’effectif alimenteront le même dossier.';
    const mergeLabel=mergeState==='running'?`${executor} remplit le dossier`:mergeState==='done'?'Le dossier est prérempli':mergeState==='error'?'Le dossier demande une vérification':'Tout se rejoindra dans le dossier';
    const branchPaths=['M500 0V10Q500 18 490 18H177Q167 18 167 27V38','M500 0V38','M500 0V10Q500 18 510 18H823Q833 18 833 27V38'];
    const joinPaths=['M167 0V10Q167 18 177 18H490Q500 18 500 27V38','M500 0V38','M833 0V10Q833 18 823 18H510Q500 18 500 27V38'];
    const connectors=(paths,join=false)=>`<svg class="outing-flow-connectors ${join?'is-join':'is-split'}" viewBox="0 0 1000 38" preserveAspectRatio="none" aria-hidden="true">${branches.map(({task},index)=>{const status=taskState(task),flow=join&&mergeState==='running'&&status==='done'?'running':status;return `<path class="outing-flow-track is-${status}" d="${paths[index]}" vector-effect="non-scaling-stroke"/><path class="outing-flow-stream is-${flow}" d="${paths[index]}" vector-effect="non-scaling-stroke"/>`;}).join('')}</svg>`;
    return `<div class="outing-parallel ${active?'is-active':''}" data-parallel-state="${running?'preparing':mergeState}"><div class="outing-flow-origin"><span class="outing-parallel-symbol" aria-hidden="true">∥</span><div><strong>Vous préparez la visite.</strong><small>${sponsorBrand('hcompany',{label:'Holo4'})} choisit et appelle les outils.</small></div><span class="outing-flow-live ${active?'is-active':''}" role="status"><i></i>${originLabel}</span></div>${connectors(branchPaths)}<div class="outing-tasks">${taskCards(job)}</div>${connectors(joinPaths,true)}<div class="outing-convergence is-${mergeState}"><span class="outing-merge-icon" aria-hidden="true">${icon(mergeState==='done'?'check':'file')}</span><div><span class="overline">LES RÉSULTATS SE REJOIGNENT</span><strong>${mergeLabel}</strong><p>${detail}</p></div><div class="outing-merge-outputs" aria-label="Résultats préparés"><span class="${job?.route?'is-done':''}">${icon('pin')}Itinéraire</span><span class="${job?.budget?.complete?'is-done':''}">${icon('users')}Budget</span><span class="${mergeState==='done'?'is-done':''}">${icon('file')}Dossier</span></div></div></div>`;
  }
  function taskCards(job) {
    return parallelTasks.map((def,index)=>{
      const task=outingTask(job,def.id),baseState=taskState(task);
      const requested=!!task?.requested_at||executionList(job).some(entry=>entry.task_id===def.id);
      const status=baseState==='pending'&&requested?'requested':baseState;
      const label={done:'Terminé',running:'En cours',error:'À vérifier',requested:'Appel reçu',pending:job?'Pas encore appelé':'Disponible'}[status];
      return `<article class="outing-task is-${status}" data-task="${def.id}" aria-label="${html(def.title)} : ${label}"><div class="outing-task-top"><span class="outing-task-icon">${icon(status==='done'?'check':def.icon)}</span><span class="outing-task-state"><i></i>${label}</span></div><span class="outing-task-lane" aria-hidden="true">0${index+1}</span><h3>${def.title}</h3><p>${html(task?.summary||task?.error||def.text)}</p><span class="outing-task-tool">${def.id==='visit'?sponsorBrand('linkup',{label:task?.provider||def.tool}):html(task?.provider||def.tool)}</span></article>`;
    }).join('');
  }
  const orchestrationTools=[
    {name:'search_museum_visit',task:'visit',title:'Rechercher la visite',provider:'Linkup · site officiel',icon:'search'},
    {name:'prepare_transport_and_calendar',task:'route',title:'Calculer le trajet',provider:'OSRM · agenda local',icon:'pin'},
    {name:'read_class_and_template',task:'roster',title:'Lire la classe et le modèle',provider:'Dossier de démonstration',icon:'folder'}
  ];
  const callNames={search_museum_visit:'Rechercher la visite',prepare_transport_and_calendar:'Calculer le trajet et vérifier l’agenda',read_class_and_template:'Lire la classe et le modèle',wait_for_outing_results:'Attendre les résultats demandés',get_outing_progress:'Consulter l’avancement',read_outing_evidence:'Lire les résultats et leurs sources',fill_administrative_dossier:'Remplir le dossier administratif'};
  function executionList(job){
    const entries=job?.executions||job?.tool_executions||[];
    return Array.isArray(entries)?entries:Object.entries(entries).map(([id,value])=>({id,...value}));
  }
  function executionFor(job,def){
    const list=executionList(job);
    return list.slice().reverse().find(item=>(item.tool_name||item.name)===def.name||item.task_id===def.task);
  }
  function executionState(execution,call,task){
    if(execution)return execution.status==='requested'?'requested':taskState(execution);
    if(!call)return 'pending';
    if(task&&taskState(task)!=='pending')return taskState(task);
    return call.status==='failed'?'error':call.status==='running'?'requested':'requested';
  }
  function callSummary(call,execution){
    const succeeded=taskState(call)==='done';
    const collection=orchestrationTools.some(def=>def.name===call.name);
    const text=call.status==='failed'?call.result_summary||'L’appel a échoué.':collection&&succeeded?'L’outil a reçu la demande. Son exécution est suivie ci-dessus.':call.name==='wait_for_outing_results'?(succeeded?'Les résultats disponibles ont été renvoyés à Holo4.':'Holo4 attend les réponses des outils qu’il a appelés.'):call.name==='read_outing_evidence'&&succeeded?'Les résultats et leurs sources ont été transmis à Holo4.':call.name==='fill_administrative_dossier'&&succeeded?'Le dossier et le courrier ont été préremplis.':call.status==='running'?'L’appel est en cours de traitement.':'';
    return `${text?`<p>${html(text)}</p>`:''}${call.result_summary?`<details class="outing-call-response"><summary>Voir la réponse de l’outil</summary><pre>${html(call.result_summary)}</pre></details>`:''}`;
  }
  function durationLabel(start,end){
    const a=Date.parse(start),b=end?Date.parse(end):Date.now();
    if(!Number.isFinite(a)||!Number.isFinite(b))return '';
    const seconds=Math.max(0,(b-a)/1000);
    if(end&&seconds<1)return seconds<.001?'< 1 ms':Math.round(seconds*1000).toLocaleString('fr-FR')+' ms';
    return seconds<60?seconds.toLocaleString('fr-FR',{maximumFractionDigits:1})+' s':Math.floor(seconds/60)+' min '+Math.floor(seconds%60)+' s';
  }
  function parallelPeak(job){
    const points=[];
    for(const entry of executionList(job)){
      const start=Date.parse(entry.started_at),end=Date.parse(entry.ended_at||entry.finished_at);
      if(Number.isFinite(start)){points.push([start,1]);if(Number.isFinite(end))points.push([end,-1]);}
    }
    points.sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
    let current=0,peak=0;for(const [,change]of points){current+=change;peak=Math.max(peak,current);}
    return peak;
  }
  function orchestrationPanel(job){
    const calls=job?.tool_calls||[],executions=executionList(job);
    const active=job?.parallel?.active_count??executions.filter(item=>taskState(item)==='running').length;
    const peak=job?.parallel?.max_concurrent??parallelPeak(job),hasCalls=calls.length>0;
    const allCollected=orchestrationTools.every(def=>taskState(outingTask(job,def.task))==='done');
    const filling=calls.some(call=>call.name==='fill_administrative_dossier'&&call.status==='running');
    const busy=!!job&&['preparing','running','queued'].includes(job.status);
    const agentLabels={provider_queued:'Session Holo4 en file d’attente',planning:'Holo4 prépare ses appels',waiting_for_tool_calls:'Holo4 prépare ses appels',collecting:'Holo4 lance ses outils',waiting_for_results:'Holo4 attend les résultats',results_available:'Résultats disponibles pour Holo4',reviewing:'Holo4 examine les résultats',filling:'Holo4 remplit le dossier',completed:'Préparation terminée',partial:'Préparation à compléter',failed:'Préparation à reprendre'};
    const status=active>1?active+' outils en parallèle':active===1?'Un outil s’exécute':agentLabels[job?.agent?.status]||(!job?'À lancer':!hasCalls&&busy?'En attente des appels de Holo4':filling?'Holo4 remplit le dossier':busy&&allCollected?'Holo4 réunit les résultats':busy?'Holo4 poursuit la préparation':'Exécution terminée');
    return `<section class="outing-orchestration" aria-labelledby="outing-orchestration-title"><header class="outing-orchestration-head"><span class="outing-orchestration-mark" aria-hidden="true">${sponsorBrand('hcompany',{iconOnly:true})}</span><div><span class="overline">LES APPELS DE L’AGENT, EN DIRECT</span><h3 id="outing-orchestration-title">Holo4 aux commandes.</h3><p>Les outils démarrent lorsqu’Holo4 les appelle. Chaque réponse garde son état et sa source.</p></div><span class="outing-orchestration-status ${active?'is-active':''}" role="status"><i></i>${html(status)}</span></header><div class="outing-execution-grid">${orchestrationTools.map(def=>{
      const execution=executionFor(job,def),call=calls.slice().reverse().find(item=>item.name===def.name),task=outingTask(job,def.task);
      const stateName=executionState(execution,call,task),requested=!!(execution||call);
      const requestedAt=execution?.requested_at||call?.started_at,startedAt=execution?.started_at||(requested?task?.started_at:null),endedAt=execution?.ended_at||execution?.finished_at||(requested?task?.finished_at:null);
      const label={pending:job&&!busy?'Non appelé':'À disposition',requested:'Appel reçu',running:'En cours',done:'Résultat reçu',error:'À vérifier'}[stateName]||'Appel reçu';
      const summary=execution?.error||execution?.result_summary||(requested?task?.error||task?.summary:'')||(stateName==='running'?'L’outil travaille ; Holo4 peut appeler les autres outils.':requested?'L’appel a été reçu. Son exécution est suivie ici.':job&&!busy?'Holo4 n’a pas lancé cet outil pendant cette préparation.':'Holo4 n’a pas encore appelé cet outil.');
      const elapsed=durationLabel(startedAt,endedAt);
      return `<article class="outing-execution is-${stateName}" data-execution-task="${def.task}"><div class="outing-execution-top"><span>${icon(stateName==='done'?'check':def.icon)}</span><span class="outing-execution-state"><i></i>${label}</span></div><h4>${def.title}</h4><code>${def.name}()</code><p class="outing-execution-summary">${html(summary)}</p><div class="outing-execution-track" aria-hidden="true"><i class="${requested?'is-filled':''}"></i><i class="${startedAt?'is-filled':''}"></i><i class="${endedAt?'is-filled':''}"></i></div><dl class="outing-execution-times"><div><dt>Appelé</dt><dd>${requestedAt?stamp(requestedAt):'—'}</dd></div><div><dt>Démarré</dt><dd>${startedAt?stamp(startedAt):'—'}</dd></div><div><dt>Terminé</dt><dd>${endedAt?stamp(endedAt):'—'}</dd></div></dl><footer><span>${def.task==='visit'?sponsorBrand('linkup')+' · site officiel':html(def.provider)}</span>${elapsed?`<strong>${elapsed}${endedAt?'':' écoulées'}</strong>`:''}</footer></article>`;
    }).join('')}</div><div class="outing-orchestration-bottom"><p>${peak>1?`${icon('check')}<span>Chevauchement réel confirmé : jusqu’à <strong>${peak} outils</strong> ont travaillé en même temps.</span>`:active>0?`${icon('clock')}<span>Les exécutions et leurs horaires permettent de voir quels appels se chevauchent réellement.</span>`:`${icon('link')}<span>Les appels de collecte, d’attente et de remplissage apparaissent au fil de l’exécution.</span>`}</p><span>${calls.length} appel${calls.length>1?'s':''} reçu${calls.length>1?'s':''}</span></div><div class="outing-visible-calls" aria-label="Tous les appels reçus de Holo4">${hasCalls?`<ol>${calls.map((call,index)=>{
      const callState=taskState(call),stateLabel={done:'Réponse renvoyée',running:'Appel en cours',error:'Échec',pending:'Appel reçu'}[callState];
      const linked=executions.find(item=>item.tool_call_id===call.id||item.id===call.execution_id||(item.tool_name||item.name)===call.name);
      return `<li class="is-${callState}"><span class="outing-call-number">${String(index+1).padStart(2,'0')}</span><div class="outing-call-description"><strong>${html(callNames[call.name]||call.name)}</strong><code>${html(call.name)}()</code>${callSummary(call,linked)}</div><div class="outing-call-meta"><span>${stateLabel}</span><time>${stamp(call.started_at)}</time>${call.duration_ms!=null?`<small>${durationLabel(call.started_at,call.ended_at)||'—'}</small>`:''}${linked?'<small>Exécution suivie ci-dessus</small>':''}</div></li>`;
    }).join('')}</ol>`:'<p class="outing-calls-empty">Les appels apparaîtront dès qu’Holo4 aura choisi ses premiers outils.</p>'}</div></section>`;
  }
  const liveTools=[...orchestrationTools,
    {name:'wait_for_outing_results',title:'Attendre les résultats',icon:'clock'},
    {name:'read_outing_evidence',title:'Lire les résultats',icon:'link'},
    {name:'fill_administrative_dossier',title:'Préremplir le dossier',icon:'file'}
  ];
  const operationTools=[
    {name:'prepare_parent_messages_demo',title:'Préparer les mails et liens Stripe',icon:'message',brand:'gmail',demo:true},
    {name:'simulate_parent_responses_demo',title:'Traiter les réponses simulées',icon:'check',brand:'gmail',demo:true},
    {name:'prepare_targeted_reminders_demo',title:'Relancer les non-répondants',icon:'clock',brand:'gmail',demo:true},
    {name:'prepare_photo_permissions_demo',title:'Préparer les autorisations photo',icon:'file',brand:'google_docs',demo:true},
    {name:'check_equipment_demo',title:'Vérifier le matériel',icon:'search',brand:'google_calendar',demo:true},
    {name:'reserve_equipment_demo',title:'Réserver le matériel en démo',icon:'folder',brand:'google_calendar',demo:true},
    {name:'prepare_administration_demo',title:'Constituer le dossier administratif',icon:'file',brand:'google_docs',demo:true}
  ];
  Object.assign(callNames,Object.fromEntries(operationTools.map(tool=>[tool.name,tool.title])));
  const allLiveTools=[...liveTools,...operationTools];
  function operationCalls(job){
    const ops=job?.operations,trace=ops?.trace_id||ops?.session_id;
    if(!trace)return [];
    return (job?.tool_calls||[]).filter(call=>operationTools.some(tool=>tool.name===call.name)&&call.session_id===trace);
  }
  function operationContext(job){
    const sid=job?.operations?.trace_id||job?.operations?.session_id;return sid?(job?.tool_calls||[]).filter(call=>call.session_id===sid&&call.name==='read_outing_evidence').at(-1):null;
  }
  function preparationCalls(job){
    return (job?.tool_calls||[]).filter(call=>!operationTools.some(tool=>tool.name===call.name)&&(!job?.session_id||!call.session_id||call.session_id===job.session_id));
  }
  function operationsStatus(job){
    const ops=job?.operations;
    if(!ops)return 'La suite attend votre lancement';
    if(ops.stale)return 'Objectif modifié · démonstration à relancer';
    if(ops.status==='running'&&ops.provider_status==='queued')return 'Holo4 attend un créneau';
    if(ops.status==='ready')return 'La démonstration est préparée';
    if(ops.status==='failed')return 'Démonstration à reprendre';
    const active=operationCalls(job).findLast(call=>call.status==='running');
    return active?callNames[active.name]:'Holo4 orchestre les actions simulées';
  }
  function operationRows(){return operationTools.map(def=>`<article id="outing-live-tool-${def.name}" class="outing-live-tool is-pending" data-live-name="${def.name}"><span class="outing-live-tool-icon" aria-hidden="true">${def.brand?sponsorBrand(def.brand,{iconOnly:true}):icon(def.icon)}</span><div class="outing-live-tool-main"><div><strong>${def.title}</strong><span class="outing-live-tool-state" data-live-field="state">Pas encore appelé</span></div><code>${def.name}()</code>${def.task==='visit'?`<div class="outing-live-provider">${sponsorBrand('linkup')} · site officiel</div>`:''}<p data-live-field="summary">Action de démonstration disponible.</p></div><div class="outing-live-tool-time"><span data-live-field="duration">—</span><small data-live-field="time">—</small><small data-live-field="count"></small></div></article>`).join('');}
  function operationsMarkup(){return `<div class="outing-live-body outing-live-operations-body" id="outing-live-operations-body" hidden><section class="outing-live-functions"><div class="outing-live-section-heading"><h3>Les actions que Holo4 orchestre</h3><span id="outing-ops-call-count">0 appel reçu</span></div><div class="outing-live-call-stack outing-ops-call-stack">${operationRows()}</div><div class="outing-live-concurrency"><span id="outing-ops-context">Contexte à lire · read_outing_evidence()</span><span>Effets simulés</span></div></section><section class="outing-ops-output"><div class="outing-ops-presentation-bar"><div class="outing-ops-integrations"><span>Interfaces simulées</span>${['gmail','google_docs','google_calendar','stripe'].map(id=>sponsorBrand(id,{iconOnly:true})).join('')}</div><button type="button" id="outing-ops-auto" aria-pressed="false">Présentation auto</button></div><div id="outing-ops-moment" class="outing-ops-moment"><span>${icon('clock')}</span><div><small>DÉMONSTRATION EN DIRECT</small><strong id="outing-ops-moment-title">Les résultats apparaissent à leur réception.</strong></div><span id="outing-ops-moment-badge">EN ATTENTE</span></div><div class="outing-ops-summary"><div class="outing-ops-counter is-confirmed"><span>Confirmations</span><strong id="outing-ops-confirmed">—</strong><small>réponses simulées</small></div><div class="outing-ops-counter is-pending"><span>À relancer</span><strong id="outing-ops-pending">—</strong><small>sans réponse</small></div><div class="outing-ops-counter is-declined"><span>Refus</span><strong id="outing-ops-declined">—</strong><small>respectés</small></div></div><div class="outing-family-board"><header><strong>La classe répond.</strong><span id="outing-ops-family-total">Données fictives</span></header><div id="outing-ops-families" class="outing-family-grid"><p>Les familles fictives apparaîtront à la préparation des messages.</p></div><div class="outing-family-legend"><span><i class="is-confirmed"></i>Confirmé</span><span><i class="is-pending"></i>Sans réponse</span><span><i class="is-declined"></i>Refusé</span></div></div><div id="outing-ops-equipment-mini" class="outing-ops-equipment-mini"><span class="outing-equipment-mini-icon">${sponsorBrand('google_calendar',{iconOnly:true})}</span><div><strong id="outing-ops-equipment-title">Matériel à vérifier</strong><small id="outing-ops-equipment-note">Stock fictif · aucune réservation réelle</small></div><b id="outing-ops-equipment-units">—</b></div><div class="outing-ops-detail-tabs" role="tablist" aria-label="Résultats de démonstration">${[['families','Familles'],['payments','Collecte Stripe'],['photo','Photo'],['equipment','Matériel'],['admin','Administration']].map(([id,label])=>`<button type="button" role="tab" aria-selected="${id==='families'}" data-ops-panel="${id}" id="outing-ops-tab-${id}" aria-controls="outing-ops-detail">${label}</button>`).join('')}</div><div id="outing-ops-detail" class="outing-ops-detail" role="tabpanel" aria-labelledby="outing-ops-tab-families"></div><div id="outing-ops-stale" class="outing-ops-stale" hidden>Votre objectif a changé. Relancez la démonstration pour mettre les documents en cohérence.</div></section></div>`;}
  function selectLivePhase(phase){
    state.livePhase=phase;
    const ops=phase==='operations';
    if(node('outing-live-preparation-body'))node('outing-live-preparation-body').hidden=ops;
    if(node('outing-live-operations-body'))node('outing-live-operations-body').hidden=!ops;
    node('outing-live-dialog')?.classList.toggle('is-operations',ops);
    for(const button of document.querySelectorAll('[data-live-phase]'))button.setAttribute('aria-selected',String(button.dataset.livePhase===phase));
    updateLiveDialog();
  }
  function operationResultSummary(job,name){
    const c=job?.operations?.counts||{};return {prepare_parent_messages_demo:`${c.initial_messages??0} invitations avec liens Stripe fictifs · aucun envoi`,simulate_parent_responses_demo:`${c.confirmed??0} confirmations · ${c.declined??0} refus · ${c.pending??0} sans réponse`,prepare_targeted_reminders_demo:`${c.reminders??0} relances ciblées simulées`,prepare_photo_permissions_demo:`${c.photo_authorized??0} accords · ${c.photo_refused??0} refus respectés`,check_equipment_demo:'Stock fictif vérifié · conflits identifiés',reserve_equipment_demo:`${c.equipment_reserved_units??0} unités allouées en simulation`,prepare_administration_demo:`${c.admin_prepared_documents??0} documents préparés · validation humaine requise`}[name]||'';
  }
  function pauseOperationsPresentation(){
    state.presentationAuto=false;
    updatePresentationControl();
  }
  function updatePresentationControl(){
    const button=node('outing-ops-auto');if(!button)return;
    button.setAttribute('aria-pressed',String(state.presentationAuto));
    button.disabled=!isOperationsBusy();
    button.textContent=isOperationsBusy()?(state.presentationAuto?'Présentation auto · ON':'Reprendre l’auto'):'Navigation libre';
    button.title=state.presentationAuto?'Un clic sur un résultat suspend la présentation automatique.':'Le focus suit uniquement les nouveaux résultats reçus de Holo4.';
  }
  function syncOperationsPresentation(ops){
    const run=ops?state.job.id+':'+(ops.run_id||ops.started_at||''):null,c=ops?.counts||{};
    const snapshot={invitations:c.initial_messages||0,confirmations:c.confirmation_messages||0,reminders:c.reminders||0,photo:(ops?.photo?.decisions||[]).length,equipment:(ops?.equipment?.items||[]).length,reserved:(ops?.equipment?.reservations||[]).length,admin:(ops?.admin?.documents||[]).length};
    if(run!==state.presentationRun){
      state.presentationRun=run;state.presentationMoment=null;
      state.presentationSeen=state.presentationAuto?{}:snapshot;
      state.operationsMessageKind=null;state.operationsMessageId=null;
    }
    const previous=state.presentationSeen||snapshot,changed=key=>snapshot[key]>0&&snapshot[key]>(previous[key]||0);
    let moment=null;
    // Mail results take visual priority if Holo4 returns independent branches together.
    if(changed('reminders'))moment={key:'reminders',panel:'families',kind:'reminder',brand:'gmail',title:snapshot.reminders+' relances ciblées, aucun refus relancé.',badge:'RELANCES SIMULÉES'};
    else if(changed('confirmations'))moment={key:'confirmations',panel:'families',kind:'confirmation',brand:'gmail',title:snapshot.confirmations+' confirmations automatiques préparées.',badge:'RÉPONSES SIMULÉES'};
    else if(changed('invitations'))moment={key:'invitations',panel:'families',kind:'invitation',brand:'gmail',title:snapshot.invitations+' invitations apparaissent dans la boîte d’envoi.',badge:'MAILS NON ENVOYÉS'};
    else if(changed('reserved'))moment={key:'reserved',panel:'equipment',brand:'google_calendar',title:(c.equipment_reserved_units||0)+' unités affectées, solution papier incluse.',badge:'RÉSERVATION SIMULÉE'};
    else if(changed('admin'))moment={key:'admin',panel:'admin',brand:'google_docs',title:snapshot.admin+' documents administratifs sont prêts à relire.',badge:'BROUILLONS PRÉPARÉS'};
    else if(changed('photo'))moment={key:'photo',panel:'photo',brand:'google_docs',title:(c.photo_authorized||0)+' accords photo ; '+(c.photo_refused||0)+' refus respectés.',badge:'AUTORISATIONS FICTIVES'};
    else if(changed('equipment'))moment={key:'equipment',panel:'equipment',brand:'google_calendar',title:'Stock vérifié : une solution au manque de tablettes.',badge:'INVENTAIRE FICTIF'};
    state.presentationSeen=snapshot;
    if(moment){
      state.presentationMoment=moment;
      if(state.presentationAuto&&state.livePhase==='operations'){
        state.operationsPanel=moment.panel;state.operationsMessageKind=moment.kind||null;state.operationsMessageId=null;state.operationsFamily=null;
        node('outing-ops-detail').scrollTop=0;
      }
    }
    const current=state.presentationMoment,box=node('outing-ops-moment');
    liveSetText(node('outing-ops-moment-title'),current?.title||(ops?.status==='ready'?'Tous les résultats sont disponibles.':ops?.provider_status==='queued'?'Holo4 attend un créneau, les résultats suivront.':'Les résultats apparaissent à leur réception.'));
    liveSetText(node('outing-ops-moment-badge'),current?.badge||(ops?.status==='ready'?'DÉMO TERMINÉE':'EN ATTENTE'));
    const mark=box?.querySelector(':scope > span:first-child'),brand=current?.brand;
    if(mark&&mark.dataset.brand!==(brand||'')){mark.dataset.brand=brand||'';mark.innerHTML=brand?sponsorBrand(brand,{iconOnly:true}):icon('clock');}
    if(box)liveFlash(box,JSON.stringify(current));
    if(ops?.status!=='running'&&!state.operationsStarting)state.presentationAuto=false;
    updatePresentationControl();
  }
  function operationsDetail(ops){
    const counts=ops?.counts||{},families=ops?.families||[];
    if(state.operationsPanel==='families'){
      const messages=ops?.messages||[],familyMessages=state.operationsFamily?messages.filter(message=>message.recipient_id===state.operationsFamily):messages,selected=state.operationsMessageKind?familyMessages.filter(message=>message.kind===state.operationsMessageKind):familyMessages;
      const message=selected.find(item=>item.id===state.operationsMessageId)||selected.at(-1),family=families.find(item=>item.id===state.operationsFamily),reminders=messages.filter(item=>item.kind==='reminder');
      return `<header class="outing-ops-detail-head"><strong>${sponsorBrand('gmail')} <span>Boîte d’envoi simulée</span></strong><span>${messages.length} message(s) préparé(s)</span></header><div class="outing-message-counts">${[['invitation',counts.initial_messages,'invitations'],['confirmation',counts.confirmation_messages,'confirmations'],['reminder',counts.reminders,'relances ciblées'],['payment_reminder',(ops?.messages||[]).filter(m=>m.kind==='payment_reminder').length,'rappels de paiement']].map(([kind,count,label])=>`<button type="button" data-ops-message-kind="${kind}" aria-pressed="${state.operationsMessageKind===kind}">${count??0} ${label}</button>`).join('')}</div><div class="outing-mail-stream">${selected.slice(-3).reverse().map(item=>`<button type="button" data-ops-message="${html(item.id)}" class="${message?.id===item.id?'is-selected':''}" style="--arrival-index:${Math.max(0,selected.length-selected.indexOf(item)-1)}"><span>${sponsorBrand('gmail',{iconOnly:true})}</span><strong>${html(item.recipient_label)}</strong><small>${html({invitation:'Invitation',confirmation:'Confirmation',reminder:'Relance ciblée',payment_reminder:'Rappel de paiement'}[item.kind])}</small></button>`).join('')}</div>${message?`<article class="outing-demo-message"><header><span class="outing-message-kind">${html({invitation:'Invitation',confirmation:'Confirmation automatique',reminder:'Relance ciblée',payment_reminder:'Rappel de paiement'}[message.kind]||'Message')}</span><span>SIMULÉ · NON ENVOYÉ</span></header><h4>${html(message.subject)}</h4><p class="outing-message-recipient">Pour ${html(message.recipient_label||family?.label||'une famille fictive')} · ${html(message.recipient)}</p><pre>${html(message.body)}</pre></article>`:'<div class="outing-ops-empty">Holo4 préparera les messages ici. Aucun accès à une boîte mail.</div>'}${reminders.length?`<div class="outing-reminder-targets"><strong>Relances ciblées · sans réponse uniquement</strong><div>${reminders.map(item=>`<button type="button" data-ops-recipient="${html(item.recipient_id)}">${html(item.recipient_label)}</button>`).join('')}</div></div>`:''}<p class="outing-ops-explain">Les refus ne reçoivent pas de relance de non-réponse. Cliquez sur une famille pour voir son dernier message.</p>`;
    }
    if(state.operationsPanel==='payments'){
      const payments=ops?.payments||{},entries=payments.entries||[],active=entries.filter(e=>e.status!=='cancelled'),total=active.reduce((sum,e)=>sum+Math.round(Number(e.amount)*100),0)/100;
      return `<header class="outing-ops-detail-head"><strong>${sponsorBrand('stripe')} <span>Collecte de la sortie</span></strong><span>LIENS SIMULÉS</span></header><div class="outing-photo-counts"><span><b>${active.length}</b> règlements attendus</span><span><b>${currency(total)}</b> à collecter</span><span><b>${currency(payments.actual_collected||0)}</b> encaissé</span></div><p class="outing-ops-explain">Un lien individuel accompagne le message destiné à chaque élève et à sa famille. Les rappels de paiement ciblent les participations confirmées non réglées. L’accord de sortie et le paiement sont suivis séparément.</p>${entries.length?`<table class="outing-equipment-table outing-payments-table"><thead><tr><th>Élève</th><th>Participation</th><th>Règlement</th></tr></thead><tbody>${entries.map(entry=>`<tr><td>${html(entry.student_label)}<small class="outing-payment-preview">Aperçu fictif : ${html(entry.url)}</small></td><td>${currency(entry.amount)}</td><td>${entry.status==='cancelled'?'Annulé · refus de sortie':'En attente'}</td></tr>`).join('')}</tbody></table>`:`<div class="outing-ops-empty">${payments.status==='budget_required'?'Confirmez un budget complet et une participation positive avant de préparer les liens.':'Les liens seront préparés avec les messages aux familles.'}</div>`}<p class="outing-ops-explain">Démonstration : aucun lien Stripe réel créé, aucun envoi ni encaissement. Les adresses fictives affichées ne permettent pas de payer.</p><details class="outing-checkout" data-checkout-job="${html(state.job.id)}"><summary>Stripe Checkout · connexion</summary><div data-checkout-content aria-live="polite"></div></details>`;
    }
    if(state.operationsPanel==='photo'){
      const photo=ops?.photo||{},decisions=photo.decisions||[];
      return `<header class="outing-ops-detail-head"><strong>${sponsorBrand('google_docs')} <span>Autorisation photo</span></strong><span>Brouillon à faire valider</span></header><div class="outing-photo-counts"><span><b>${counts.photo_authorized??'—'}</b> accords simulés</span><span><b>${counts.photo_refused??'—'}</b> refus respectés</span><span><b>${counts.photo_pending??'—'}</b> à confirmer</span></div><div class="outing-photo-decisions">${decisions.filter(item=>item.status==='refused').map(item=>`<span>${icon('close')}${html(item.label)} · diffusion bloquée</span>`).join('')}</div>${photo.document?`<pre class="outing-ops-document">${html(photo.document.text)}</pre>`:'<div class="outing-ops-empty">Le formulaire de démonstration apparaîtra après l’appel de préparation.</div>'}<p class="outing-ops-explain">L’accord photo est indépendant de la participation à la sortie. Aucune signature réelle n’est recueillie.</p>`;
    }
    if(state.operationsPanel==='equipment'){
      const equipment=ops?.equipment||{},items=equipment.items||[],conflicts=equipment.conflicts||[],reservations=equipment.reservations||[];
      return `<header class="outing-ops-detail-head"><strong>${sponsorBrand('google_calendar')} <span>Le matériel de la sortie</span></strong><span>RÉSERVATIONS SIMULÉES</span></header>${items.length?`<table class="outing-equipment-table"><thead><tr><th>Matériel</th><th>Besoin</th><th>Stock</th><th>Alloué</th></tr></thead><tbody>${items.map(item=>`<tr class="${item.shortfall?'has-shortfall':''}"><td>${html(item.label)}</td><td>${html(item.requested)}</td><td>${html(item.available)}</td><td>${html(item.allocated??'—')}</td></tr>`).join('')}</tbody></table>`:'<div class="outing-ops-empty">Holo4 vérifiera le stock fictif avant de réserver.</div>'}${conflicts.map(item=>`<div class="outing-equipment-conflict">${icon('clock')}<span>${html(item.solution||`${item.missing} unité(s) indisponible(s)`)}</span></div>`).join('')}${(equipment.fallbacks||[]).map(item=>`<div class="outing-equipment-fallback">${icon('check')}<span>${html(item.quantity)} × ${html(item.label)}<small>${html(item.reason)}</small></span></div>`).join('')}<p class="outing-ops-explain">${reservations.length?`${reservations.length} ligne(s) de réservation enregistrée(s) dans la démonstration.`:'Aucune réservation n’a encore été préparée.'} Aucun stock réel n’est bloqué.</p>`;
    }
    const admin=ops?.admin||{},checks=admin.checklist||[];
    return `<header class="outing-ops-detail-head"><strong>${sponsorBrand('google_docs')} <span>Gestion administrative</span></strong><span>${counts.admin_prepared_documents??0} document(s) préparé(s)</span></header>${checks.length?`<ul class="outing-admin-checks">${checks.map(item=>`<li class="${item.status==='prepared'?'is-prepared':''}"><span>${icon(item.status==='prepared'?'check':'clock')}</span><div><strong>${html(item.label)}</strong><small>${html(item.detail)}</small></div><em>${item.status==='prepared'?'Préparé':'À valider'}</em></li>`).join('')}</ul>`:'<div class="outing-ops-empty">Holo4 assemblera les pièces du dossier après les autres appels.</div>'}${(admin.documents||[]).map(document=>`<details class="outing-admin-document"><summary>${icon('file')}${html(document.title)}<span>BROUILLON</span></summary><pre>${html(document.text)}</pre></details>`).join('')}<p class="outing-ops-explain">Dossier de démonstration. Aucun accord de direction, signature ou validation administrative réelle.</p>`;
  }
  function updateOperationsView(){
    if(!node('outing-live-operations-body'))return;
    const ops=state.job?.operations,counts=ops?.counts||{},families=ops?.families||[];
    syncOperationsPresentation(ops);
    for(const [id,key]of [['confirmed','confirmed'],['pending','pending'],['declined','declined']]){const counter=node('outing-ops-'+id);liveSetText(counter,counts[key]??'—');liveFlash(counter,counts[key]??'—');}
    liveSetText(node('outing-ops-family-total'),families.length?families.length+' familles fictives':'Données fictives');
    const equipment=ops?.equipment,allocated=equipment?.reservations?.length>0,checked=equipment?.items?.length>0;
    liveSetText(node('outing-ops-equipment-title'),allocated?'Matériel affecté · SIMULATION':checked?'Stock vérifié · disponibilité limitée':'Matériel à vérifier');
    liveSetText(node('outing-ops-equipment-note'),allocated?(equipment.fallbacks?.length?'Solution papier préparée · aucun stock réel bloqué':'Aucune réservation réelle'):checked?'Manque de tablettes identifié · alternative en préparation':'Stock fictif · aucune réservation réelle');
    liveSetText(node('outing-ops-equipment-units'),allocated?(counts.equipment_reserved_units||0)+' unités':checked?equipment.items.length+' lots':'—');
    node('outing-ops-equipment-mini').classList.toggle('is-ready',allocated);
    liveFlash(node('outing-ops-equipment-mini'),JSON.stringify([checked,allocated,counts.equipment_reserved_units]));
    const context=operationContext(state.job);
    liveSetText(node('outing-ops-call-count'),(operationCalls(state.job).length+(context?1:0))+' appel(s) reçu(s)');
    liveSetText(node('outing-ops-context'),(context?taskState(context)==='done'?'Contexte lu':taskState(context)==='error'?'Contexte à vérifier':'Lecture du contexte':'Contexte à lire')+' · read_outing_evidence()');
    const board=node('outing-ops-families'),signature=families.map(item=>item.id).join('|');
    if(board.dataset.families!==signature){board.dataset.families=signature;board.innerHTML=families.length?families.map((family,index)=>`<button type="button" id="outing-family-${html(family.id)}" data-ops-family="${html(family.id)}">${String(index+1).padStart(2,'0')}</button>`).join(''):'<p>Les familles fictives apparaîtront à la préparation des messages.</p>';board.querySelectorAll('[data-ops-family]').forEach(button=>button.onclick=()=>{pauseOperationsPresentation();state.operationsFamily=button.dataset.opsFamily;state.operationsMessageKind=null;state.operationsMessageId=null;state.operationsPanel='families';updateOperationsView();});}
    families.forEach(family=>{const chip=node('outing-family-'+family.id);if(!chip)return;const responseChanged=chip.dataset.response&&chip.dataset.response!==family.response;liveSetClass(chip,'is-'+family.response+(state.operationsFamily===family.id?' is-selected':'')+(responseChanged?' has-response-update':''));chip.dataset.response=family.response;if(responseChanged){chip.style.setProperty('--family-index',families.indexOf(family));setTimeout(()=>chip.classList.remove('has-response-update'),1100);}chip.title=family.label+' · '+({confirmed:'confirmation simulée',declined:'refus simulé',pending:'sans réponse'}[family.response]||'à vérifier');chip.setAttribute('aria-label',chip.title);chip.setAttribute('aria-pressed',String(state.operationsFamily===family.id));});
    for(const button of document.querySelectorAll('[data-ops-panel]'))button.setAttribute('aria-selected',String(button.dataset.opsPanel===state.operationsPanel));
    const detail=node('outing-ops-detail'),detailSignature=JSON.stringify([state.operationsPanel,state.operationsFamily,state.operationsMessageKind,state.operationsMessageId,ops?.messages,ops?.payments,ops?.photo,ops?.equipment,ops?.admin,counts]);
    if(state.operationsDetailSignature!==detailSignature){
      const samePanel=state.operationsRenderedPanel===state.operationsPanel,scroll=samePanel?detail.scrollTop:0,openDrafts=[...detail.querySelectorAll('.outing-admin-document')].map(item=>item.open);
      state.operationsDetailSignature=detailSignature;state.operationsRenderedPanel=state.operationsPanel;detail.innerHTML=operationsDetail(ops);detail.setAttribute('aria-labelledby','outing-ops-tab-'+state.operationsPanel);
      if(samePanel)detail.querySelectorAll('.outing-admin-document').forEach((item,index)=>item.open=!!openDrafts[index]);detail.scrollTop=scroll;
      detail.querySelectorAll('[data-ops-recipient]').forEach(button=>button.onclick=()=>{pauseOperationsPresentation();state.operationsFamily=button.dataset.opsRecipient;state.operationsMessageKind='reminder';state.operationsMessageId=null;updateOperationsView();});
      detail.querySelectorAll('[data-ops-message-kind]').forEach(button=>button.onclick=()=>{pauseOperationsPresentation();state.operationsMessageKind=button.dataset.opsMessageKind;state.operationsMessageId=null;state.operationsFamily=null;updateOperationsView();});
      detail.querySelectorAll('[data-ops-message]').forEach(button=>button.onclick=()=>{pauseOperationsPresentation();state.operationsMessageId=button.dataset.opsMessage;updateOperationsView();});
      detail.querySelectorAll('.outing-mail-stream>button').forEach(button=>{const id=button.dataset.opsMessage;if(!state.seenMessageCards)state.seenMessageCards=new Set();if(!state.seenMessageCards.has(id)){button.classList.add('is-arriving');state.seenMessageCards.add(id);}});
    }
    node('outing-ops-stale').hidden=!ops?.stale;
    for(const button of document.querySelectorAll('[data-operations-start]')){button.disabled=isBusy()||isOperationsBusy()||state.operationsStarting||state.saving||!state.job?.dossier;button.textContent=isOperationsBusy()?'Holo4 joue la démonstration…':ops?'Rejouer la démonstration':'Jouer la suite de démonstration';}
  }
  async function startOperations(){
    if(!state.job?.dossier||isBusy()||isOperationsBusy()||state.operationsStarting||state.saving)return;
    const id=state.job.id;
    state.operationsStarting=true;state.presentationAuto=true;state.presentationRun=null;state.presentationSeen=null;state.presentationMoment=null;state.seenMessageCards=new Set();state.error='';updateOperationsView();fillForm();
    try{clearTimeout(state.objectiveTimer);await persistObjective();if(state.job?.id!==id)return;const incoming=await api('/api/outings/'+encodeURIComponent(id)+'/operations-demo',{});if(state.job?.id!==id)return;state.job=incoming;state.presentationAuto=true;state.presentationRun=null;state.presentationSeen=null;state.operationsAutoRun=null;state.operationsFamily=null;state.livePhase='operations';renderJob();openLiveDialog(true);selectLivePhase('operations');pollJob();}
    catch(error){state.error=error.message;renderFeedback();}
    finally{state.operationsStarting=false;updateOperationsView();fillForm();}
  }
  // A finished outing where every collection failed and no tool call or collection succeeded (also for jobs saved
// before h_outcome existed): shown as failed without naming a cause the job does not record.
function nothingCollected(job){
    if(!job||['preparing','running'].includes(job.status))return false;
    const collections=(job.tasks||[]).filter(task=>task.id!=='dossier');
    const succeeded=[...(job.tool_calls||[]),...(job.executions||[])].some(item=>item.status==='succeeded');
    return collections.length>0&&collections.every(task=>task.status==='failed')&&!succeeded;
}
function liveStatusText(job,includeOperations=true){
    if(!job)return 'Prêt à démarrer';
    if(nothingCollected(job))return job.h_outcome==='timeout'?'Délai dépassé : aucune collecte n’a abouti, rien n’a été préparé':'Aucune collecte n’a abouti : rien n’a été préparé';
    if(includeOperations&&job.operations?.status==='running')return operationsStatus(job);
    const busy=['preparing','running','queued'].includes(job.status);
    if(busy&&job.agent?.provider_status==='queued')return 'Holo4 attend un créneau';
    const active=job.parallel?.active_count??executionList(job).filter(entry=>entry.status==='running').length;
    if(active>1)return `${active} outils s’exécutent en parallèle`;
    if(active===1)return 'Un outil s’exécute pendant qu’Holo4 poursuit';
    const labels={provider_queued:'Holo4 attend un créneau',planning:'Holo4 prépare ses appels',waiting_for_tool_calls:'Holo4 prépare ses appels',collecting:'Holo4 appelle les outils',waiting_for_results:'Holo4 attend les réponses',results_available:'Les résultats sont disponibles pour Holo4',reviewing:'Holo4 examine les résultats',filling:'Holo4 remplit le dossier',completed:'La sortie est prête à relire',partial:'La préparation est à compléter',failed:'La préparation demande une vérification'};
    return labels[job.agent?.status]||({ready:'La sortie est prête à relire',partial:'La préparation est à compléter',failed:'La préparation demande une vérification'}[job.status])||(busy?'Holo4 prépare la suite':'Préparation terminée');
  }
  function liveLauncher(job){
    return `<div class="outing-live-launcher"><span class="outing-live-launch-mark" aria-hidden="true">∥</span><div><strong>${isBusy()?'Calli prépare votre sortie…':html(liveStatusText(job))}</strong><p>${isBusy()?'Vous pouvez continuer à rédiger votre objectif.':'Retrouvez les étapes et les sources de la préparation.'}</p></div><div class="outing-live-launch-actions"><button type="button" class="button secondary" id="outing-open-live">Voir le détail ${icon('arrow')}</button>${job?.dossier?`<button type="button" class="button primary" data-operations-start ${isBusy()||isOperationsBusy()||state.operationsStarting?'disabled':''}>${isOperationsBusy()?'Holo4 joue la démonstration…':job.operations?'Rejouer la démonstration':'Jouer la suite de démonstration'}</button>`:''}</div></div>`;
  }
  function ensureLiveDialog(){
    if(node('outing-live-dialog'))return;
    const dialog=document.createElement('dialog');dialog.id='outing-live-dialog';dialog.className='outing-live-dialog';dialog.setAttribute('aria-labelledby','outing-live-title');
    dialog.innerHTML=`<div class="outing-live-shell"><header class="outing-live-head"><span class="outing-live-brand" aria-hidden="true"><img src="/static/brand/calli-symbol.svg" alt=""></span><div><span class="overline" id="outing-live-runtime">LES FUNCTION CALLS, EN DIRECT</span><h2 id="outing-live-title">Calli prépare votre sortie</h2><p id="outing-live-context">Une classe, une destination, un dossier qui avance.</p></div><div class="outing-live-head-metrics"><span id="outing-live-state" role="status"></span><span><b id="outing-live-active">0</b> outil(s) en cours <i>·</i> <time id="outing-live-elapsed">—</time></span></div><button type="button" class="outing-live-close" id="outing-live-close" aria-label="Fermer le suivi en direct">${icon('close')}</button></header><div class="outing-live-body" id="outing-live-preparation-body"><section class="outing-live-functions" aria-labelledby="outing-live-functions-title"><div class="outing-live-section-heading"><h3 id="outing-live-functions-title">Les outils appelés par Holo4</h3><span id="outing-live-call-count">0 appel reçu</span></div><div class="outing-live-call-stack">${liveTools.map((def,index)=>`<article id="outing-live-tool-${def.name}" class="outing-live-tool is-pending" data-live-name="${def.name}"><span class="outing-live-tool-icon" aria-hidden="true">${icon(def.icon)}</span><div class="outing-live-tool-main"><div><strong>${def.title}</strong><span class="outing-live-tool-state" data-live-field="state">Pas encore appelé</span></div><code>${def.name}()</code>${def.task==='visit'?`<div class="outing-live-provider">${sponsorBrand('linkup')} · site officiel</div>`:''}<p data-live-field="summary">L’outil est à disposition de Holo4.</p></div><div class="outing-live-tool-time"><span data-live-field="duration">—</span><small data-live-field="time">—</small><small data-live-field="count"></small></div></article>`).join('')}</div><div class="outing-live-concurrency"><span id="outing-live-concurrency">Les appels apparaissent lorsqu’ils sont réellement reçus.</span><span class="outing-live-legend"><i></i>En cours <i></i>Terminé</span></div></section><section class="outing-live-output" aria-labelledby="outing-live-output-title"><div class="outing-live-section-heading"><h3 id="outing-live-output-title">Les résultats se rejoignent</h3><span id="outing-live-result-count">0 / 3</span></div><div class="outing-live-results"><article id="outing-live-route" class="outing-live-result"><span>${icon('pin')} Itinéraire</span><strong data-live-field="value">—</strong><p data-live-field="detail">En attente du calcul</p></article><article id="outing-live-budget" class="outing-live-result"><span>${icon('users')} Budget</span><strong data-live-field="value">—</strong><p data-live-field="detail">En attente des tarifs</p></article><article id="outing-live-roster" class="outing-live-result"><span>${icon('folder')} Effectif</span><strong data-live-field="value">—</strong><p data-live-field="detail">En attente de la liste</p></article></div><article class="outing-live-paper"><header><span>${icon('file')} DOSSIER DE SORTIE</span><span id="outing-live-dossier-state">À préparer</span></header><pre id="outing-live-dossier-text">Le dossier se remplit au fur et à mesure des réponses des outils.</pre></article><label class="outing-live-objective" for="outing-live-objective"><span>Vous préparez l’objectif pédagogique.<small id="outing-live-objective-status">Brouillon local</small></span><textarea id="outing-live-objective" rows="2" maxlength="3000" placeholder="Continuez à rédiger pendant que Holo4 travaille…"></textarea></label></section></div><footer class="outing-live-footer"><span class="outing-live-feed-label">DERNIÈRES ACTIONS RÉELLES</span><div class="outing-live-events">${[0,1,2].map(i=>`<div id="outing-live-event-${i}" class="outing-live-event"><time></time><p></p></div>`).join('')}</div><p id="outing-live-error" role="alert" hidden></p></footer></div>`;
    document.body.append(dialog);
    node('outing-live-preparation-body').insertAdjacentHTML('beforebegin',`<div class="outing-live-phasebar" role="tablist" aria-label="Phases de la sortie"><button type="button" role="tab" data-live-phase="prepare" aria-selected="true">1 · Préparer la sortie</button><button type="button" role="tab" data-live-phase="operations" aria-selected="false">2 · Familles & logistique</button><button type="button" class="outing-ops-play" data-operations-start>Jouer la suite de démonstration</button></div><div class="outing-ops-simulation">DÉMONSTRATION · AUCUN ENVOI / AUCUNE RÉSERVATION RÉELLE</div>`);
    node('outing-live-preparation-body').insertAdjacentHTML('afterend',operationsMarkup());
    dialog.querySelectorAll('[data-live-phase]').forEach(button=>button.onclick=()=>{pauseOperationsPresentation();selectLivePhase(button.dataset.livePhase);});
    dialog.querySelectorAll('[data-ops-panel]').forEach(button=>button.onclick=()=>{pauseOperationsPresentation();state.operationsPanel=button.dataset.opsPanel;updateOperationsView();});
    dialog.querySelectorAll('[data-operations-start]').forEach(button=>button.onclick=startOperations);
    node('outing-ops-auto').onclick=()=>{state.presentationAuto=!state.presentationAuto;updatePresentationControl();};
    node('outing-ops-detail').addEventListener('pointerdown',pauseOperationsPresentation);
    node('outing-live-close').onclick=()=>dialog.close();
    dialog.addEventListener('close',()=>{clearInterval(state.liveTimer);state.liveTimer=null;});
    node('outing-live-objective').oninput=()=>changeObjective(node('outing-live-objective').value,'live');
    updateLiveDialog();
  }
  function openLiveDialog(force=false){
    ensureLiveDialog();
    const dialog=node('outing-live-dialog');
    if(!force&&state.liveOpenedJob===state.job?.id)return;
    if(state.job)state.liveOpenedJob=state.job.id;
    updateLiveDialog();
    if(!dialog.open)dialog.showModal();
    clearInterval(state.liveTimer);state.liveTimer=setInterval(updateLiveTimes,1000);
  }
  function changeObjective(value,source){
    state.draft.objective=value;state.revision++;state.objectiveDirty=true;saveDraft();
    const main=node('outing-objective'),live=node('outing-live-objective');
    if(source!=='main'&&main&&main.value!==value)main.value=value;
    if(source!=='live'&&live&&live.value!==value)live.value=value;
    updateObjectiveStatus();
    if(node('outing-save'))node('outing-save').disabled=true;
    if(node('outing-download'))node('outing-download').disabled=true;
    clearTimeout(state.objectiveTimer);
    if(state.job)state.objectiveTimer=setTimeout(()=>persistObjective().catch(error=>{state.error=error.message;renderFeedback();}),800);
  }
  function updateObjectiveStatus(){
    const label=state.objectiveDirty&&state.error?'À enregistrer':state.objectiveDirty&&state.job?'Enregistrement…':state.job?'Dans le brouillon':'Brouillon local';
    for(const id of ['outing-objective-status','outing-live-objective-status'])if(node(id)&&node(id).textContent!==label)node(id).textContent=label;
  }
  function liveSetText(target,value){if(target&&target.textContent!==String(value??''))target.textContent=value??'';}
  function liveSetClass(target,value){if(target&&target.className!==value)target.className=value;}
  function liveFlash(target,signature){
    if(!target)return;
    const key=target.id||target.dataset.liveName,previous=state.liveSignatures[key];
    state.liveSignatures[key]=signature;
    if(previous===undefined||previous===signature)return;
    target.classList.remove('has-update');void target.offsetWidth;target.classList.add('has-update');
    setTimeout(()=>target.classList.remove('has-update'),900);
  }
  function liveToolView(job,def){
    const calls=(def.demo?operationCalls(job):preparationCalls(job)).filter(call=>call.name===def.name),call=calls.at(-1);
    const execution=def.task?executionFor(job,def):null,task=def.task?outingTask(job,def.task):null;
    const current=def.task?executionState(execution,call,task):call?taskState(call):'pending';
    const started=execution?execution.started_at:call?.started_at,ended=execution?execution.ended_at:call?.ended_at;
    const requested=!!(execution||call);
    const label={pending:'Pas encore appelé',requested:'Appel reçu',running:'En cours',done:'Terminé',error:'À vérifier'}[current]||'Appel reçu';
    const demoSummary=def.demo&&current==='done'?operationResultSummary(job,def.name):'';
    const summary=execution?.error||execution?.result_summary||demoSummary||(def.task&&requested?(task?.error||task?.summary):'')||(!requested?'L’outil est à disposition de Holo4.':current==='running'?(def.name==='wait_for_outing_results'?'Holo4 attend les résultats des appels en cours.':'L’appel s’exécute réellement.'):current==='requested'?'La demande est reçue ; l’exécution va démarrer.':current==='done'?(def.task?'Le résultat a été renvoyé à Holo4.':def.name==='read_outing_evidence'?'Holo4 a reçu les résultats et leurs sources.':def.name==='fill_administrative_dossier'?'Le dossier et le courrier ont été préremplis.':'Les réponses des outils sont disponibles.'):'Une information reste à vérifier.');
    return {current,label,summary,started,ended,requested,calls,call,execution};
  }
  function updateLiveTimes(){
    const dialog=node('outing-live-dialog');if(!dialog?.open)return;
    const job=state.job;
    if(job){
      const ops=state.livePhase==='operations'?job.operations:null;
      const end=ops?ops.status==='running'?null:ops.completed_at||ops.updated_at:['ready','partial','failed'].includes(job.status)?job.completed_at||job.updated_at:null;
      liveSetText(node('outing-live-elapsed'),durationLabel(ops?.started_at||job.created_at,end)||'—');
      for(const def of allLiveTools){const view=liveToolView(job,def),row=node('outing-live-tool-'+def.name);liveSetText(row?.querySelector('[data-live-field="duration"]'),view.started?durationLabel(view.started,view.ended):'—');}
    }
  }
  function updateLiveDialog(){
    const dialog=node('outing-live-dialog');if(!dialog)return;
    const job=state.job,calls=preparationCalls(job),active=job?.parallel?.active_count||0;
    const ops=job?.operations,run=ops?.started_at?job.id+':'+ops.started_at:null;
    if(run&&state.operationsAutoRun!==run){state.operationsAutoRun=run;state.livePhase='operations';}
    const operations=state.livePhase==='operations';
    node('outing-live-preparation-body').hidden=operations;node('outing-live-operations-body').hidden=!operations;dialog.classList.toggle('is-operations',operations);
    dialog.querySelectorAll('[data-live-phase]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.livePhase===state.livePhase)));
    liveSetText(node('outing-live-title'),operations?'Calli organise la suite':'Calli prépare votre sortie');
    liveSetText(node('outing-live-state'),operations?operationsStatus(job):liveStatusText(job,false));
    const ephemeral=job?job.agent?.environment==='workstation'&&job.agent?.storage==='ephemeral':state.options?.capabilities?.workstation_storage==='ephemeral';
    liveSetText(node('outing-live-runtime'),operations?(ops?.execution_mode==='models_api'?'Holo4 · Models API · démonstration locale':'DÉMONSTRATION LOCALE · APPELS HOLO4'):ephemeral?'WORKSTATION H ÉPHÉMÈRE · APPELS EN DIRECT':'LES FUNCTION CALLS, EN DIRECT');
    liveSetText(node('outing-live-active'),operations?operationCalls(job).filter(call=>call.status==='running').length:active);
    const phaseActive=operations?operationCalls(job).some(call=>call.status==='running'):active>0,phaseQueued=operations?ops?.status==='running'&&ops?.provider_status==='queued':job?.status==='preparing'&&job?.agent?.provider_status==='queued',phaseFinished=operations?['ready','failed'].includes(ops?.status):['ready','partial','failed'].includes(job?.status);
    liveSetClass(node('outing-live-state'),'outing-live-state '+(phaseQueued?'is-queued':phaseActive?'is-running':phaseFinished?'is-finished':''));
    const selected=state.options?.destinations?.find(destination=>destination.id===job?.input?.destination_id);
    liveSetText(node('outing-live-context'),job?`${selected?.name||'Sortie scolaire'} · ${formatDate(job.input?.date)} · ${job.input?.visit_time||''}`:'Une classe, une destination, un dossier qui avance.');
    liveSetText(node('outing-live-call-count'),`${calls.length} appel${calls.length>1?'s':''} reçu${calls.length>1?'s':''}`);
    for(const def of allLiveTools){
      const row=node('outing-live-tool-'+def.name),view=liveToolView(job,def);
      liveSetClass(row,'outing-live-tool is-'+view.current+(row.classList.contains('has-update')?' has-update':''));
      liveSetText(row.querySelector('[data-live-field="state"]'),view.label);
      liveSetText(row.querySelector('[data-live-field="summary"]'),view.summary);
      liveSetText(row.querySelector('[data-live-field="time"]'),view.requested?stamp(view.execution?.requested_at||view.call?.started_at):'—');
      liveSetText(row.querySelector('[data-live-field="count"]'),view.calls.length>1?`× ${view.calls.length} appels`:'');
      liveFlash(row,JSON.stringify([view.current,view.summary,view.calls.length,view.ended]));
    }
    const route=job?.route,budget=job?.budget,roster=job?.roster;
    const resultViews=[['route',!!route,route?`${timeLabel(route.departure_at)} → ${timeLabel(route.arrival_at)}`:'—',route?`${route.duration_minutes} min · ${route.distance_km} km · retour ${timeLabel(route.return_at)}`:'En attente du calcul'],['budget',!!budget,budget?currency(budget.total??budget.known_total):'—',budget?budget.complete?`${currency(budget.per_student)} par élève`:'Sous-total connu · tarifs à confirmer':'En attente des tarifs'],['roster',!!roster,roster?`${roster.student_count} élèves`:'—',roster?`+ ${roster.adults} accompagnateurs`:'En attente de la liste']];
    for(const [id,ready,value,detail]of resultViews){const tile=node('outing-live-'+id);liveSetClass(tile,'outing-live-result'+(ready?' is-ready':''));liveSetText(tile.querySelector('[data-live-field="value"]'),value);liveSetText(tile.querySelector('[data-live-field="detail"]'),detail);liveFlash(tile,JSON.stringify([ready,value,detail]));}
    liveSetText(node('outing-live-result-count'),`${resultViews.filter(view=>view[1]).length} / 3 résultats`);
    const filled=outingTask(job,'dossier')?.status==='done',text=job?.dossier?.text||'Le dossier se remplit au fur et à mesure des réponses des outils.';
    liveSetText(node('outing-live-dossier-state'),filled?'Prérempli par Holo4':job?.dossier?'En cours d’assemblage':'À préparer');
    liveSetText(node('outing-live-dossier-text'),text);liveFlash(node('outing-live-dossier-text'),text);
    const objective=state.draft.objective??job?.input?.objective??'';
    if(document.activeElement!==node('outing-live-objective')&&node('outing-live-objective').value!==objective)node('outing-live-objective').value=objective;
    updateObjectiveStatus();
    updateOperationsView();
    const events=((operations?ops?.events:job?.events)||[]).slice(-3).reverse();
    liveSetText(dialog.querySelector('.outing-live-feed-label'),operations?'JOURNAL DE LA DÉMONSTRATION':'DERNIÈRES ACTIONS RÉELLES');
    for(let i=0;i<3;i++){const row=node('outing-live-event-'+i),event=events[i];row.hidden=!event&&i>0;liveSetText(row.querySelector('time'),event?stamp(event.at||event.time):'—');liveSetText(row.querySelector('p'),event?.text||(operations?'Les appels Holo4 et leurs résultats simulés apparaîtront ici.':'Les actions réellement reçues apparaîtront ici.'));liveFlash(row,JSON.stringify(event||null));}
    liveSetText(node('outing-live-error'),state.error);node('outing-live-error').hidden=!state.error;
    updateLiveTimes();
  }
  window.setupOutingsPage = async () => {
    const token=++state.setupToken;
    ensureLiveDialog();bindPage();
    const objective=node('outing-objective');objective.value=state.draft.objective??state.job?.input?.objective??'';
    if(state.options){fillForm();renderJob();}
    try {
      if(!state.options)state.options=await api('/api/outings/options');
      if(token!==state.setupToken||!node('outings-page'))return;
      fillForm();
      const queryId=new URLSearchParams(location.search).get('outing_id'),requestedId=/^[a-f0-9]{12}$/i.test(queryId||'')?queryId.toLowerCase():null;
      let latest=requestedId;if(!latest){try{latest=localStorage.getItem('new-pronote-outing-job');}catch{}}
      if(latest&&(!state.job||requestedId&&state.job.id!==requestedId)){
        try{const existing=await api('/api/outings/'+encodeURIComponent(latest));if(token!==state.setupToken)return;state.job=existing;}
        catch(error){if(requestedId)throw error;try{localStorage.removeItem('new-pronote-outing-job');}catch{}}
      }
      if(token!==state.setupToken||!node('outings-page'))return;
      fillForm();renderJob();
      if(shouldPoll())pollJob();
    }catch(error){if(token!==state.setupToken||!node('outings-page'))return;state.error='Impossible de charger la préparation : '+error.message;renderFeedback();node('outing-roster-label').innerHTML='<button type="button" id="outing-options-retry">Réessayer ↻</button>';node('outing-options-retry').onclick=()=>setupOutingsPage();}
  };
  function fillForm(){
    const form=node('outing-form');if(!form||!state.options)return;
    const options=state.options,values={...options.defaults,...state.job?.input,...state.draft};
    node('outing-class').innerHTML=(options.classes||[]).map(item=>`<option value="${html(item.id)}">${html(item.name)} · ${Number(item.student_count)} élèves</option>`).join('');
    node('outing-destination').innerHTML=(options.destinations||[]).map(item=>`<option value="${html(item.id)}">${html(item.name)}</option>`).join('');
    for(const el of form.elements){if(el.name&&values[el.name]!=null)el.value=values[el.name];}
    if(!state.objectiveDirty&&node('outing-objective').value!==(values.objective||''))node('outing-objective').value=values.objective||'';
    for(const el of form.elements){if(el.tagName!=='BUTTON'&&el.id!=='outing-objective')el.disabled=isBusy()||isOperationsBusy()||state.operationsStarting;}
    form.setAttribute('aria-busy',String(shouldPoll()));
    const selected=(options.classes||[]).find(item=>item.id===form.elements.class_id.value);
    node('outing-roster-label').textContent=`${selected?.student_count??'—'} élèves`;
    node('outing-roster-label').title=selected?.source||'Liste de démonstration';
    node('outing-mode-note').textContent=isBusy()?'La préparation avance. Votre dossier apparaîtra ci-dessous.':'Le trajet, le budget et les documents seront réunis ici.';
    node('outing-start').disabled=isBusy()||isOperationsBusy()||state.operationsStarting||state.saving;
    node('outing-full-demo').disabled=isBusy()||isOperationsBusy()||state.operationsStarting||state.saving;
    node('outing-full-demo').innerHTML=state.completeDemoRequested?'Démo complète en cours…':`${icon('play')} Démo complète`;
    node('outing-start').innerHTML=isOperationsBusy()?'Démonstration en cours…':isBusy()?'<span class="outing-spinner" aria-hidden="true"></span> Préparation en cours…':state.saving?'Patientez…':`${icon(state.job?'arrow':'play')} ${state.job?'Actualiser le dossier':'Préparer la sortie'}`;
    if(!state.draft.objective&&values.objective){state.draft.objective=values.objective;saveDraft();}
  }
  function bindPage(){
    node('outing-form').onsubmit=startJob;
    node('outing-full-demo').onclick=()=>startJob(null,true);
    node('outing-form').addEventListener('invalid',event=>{const settings=event.target.closest('.outing-settings');if(settings)settings.open=true;},true);
    if(node('outing-open-live'))node('outing-open-live').onclick=()=>openLiveDialog(true);
    node('outing-form').oninput=event=>{if(event.target.name){state.draft[event.target.name]=event.target.value;saveDraft();}};
    node('outing-objective').oninput=()=>changeObjective(node('outing-objective').value,'main');
  }
  async function startJob(event,completeDemo=false){
    event?.preventDefault();if(isBusy()||isOperationsBusy()||state.operationsStarting||state.saving||!state.options)return;
    const form=node('outing-form');if(!form.reportValidity())return;
    state.completeDemoRequested=completeDemo;state.completeDemoJob=null;
    state.saving=true;state.error='';state.notice='';renderFeedback();fillForm();
    const payload={...state.options.defaults,...Object.fromEntries(new FormData(form)),...state.draft,objective:node('outing-objective').value,mode:'live'}, submittedRevision=state.revision;
    for(const key of ['adults','duration_minutes'])payload[key]=Number(payload[key]);
    try{
      clearTimeout(state.poll);clearTimeout(state.objectiveTimer);
      state.job=await api('/api/outings',payload);state.livePhase='prepare';state.operationsAutoRun=null;state.operationsFamily=null;state.completeDemoJob=completeDemo?state.job.id:null;state.objectiveDirty=state.revision!==submittedRevision;
      try{localStorage.setItem('new-pronote-outing-job',state.job.id);}catch{}
      state.notice='';
      renderJob();if(completeDemo)openLiveDialog(true);pollJob();if(state.objectiveDirty)await persistObjective();
    }catch(error){state.completeDemoRequested=false;state.completeDemoJob=null;state.error=error.message;}
    finally{state.saving=false;fillForm();renderFeedback();}
  }
  async function persistObjective(){
    if(state.objectivePending){await state.objectivePending;if(state.objectiveDirty)return persistObjective();return;}
    if(!state.job||!state.objectiveDirty)return;
    const id=state.job.id,rev=state.revision,objective=state.draft.objective??'';
    const request=api('/api/outings/'+encodeURIComponent(id)+'/objective',{objective});state.objectivePending=request;
    try{
      const result=await request;
      if(state.job?.id!==id)return;
      if(state.revision===rev){state.objectiveDirty=false;adoptJob(result);renderJob();if(node('outing-objective-status'))node('outing-objective-status').textContent='Enregistré dans le brouillon';updateObjectiveStatus();}
    }finally{if(state.objectivePending===request)state.objectivePending=null;}
    if(state.job?.id===id&&state.objectiveDirty)await persistObjective();
  }
  async function pollJob(){
    clearTimeout(state.poll);const id=state.job?.id;if(!id)return;
    try{
      const job=await api('/api/outings/'+encodeURIComponent(id));if(state.job?.id!==id)return;
      const previous=state.job.status;adoptJob(job);
      if(!isBusy()&&['preparing','running','queued'].includes(previous))state.notice=state.job.status==='ready'?'Votre sortie est prête à relire.':'La préparation est disponible. Les informations manquantes sont signalées dans le dossier.';
      renderJob();
      if(state.completeDemoRequested&&state.completeDemoJob===id&&!isBusy()&&!state.saving&&!state.operationsStarting){
        state.completeDemoRequested=false;state.completeDemoJob=null;
        if(state.job.dossier&&state.job.roster&&['ready','partial'].includes(state.job.status)){await startOperations();return;}
        state.error='La préparation doit être complétée avant la démonstration familles et logistique.';renderFeedback();fillForm();
      }
      if(shouldPoll()||state.completeDemoRequested)state.poll=setTimeout(pollJob,1800);
      else if(['preparing','running','queued'].includes(previous)){fillForm();if(job.status==='ready')feedback('La sortie est préparée. Itinéraire, budget et dossier sont prêts à relire.');else feedback('La préparation est terminée. Quelques informations restent à vérifier.');}
    }catch(error){state.error='Le suivi a été interrompu : '+error.message;renderFeedback();if(shouldPoll())state.poll=setTimeout(pollJob,5000);}
  }
  function renderFeedback(){
    updateLiveDialog();
    const target=node('outing-feedback');if(!target)return;
    target.innerHTML=state.error?`<div class="outing-error" role="alert">${html(state.error)} ${state.objectiveDirty?'<button id="outing-retry-objective" type="button">Réessayer l’enregistrement de l’objectif ↻</button>':''}${shouldPoll()?'<button id="outing-refresh-job" type="button">Actualiser le suivi ↻</button>':''}</div>`:state.notice?`<p class="outing-notice">${icon('check')}${html(state.notice)}</p>`:'';
    if(node('outing-refresh-job'))node('outing-refresh-job').onclick=()=>{state.error='';pollJob();};
    if(node('outing-retry-objective'))node('outing-retry-objective').onclick=async()=>{try{state.error='';await persistObjective();renderFeedback();}catch(error){state.error=error.message;renderFeedback();}};
    if(node('outing-live-error')){liveSetText(node('outing-live-error'),state.error);node('outing-live-error').hidden=!state.error;}
  }
  function renderJob(){
    updateLiveDialog();
    if(!node('outings-page'))return;renderFeedback();
    const job=state.job;if(!job)return;
    node('outing-work').hidden=false;
    node('outing-live-launch').innerHTML=liveLauncher(job);
    node('outing-open-live').onclick=()=>openLiveDialog(true);
    node('outing-live-launch').querySelectorAll('[data-operations-start]').forEach(button=>button.onclick=isOperationsBusy()?()=>{state.livePhase='operations';openLiveDialog(true);}:startOperations);
    const label=nothingCollected(job)?'Rien n’a été préparé':({preparing:'Préparation en cours',running:'Préparation en cours',ready:'Prêt à relire',partial:'À compléter',failed:'Préparation à reprendre'}[job.status]||'En attente');
    node('outing-job-state').textContent=label;node('outing-job-state').className='outing-job-state '+(isBusy()?'is-running':job.status==='ready'?'is-done':'');
    node('outing-results-count').textContent=job.saved&&!state.objectiveDirty?'Dossier enregistré':isBusy()?'Les résultats arrivent ici':label;
    const available=!!(job.route||job.budget||job.dossier)||['failed','partial'].includes(job.status);
    node('outing-results').hidden=!available;
    node('outing-result-content').innerHTML=available?results(job):'';
    if(node('outing-save'))node('outing-save').onclick=saveDossier;
    if(node('outing-download'))node('outing-download').onclick=downloadDossier;
    node('outing-result-content').querySelectorAll('[data-outing-tab]').forEach(button=>{
      const select=tab=>{state.activeTab=tab;renderJob();node(tab==='families'?'outing-families-tab':'outing-dossier-tab')?.focus({preventScroll:true});};
      button.onclick=()=>select(button.dataset.outingTab);
      button.onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();select(event.key==='Home'?'dossier':event.key==='End'?'families':state.activeTab==='dossier'?'families':'dossier');}};
    });
    const trace=node('outing-trace');trace.hidden=!(job.events?.length||job.visit?.sources?.length||job.warnings?.length||job.tool_calls?.length);
    node('outing-trace-content').innerHTML=traceContent(job);
    fillForm();
  }

  function results(job){
    const route=job.route||{},budget=job.budget||{},dossier=job.dossier||{};
    const missing=dossier.missing_fields||[],warnings=job.warnings||[];
    const ready=!!job.dossier&&['ready','partial'].includes(job.status)&&!nothingCollected(job),saved=!!job.saved&&!state.objectiveDirty;
    const destination=(state.options?.destinations||[]).find(d=>d.id===job.input?.destination_id);
    const routeTask=(job.tasks||[]).find(task=>task.id==='route'),routeError=route.error||routeTask?.error;
    const routeOK=job.route&&route.status!=='failed';
    const depart=route.departure_at||route.departure_time||route.departure||route.depart_at,arrival=route.arrival_at||route.arrival_time||route.visit_time||job.input?.visit_time;
    const duration=route.duration_minutes??route.travel_minutes,km=route.distance_km;
    const resultSource=route.provider||route.source||'Calcul du trajet';
    const routeSchedule=route.schedule||job.schedule||{};
    const conflictList=job.calendar?.conflicts||route.conflicts||[];
    const rows=budget.lines||budget.items||[];
    const total=budget.total??budget.total_eur,perStudent=budget.per_student??budget.per_student_eur??budget.cost_per_student;
    const calculated=!!job.budget,complete=budget.complete!==false&&total!=null;
    const body=state.activeTab==='families'?(dossier.family_letter||dossier.letter||'Le courrier sera disponible à la fin de la préparation.'):(dossier.text||'Le dossier se remplit lorsque les résultats sont disponibles.');
    return `<div class="outing-summary-grid"><article class="outing-route-result"><div class="outing-result-heading"><span class="outing-result-icon">${icon('pin')}</span><div><h3>Itinéraire</h3></div></div>${routeOK?`<div class="outing-route-line"><div><span class="outing-route-dot"></span><strong>${html(timeLabel(depart||routeSchedule.departure_time)||'À confirmer')}</strong><p>Départ de l’établissement</p></div><div class="outing-route-duration">${duration!=null?`${Math.ceil(Number(duration))} min`:'Durée à confirmer'}${km!=null?` · ${Number(km).toLocaleString('fr-FR',{maximumFractionDigits:1})} km`:''}<small>${html(route.mode_label||route.mode||'Trajet routier estimé')}</small></div><div><span class="outing-route-dot destination"></span><strong>${html(timeLabel(arrival)||'À confirmer')}</strong><p>${html(destination?.name||'Arrivée sur place')}</p></div></div><p class="outing-result-detail">${html(route.summary||route.note||'Temps routier indicatif, hors trafic et contraintes de stationnement du car.')}</p>${route.return_at||route.return_time||routeSchedule.return_time?`<p class="outing-return">Retour prévu : <strong>${html(timeLabel(route.return_at||route.return_time||routeSchedule.return_time))}</strong></p>`:''}<p class="outing-route-source">${html(typeof resultSource==='string'?resultSource:resultSource.label||resultSource.name||'Calcul du trajet')}${route.map_url||route.url||route.source_url?` · ${link(route.map_url||route.url||route.source_url,'Voir le trajet')}`:''}</p>`:`<div class="outing-result-pending">${icon('pin')}<p>${html(routeError||(isBusy()?'Le trajet est en cours de préparation.':'Le trajet n’est pas disponible. Relancez une préparation.'))}</p></div>`}${job.calendar?`<div class="outing-calendar-check ${conflictList.length?'has-conflict':''}">${icon(conflictList.length?'calendar':'check')}<span>${conflictList.length?`${conflictList.length} conflit${conflictList.length>1?'s':''} à examiner`:'Agenda local vérifié'}<small>${html(job.calendar.scope_note||job.calendar.summary||job.calendar.note||job.calendar.source||'Événements du dossier de démonstration')}</small></span></div>`:''}</article>
      <article class="outing-budget-result"><div class="outing-result-heading"><span class="outing-result-icon">${icon('users')}</span><div><h3>Budget</h3></div></div>${calculated?`<div class="outing-budget-total"><strong>${currency(complete?total:budget.known_total)}</strong><span>${complete?'Coût total de la sortie':'Sous-total connu · budget à compléter'}</span></div><dl class="outing-budget-lines">${rows.length?rows.map(row=>`<div><dt>${html(row.label||row.name)}${row.detail||row.formula||row.quantity!=null?`<small>${html(row.detail||row.formula||(row.unit_price!=null?row.quantity+' × '+currency(row.unit_price):row.quantity+' × tarif à confirmer'))}</small>`:''}</dt><dd>${currency(row.total??row.amount??row.total_eur)}</dd></div>`).join(''):budgetFallback(budget,job)}<div><dt>Financement prévu</dt><dd>− ${currency(budget.subsidy??job.input?.subsidy??'0')}</dd></div><div class="outing-budget-per"><dt>Participation par élève<small>${html(budget.student_count??job.roster?.student_count??'')} élèves · après financement</small></dt><dd>${currency(perStudent)}</dd></div></dl><p class="outing-budget-note">${html(budget.rounding||budget.note||'Tarifs issus de la recherche · transport saisi dans le projet. Les montants non vérifiés restent à confirmer.')}</p>`:`<div class="outing-result-pending">${icon('users')}<p>${html(budget.error||'Le budget sera calculé dès que le tarif et l’effectif seront disponibles.')}</p></div>`}</article></div>
      <article class="outing-dossier-result"><header class="outing-dossier-header"><div class="outing-result-heading"><span class="outing-result-icon">${icon('file')}</span><div><h3>Documents</h3></div></div><span class="badge ${saved?'':'purple'}">${saved?'Enregistré':ready?'Brouillon à relire':'En préparation'}</span></header><div class="outing-dossier-tabs" role="tablist" aria-label="Documents préparés"><button role="tab" id="outing-dossier-tab" aria-controls="outing-document-text" aria-selected="${state.activeTab==='dossier'}" data-outing-tab="dossier" class="${state.activeTab==='dossier'?'active':''}">Dossier de sortie</button><button role="tab" id="outing-families-tab" aria-controls="outing-document-text" aria-selected="${state.activeTab==='families'}" data-outing-tab="families" class="${state.activeTab==='families'?'active':''}">Courrier aux familles</button></div><div class="outing-document-layout"><div class="outing-document-paper"><div class="outing-document-letterhead"><span>COLLÈGE DES TILLEULS</span><span>${html(formatDate(job.input?.date))}</span></div><div class="outing-document-text" id="outing-document-text" role="tabpanel" aria-labelledby="${state.activeTab==='families'?'outing-families-tab':'outing-dossier-tab'}">${html(body)}</div></div><aside class="outing-document-checks"><h4>À vérifier</h4>${missing.length?`<p>${missing.length} point${missing.length>1?'s':''} à compléter ou confirmer :</p><ul>${missing.map(field=>`<li>${html(typeof field==='string'?field:field.label||field.name)}</li>`).join('')}</ul>`:'<p>Relisez les informations, les horaires et les montants avant de valider avec votre établissement.</p>'}<div class="outing-template-note">${icon('folder')}<span>${html(state.options?.template?.label||'Modèle de l’établissement')}<small>Modèle fictif de démonstration</small></span></div>${dossier.filled_by||dossier.provider?`<p class="outing-dossier-provider">${html(dossier.filled_by||dossier.provider)}</p>`:''}</aside></div><footer class="outing-dossier-footer"><span id="outing-save-status" role="status">${saved?`Enregistré dans l’espace administratif de démonstration${job.saved_at?' · '+stamp(job.saved_at):''}`:'Brouillon interne · à relire avant toute transmission'}</span><div>${ready?`<button class="button secondary" type="button" id="outing-download" ${state.saving||state.objectiveDirty?'disabled':''}>${icon('file')} Télécharger</button>`:''}<button class="button primary" id="outing-save" ${!ready||state.saving||saved||state.objectiveDirty?'disabled':''}>${icon('check')}${saved?'Dossier enregistré':'Enregistrer le dossier'}</button></div></footer></article>${warnings.length?`<div class="outing-warning"><strong>À garder en tête</strong><ul>${warnings.map(w=>`<li>${html(typeof w==='string'?w:w.text||w.message)}</li>`).join('')}</ul></div>`:''}`;
  }
  function timeLabel(value){if(!value)return '';if(/^\d{2}:\d{2}$/.test(value))return value;const d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});}
  function budgetFallback(budget,job){
    return [['Visite et billets',budget.tickets_total??budget.visit_total??budget.admission_total],['Transport',budget.transport_total??job.input?.transport_total],['Financement prévu',budget.subsidy??job.input?.subsidy]].filter(([,v])=>v!=null).map(([label,value])=>`<div><dt>${label}</dt><dd>${currency(value)}</dd></div>`).join('');
  }
  const visitFieldLabels={opening_time:'Heure d’accueil des groupes',closing_time:'Fin d’accueil des groupes',closed_on_date:'Jours d’ouverture',student_unit_price:'Tarif des élèves',adult_unit_price:'Tarif des accompagnateurs',group_fee:'Réservation du groupe',max_group_size:'Effectif maximal',conditions:'Conditions d’accueil'};
  const stageLabels={parallel:'Préparation parallèle',dispatch:'Appel demandé par Holo4',wait:'Attente des résultats',visit:'Recherche de la visite',route:'Itinéraire et agenda',roster:'Classe et modèle',dossier:'Dossier administratif',h:'H Company',browser:'Navigation visuelle Holo4',objective:'Objectif pédagogique',save:'Enregistrement',complete:'Préparation terminée'};
  function traceContent(job){
    const sources=job.visit?.sources||job.sources||[];
    const v=job.visit;
    const facts=v?[v.summary||v.text,v.opening_time&&v.closing_time?'Horaires recherchés : '+v.opening_time+' – '+v.closing_time:null,v.student_unit_price!=null?'Entrée élève : '+currency(v.student_unit_price):null,v.adult_unit_price!=null?'Entrée accompagnateur : '+currency(v.adult_unit_price):null,...(Array.isArray(v.conditions)?v.conditions:v.conditions?[v.conditions]:[])].filter(Boolean).join(' · '):null;
    return `<div class="outing-trace-grid"><div><h3>La visite, à la source.</h3>${facts?`<p>${html(facts)}</p>`:''}${sources.length?sources.map(source=>`<div class="outing-evidence">${link(source.url,visitFieldLabels[source.field]||source.title||source.name||'Site officiel du lieu de visite')}<p>${html(source.excerpt||source.content||'')}</p></div>`).join(''):'<p>Les liens officiels apparaîtront après la recherche.</p>'}${job.visit?.error?`<p class="outing-trace-error">${html(job.visit.error)}</p>`:''}${job.calendar?.conflicts?.length?`<h3>Conflits dans l’agenda local</h3>${job.calendar.conflicts.map(item=>`<p>${html(typeof item==='string'?item:item.title||item.summary)}</p>`).join('')}`:''}</div><div><h3>Ce qui a réellement été exécuté.</h3><ol class="outing-event-list">${(job.events||[]).slice().reverse().map(event=>`<li><time>${stamp(event.at||event.time)}</time><p>${html(event.text||event.message)}</p><small>${html(stageLabels[event.stage]||'Préparation')}</small></li>`).join('')}</ol>${browserProof(job)}${toolCalls(job)}</div></div>`;
  }
  function browserProof(job){
    const proof=job.browser_evidence;
    if(!proof?.verified)return '';
    return `<section class="outing-evidence"><h3>${sponsorBrand('hcompany',{label:'Holo4'})} a consulté le site officiel à l’écran.</h3><p>${Number(proof.visual_observation_count||0)} observation(s) visuelle(s) et ${Number(proof.executed_action_count||0)} action(s) de navigation confirmées.</p>${(proof.urls||[]).map(url=>link(url,'Page officielle consultée')).join('<br>')}${(proof.access_warnings||[]).map(warning=>`<p>${html(warning)}</p>`).join('')}<p>Ces traces attestent la navigation ; les tarifs restent reliés aux sources de recherche.</p></section>`;
  }
  function toolCalls(job){
    if(!job.tool_calls?.length)return '';
    const names={...callNames,read_outing_evidence:'Lire les preuves de la sortie',read_outing_inputs:'Lire les informations de la sortie',read_prepared_data:'Lire les résultats préparés',get_outing_data:'Rassembler les données de la sortie',fill_outing_dossier:'Remplir le dossier administratif',fill_administrative_dossier:'Remplir le dossier administratif'};
    return `<details class="outing-tools"><summary>Les outils réellement appelés par H (${job.tool_calls.length})</summary>${job.tool_calls.map(call=>`<div class="outing-tool"><strong>${html(names[call.name]||call.name)}</strong><span>${call.status==='succeeded'?'Terminé':call.status==='failed'?'Échec':'En cours'}${call.duration_ms!=null?' · '+(call.duration_ms/1000).toLocaleString('fr-FR',{maximumFractionDigits:1})+' s':''}${call.cached?' · résultat réutilisé':''}</span><p>${html(call.result_summary||'Appel en cours de traitement.')}</p></div>`).join('')}</details>`;
  }
  async function downloadDossier(){
    if(!state.job||isBusy()||state.saving)return;state.saving=true;state.error='';renderJob();
    try{
      clearTimeout(state.objectiveTimer);await persistObjective();
      const id=state.job.id,response=await fetch('/api/outings/'+encodeURIComponent(id)+'/export');
      if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(detail||'Le téléchargement n’est pas disponible.');}
      const blob=await response.blob(),url=URL.createObjectURL(blob),anchor=document.createElement('a');
      anchor.href=url;anchor.download='sortie-scolaire-'+state.job.input.date+'.txt';document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){state.error=error.message;}
    finally{state.saving=false;renderJob();}
  }
  async function saveDossier(){
    if(!state.job||isBusy()||state.saving)return;state.saving=true;state.error='';renderJob();
    try{clearTimeout(state.objectiveTimer);await persistObjective();const id=state.job.id;adoptJob(await api('/api/outings/'+encodeURIComponent(id)+'/save',{}));state.notice='Dossier enregistré dans l’espace administratif de démonstration.';feedback(state.notice);}
    catch(error){state.error=error.message;}
    finally{state.saving=false;renderJob();}
  }
})();
