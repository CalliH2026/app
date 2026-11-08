// Notes remain editable locally and are included in each frozen Calli dossier.
const managementKey='new-pronote-management-v1';
let managementData,managementTab='students',gradingVoiceCleanup=null;
function stopGradingVoice(){if(gradingVoiceCleanup){gradingVoiceCleanup();gradingVoiceCleanup=null;}}
function getTeacherAssessment(record=getRecordedGrade('alex')){
 if(!record||record.studentId!=='alex'||record.archived||!record.gradedAt||record.score==null||gradeValidation(Number(record.score),Number(record.maximum)))return null;
 return {student_id:record.studentId,evaluation_id:record.id,title:record.title,date:record.date,score:Number(record.score),maximum:Number(record.maximum),appreciation:record.appreciation||'',graded_at:record.gradedAt};
}
function prepareSavedGrade(record){if(getTeacherAssessment(record)){prepareGradedAssessment(record);return true;}return false;}
function getManagement(){
 if(managementData)return managementData;
 try{const stored=JSON.parse(localStorage.getItem(managementKey));if(stored&&Array.isArray(stored.students)&&Array.isArray(stored.evaluations))return managementData=stored;}catch{}
 managementData={students:workspace.students.map(student=>({id:student.id,name:student.name,class:student.class,archived:false,source:true})),evaluations:workspace.students.map(student=>({id:'source-'+student.id,title:'Théorème de Pythagore · Exercice 2',studentId:student.id,class:student.class,date:'2026-11-05',score:student.assessment.score,maximum:student.assessment.maximum,status:'Corrigée',source:true,archived:false}))};
 return managementData;
}
// Local records plus the read-only native Calli roster (never saved into the local records).
function managementView(){const data=getManagement(),native=window.calliNativeStudents||[];return native.length?{...data,students:[...data.students,...native]}:data;}
function getRecordedGrade(studentId,evaluationId){
 return getManagement().evaluations.filter(item=>item.studentId===studentId&&!item.archived&&item.gradedAt&&(!evaluationId||item.id===evaluationId)).sort((a,b)=>String(b.gradedAt).localeCompare(String(a.gradedAt)))[0]||null;
}
function gradingButton(studentId,evaluationId){
 const grade=getRecordedGrade(studentId,evaluationId);
 return `<button type="button" class="button secondary" data-grade-student="${esc(studentId)}"${evaluationId?` data-grade-evaluation="${esc(evaluationId)}"`:''}>${grade?'Modifier la note':'Noter l’élève'}</button>`;
}
function bindGrading(root){root.querySelectorAll('[data-grade-student]').forEach(button=>button.onclick=()=>openGrading(button.dataset.gradeStudent,button.dataset.gradeEvaluation));}
function gradeValidation(score,maximum){
 if(!Number.isFinite(maximum)||maximum<=0)return 'Le maximum doit être un nombre supérieur à zéro.';
 if(!Number.isFinite(score)||score<0||score>maximum)return 'La note doit être comprise entre 0 et le maximum.';
 return '';
}
function openGrading(studentId='alex',evaluationId){
 stopGradingVoice();
 const data=getManagement(),student=data.students.find(item=>item.id===studentId&&!item.archived);
 if(!student){feedback('Ajoutez ou restaurez cet élève avant de le noter.');return;}
 const evaluations=data.evaluations.filter(item=>item.studentId===studentId&&!item.archived);
 if(evaluationId&&!evaluations.some(item=>item.id===evaluationId)){feedback('Cette évaluation est archivée ou indisponible.');return;}
 const selectedId=evaluationId||getRecordedGrade(studentId)?.id||evaluations[0]?.id||'';
 const dialog=$('management-dialog');
 dialog.setAttribute('aria-labelledby','grading-title');
 $('management-form').innerHTML=`<h2 id="grading-title">Noter ${esc(student.name)}</h2><p>${esc(student.class)} · Note de suivi</p><form id="grading-form"><label>Évaluation<select id="grading-evaluation" name="evaluationId">${evaluations.map(item=>`<option value="${esc(item.id)}" ${item.id===selectedId?'selected':''}>${esc(item.title)}</option>`).join('')}<option value="" ${!selectedId?'selected':''}>Nouvelle évaluation</option></select></label><div id="grading-voice"></div><div id="grading-fields"></div><p id="grading-error" class="error-note" role="alert" hidden></p><div class="form-actions"><button type="button" class="button secondary" id="cancel-grading">Annuler</button><button class="button primary" id="save-grading" type="submit">Enregistrer la note</button></div></form>`;
 const renderFields=()=>{
  stopGradingVoice();
  const item=evaluations.find(entry=>entry.id===$('grading-evaluation').value)||{};
  $('grading-fields').innerHTML=`<label>Intitulé<input name="title" value="${esc(item.title||'')}" required maxlength="150" placeholder="Contrôle de mathématiques"></label><label>Date<input name="date" type="date" value="${esc(item.date||new Date().toLocaleDateString('en-CA'))}" required></label><div class="form-columns"><label>Note<input name="score" type="number" value="${esc(item.score??'')}" min="0" max="${esc(item.maximum??20)}" step="0.01" required inputmode="decimal"></label><label>Sur<input name="maximum" type="number" value="${esc(item.maximum??20)}" min="0.01" step="0.01" required inputmode="decimal"></label></div><label>Appréciation <span class="fine">(facultative)</span><textarea name="appreciation" rows="4" maxlength="2000" placeholder="Réussites, points à retravailler, prochain objectif…">${esc(item.appreciation||'')}</textarea></label><p class="local-note">${student.id==='alex'?'Cette note et cette appréciation seront utilisées dans le prochain rapport et la capsule Calli. La copie source est conservée.':'Enregistré dans ce navigateur. Le rapport Calli de la démo est disponible pour le dossier d’Alex.'}</p>`;
  const form=$('grading-form');
  form.elements.maximum.oninput=()=>form.elements.score.max=form.elements.maximum.value;
  $('grading-error').hidden=true;
  $('save-grading').textContent=student.id==='alex'?'Enregistrer et préparer':'Enregistrer la note';
  if(typeof mountGradingVoice==='function')gradingVoiceCleanup=mountGradingVoice({dialog,form,student,evaluations});
 };
 renderFields();
 $('grading-evaluation').onchange=renderFields;
 $('cancel-grading').onclick=()=>{stopGradingVoice();dialog.close();};
 $('grading-form').onsubmit=event=>{
  event.preventDefault();
  const form=new FormData(event.target),existing=evaluations.find(item=>item.id===form.get('evaluationId'));
  const score=form.get('score').trim()===''?NaN:Number(form.get('score')),maximum=form.get('maximum').trim()===''?NaN:Number(form.get('maximum'));
  const title=form.get('title').trim(),appreciation=form.get('appreciation').trim();
  let error=gradeValidation(score,maximum);
  if(!error&&!title)error='Renseignez un intitulé.';
  if(!error&&appreciation.length>2000)error='L’appréciation est limitée à 2 000 caractères.';
  if(error){$('grading-error').textContent=error;$('grading-error').hidden=false;return;}
  const updated=structuredClone(data),record={...existing,id:existing?.id||crypto.randomUUID(),studentId:student.id,class:student.class,title,date:form.get('date'),score,maximum,appreciation,status:'Corrigée',archived:false,gradedAt:new Date().toISOString()};
  if(existing)updated.evaluations=updated.evaluations.map(item=>item.id===record.id?record:item);
  else updated.evaluations.push(record);
  if(saveManagement(updated)){stopGradingVoice();dialog.close();showPage(page,{preserveScroll:true});if(!prepareSavedGrade(record))feedback('Note et appréciation enregistrées dans ce navigateur.');}
  else{$('grading-error').textContent='Enregistrement impossible : le stockage du navigateur est indisponible ou plein.';$('grading-error').hidden=false;}
 };
 dialog.showModal();
 $('grading-form').elements.score.focus();
}
function managementPage(){const data=managementView();return title('Élèves & évaluations','Retrouvez les dossiers, organisez les évaluations et suivez chaque élève.')+`<div class="management-stats"><div><strong>${data.students.filter(s=>!s.archived).length}</strong><span>élèves actifs</span></div><div><strong>${new Set(data.students.filter(s=>!s.archived).map(s=>s.class)).size}</strong><span>classes</span></div><div><strong>${data.evaluations.filter(e=>!e.archived).length}</strong><span>évaluations</span></div></div><p class="local-note">${window.CALLI_PHOTO_NOTE||''} Les notes sont conservées dans ce navigateur. La note et l’appréciation d’Alex alimentent le rapport et la capsule Calli. Aucune synchronisation avec PRONOTE.</p><div class="management-tabs" role="tablist" aria-label="Gestion"><button role="tab" aria-selected="${managementTab==='students'}" data-manage-tab="students">Élèves</button><button role="tab" aria-selected="${managementTab==='evaluations'}" data-manage-tab="evaluations">Évaluations</button></div><div class="management-toolbar"><label class="management-search">Rechercher<input type="search" id="manage-query" placeholder="Un nom, une évaluation…"></label><label>Classe<select id="manage-class"><option value="">Toutes les classes</option>${[...new Set([...data.students,...data.evaluations].map(s=>s.class))].sort().map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('')}</select></label><label>Afficher<select id="manage-archive"><option value="active">Actifs</option><option value="archived">Archivés</option><option value="all">Tous</option></select></label><button class="button primary" id="manage-add">+ ${managementTab==='students'?'Ajouter un élève':'Créer une évaluation'}</button></div><div class="panel" id="management-results"></div>`;}
function bindManagement(){document.querySelectorAll('[data-manage-tab]').forEach(button=>button.onclick=()=>{managementTab=button.dataset.manageTab;showPage('management');});$('manage-query').oninput=renderManagementRows;$('manage-class').onchange=renderManagementRows;$('manage-archive').onchange=renderManagementRows;$('manage-add').onclick=()=>editManagement();renderManagementRows();}
function renderManagementRows(){const data=managementView(),studentTab=managementTab==='students',query=$('manage-query').value.trim().toLocaleLowerCase('fr'),className=$('manage-class').value,archive=$('manage-archive').value;const rows=data[managementTab].filter(item=>(!className||item.class===className)&&(archive==='all'||!!item.archived===(archive==='archived'))&&`${item.name||item.title} ${data.students.find(s=>s.id===item.studentId)?.name||''} ${item.class}`.toLocaleLowerCase('fr').includes(query));
 $('management-results').innerHTML=`<div class="management-count">${rows.length} ${studentTab?'élève(s)':'évaluation(s)'}</div>`+(rows.length?`<div class="table-scroll"><table class="management-table"><thead><tr><th>${studentTab?'Élève':'Évaluation'}</th><th>Classe</th><th>${studentTab?'Suivi':'Note / statut'}</th><th>Actions</th></tr></thead><tbody>${rows.map(item=>{
  if(item.native)return calliNativeRow(item);
  const grade=studentTab?getRecordedGrade(item.id):getRecordedGrade(item.studentId,item.id);
  const summary=studentTab?`${data.evaluations.filter(e=>e.studentId===item.id&&!e.archived).length} évaluation(s)${grade?`<small>Note de suivi : ${esc(grade.score)} / ${esc(grade.maximum)}</small>`:''}`:`${item.score==null?'—':esc(item.score)} / ${esc(item.maximum)}<small>${grade?'Note de suivi · ':''}${esc(item.status)}</small>`;
  const canGrade=!item.archived&&(studentTab||data.students.some(student=>student.id===item.studentId&&!student.archived));
  return `<tr><td>${studentTab&&window.studentAvatar?studentAvatar(item,'small'):''}<strong>${esc(item.name||item.title)}</strong><small>${studentTab?(item.source?'Dossier source disponible':'Fiche de suivi locale'):`${esc(data.students.find(s=>s.id===item.studentId)?.name||'Élève non disponible')} · ${esc(item.date)}`}${item.archived?' · Archivé':''}</small></td><td>${esc(item.class)}</td><td>${summary}${(studentTab?grade?.appreciation:item.appreciation)?`<small class="grading-appreciation">${esc(studentTab?grade.appreciation:item.appreciation)}</small>`:''}</td><td><div class="row-actions">${canGrade?gradingButton(studentTab?item.id:item.studentId,studentTab?undefined:item.id):''}<button class="text-button" data-edit-record="${esc(item.id)}">Modifier</button>${item.source?`<button class="text-button" data-doc="copie">Copie ↗</button>`:''}<button class="text-button" data-archive-record="${esc(item.id)}">${item.archived?'Restaurer':'Archiver'}</button>${studentTab?`<button class="text-button" data-student-evaluation="${esc(item.id)}">+ Évaluation</button>`:''}</div></td></tr>`;
 }).join('')}</tbody></table></div>`:`<div class="empty-state"><h3>Aucun résultat</h3><p>Modifiez les filtres ou ajoutez ${studentTab?'un élève':'une évaluation'}.</p></div>`);
 $('management-results').querySelectorAll('[data-edit-record]').forEach(button=>button.onclick=()=>editManagement(button.dataset.editRecord));$('management-results').querySelectorAll('[data-archive-record]').forEach(button=>button.onclick=()=>{const item=data[managementTab].find(i=>i.id===button.dataset.archiveRecord);const updated=structuredClone(getManagement());updated[managementTab].find(i=>i.id===item.id).archived=!item.archived;if(saveManagement(updated)){showPage('management',{preserveScroll:true});feedback(item.archived?'Fiche restaurée.':'Fiche archivée. Vous pouvez la restaurer avec le filtre Archivés.');}});$('management-results').querySelectorAll('[data-student-evaluation]').forEach(button=>button.onclick=()=>{managementTab='evaluations';showPage('management');editManagement(null,button.dataset.studentEvaluation);});$('management-results').querySelectorAll('[data-calli-open]').forEach(button=>button.onclick=()=>openCalliStudent(button.dataset.calliOpen));bindContent($('management-results'));bindGrading($('management-results'));
}
function saveManagement(data){try{localStorage.setItem(managementKey,JSON.stringify(data));managementData=data;return true;}catch{feedback('Enregistrement impossible : le stockage du navigateur est indisponible ou plein.');return false;}}
function editManagement(id,studentId){
 stopGradingVoice();
 const data=getManagement(),tab=managementTab,studentTab=tab==='students',item=data[tab].find(i=>i.id===id)||{},activeStudents=data.students.filter(s=>!s.archived||s.id===item.studentId);
 if(!studentTab&&!activeStudents.length){feedback('Ajoutez ou restaurez un élève avant de créer une évaluation.');return;}
 const input=(label,name,value,type='text',extra='')=>`<label>${label}<input name="${name}" type="${type}" value="${esc(value??'')}" ${extra}></label>`;
 $('management-dialog').setAttribute('aria-labelledby','record-title');
 $('management-form').innerHTML=`<h2 id="record-title">${id?'Modifier':studentTab?'Ajouter un élève':'Créer une évaluation'}</h2><form id="record-form">${studentTab?input('Prénom et nom','name',item.name,'text','required maxlength="100"')+input('Classe','class',item.class||'4e B','text','required maxlength="50"'):`${input('Intitulé','title',item.title,'text','required maxlength="150"')}<label>Élève<select name="studentId" ${item.source?'disabled':''}>${activeStudents.map(student=>`<option value="${esc(student.id)}" ${student.id===(item.studentId||studentId)?'selected':''}>${esc(student.name)} · ${esc(student.class)}</option>`).join('')}</select></label>${input('Date','date',item.date||new Date().toLocaleDateString('en-CA'),'date','required')}<div class="form-columns">${input('Note (facultative)','score',item.score,'number','min="0" step="0.01"')}${input('Sur','maximum',item.maximum??20,'number','required min="0.01" step="0.01"')}</div><label>Appréciation (facultative)<textarea name="appreciation" rows="4" maxlength="2000">${esc(item.appreciation||'')}</textarea></label><label>Statut<select name="status">${['À préparer','À corriger','Corrigée'].map(status=>`<option ${item.status===status?'selected':''}>${status}</option>`).join('')}</select></label>`}<p class="local-note">${item.source&&!studentTab?'La note et l’appréciation alimenteront un nouveau rapport et une nouvelle capsule Calli. La copie et le barème sources sont conservés.':'Cette fiche sera enregistrée dans ce navigateur.'}</p><p id="record-error" class="error-note" role="alert" hidden></p><div class="form-actions"><button type="button" class="button secondary" id="cancel-record">Annuler</button><button class="button primary" type="submit">Enregistrer</button></div></form>`;
 $('cancel-record').onclick=()=>$('management-dialog').close();
 $('record-form').onsubmit=event=>{
  event.preventDefault();
  const form=new FormData(event.target),record={...item,id:item.id||crypto.randomUUID(),archived:!!item.archived};
  let error='';
  if(studentTab){
   record.name=form.get('name').trim();record.class=form.get('class').trim();
   if(!record.name||!record.class)error='Renseignez le nom et la classe.';
  }else{
   record.title=form.get('title').trim();record.studentId=item.source?item.studentId:form.get('studentId');
   const student=data.students.find(s=>s.id===record.studentId);
   record.class=student?.class||'';record.date=form.get('date');record.status=form.get('status');
   record.score=form.get('score').trim()===''?null:Number(form.get('score'));record.maximum=Number(form.get('maximum'));
   record.appreciation=form.get('appreciation').trim();
   if(!record.title)error='Renseignez un intitulé.';
   else if(!student)error='Choisissez un élève disponible.';
   else error=gradeValidation(record.score??0,record.maximum);
   if(!error&&record.appreciation.length>2000)error='L’appréciation est limitée à 2 000 caractères.';
   if(!error){if(record.score!==null)record.gradedAt=new Date().toISOString();else delete record.gradedAt;}
  }
  if(error){$('record-error').textContent=error;$('record-error').hidden=false;return;}
  const updated=structuredClone(data);
  if(id)updated[tab]=updated[tab].map(i=>i.id===id?record:i);else updated[tab].push(record);
  if(studentTab)updated.evaluations.forEach(e=>{if(e.studentId===record.id)e.class=record.class;});
  if(saveManagement(updated)){$('management-dialog').close();showPage('management',{preserveScroll:true});if(studentTab||!prepareSavedGrade(record))feedback('Fiche enregistrée dans ce navigateur.');}
  else{$('record-error').textContent='Enregistrement impossible : le stockage du navigateur est indisponible ou plein.';$('record-error').hidden=false;}
 };
 $('management-dialog').showModal();$('record-form').querySelector('input').focus();
}
