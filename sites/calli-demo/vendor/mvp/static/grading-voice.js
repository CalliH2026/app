// Gladia transcribes only audio explicitly recorded or selected in this form.
function gradingWords(value){return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('fr').replace(/[^a-z0-9]+/g,' ').trim();}
function checkGradingVoiceTarget(command,student,title){
 if(command.student_name){
  const target=gradingWords(command.student_name).split(' ').filter(Boolean);
  const candidates=getManagement().students.filter(item=>!item.archived&&target.length&&target.every(word=>gradingWords(item.name).split(' ').includes(word)));
  if(candidates.length!==1||candidates[0].id!==student.id)return 'Le nom dicté ne désigne pas clairement '+student.name+'. Ouvrez sa fiche ou précisez le nom avant de recommencer.';
 }
 const target=gradingWords(command.evaluation_title);
 if(target&&!['devoir','le devoir','controle','le controle','evaluation','l evaluation','cet exercice','exercice'].includes(target)){
  const selected=gradingWords(title);
  if(!selected||(!selected.includes(target)&&!target.includes(selected)))return 'L’évaluation dictée ne correspond pas à celle sélectionnée. Choisissez la bonne évaluation, puis recommencez.';
 }
 return gradeValidation(command.score,command.maximum);
}
function mountGradingVoice({dialog,form,student}){
 const container=$('grading-voice');
 container.innerHTML=`<section class="grading-voice" aria-label="Saisie vocale avec Gladia"><strong>Dictez votre note avec Gladia</strong><p>« Note ${esc(student.name.split(' ')[0])} pour le devoir et mets-lui 12 sur 20, appréciation : bon travail. »</p><div class="grading-voice-actions"><button type="button" class="button secondary" id="grading-record">Dicter une note</button><label class="grading-audio-upload">Importer un vocal<input type="file" id="grading-audio-file" accept="audio/*,.webm,.mp4,.m4a,.wav,.ogg,.mp3,.aac,.flac"></label></div><p id="grading-voice-status" class="grading-voice-status" role="status" aria-live="polite">L’audio est envoyé à Gladia pour remplir les champs. Relisez, puis enregistrez la note.</p><blockquote id="grading-voice-transcript" class="grading-voice-transcript" hidden></blockquote></section>`;
 const button=$('grading-record'),file=$('grading-audio-file'),status=$('grading-voice-status'),transcript=$('grading-voice-transcript'),save=$('save-grading');
 let active=true,stream=null,recorder=null,timer=null,controller=null,recording=false,requesting=false,tooLarge=false;
 const alive=()=>active&&dialog.open&&$('grading-form')===form;
 const say=(text,error=false)=>{if(active){status.textContent=text;status.classList.toggle('is-error',error);}};
 const stopTracks=()=>{stream?.getTracks().forEach(track=>track.stop());stream=null;};
 const busy=(value)=>{save.disabled=value;file.disabled=value;button.disabled=value&&!recording;};
 const resetButton=()=>{recording=false;requesting=false;button.textContent='Dicter une note';busy(false);};
 async function transcribeAudio(audio,filename){
  if(!alive())return;
  if(!audio.size){say('Aucun son enregistré. Recommencez ou importez un vocal.',true);resetButton();return;}
  if(audio.size>20*1024*1024){say('Le vocal doit faire moins de 20 Mo.',true);resetButton();return;}
  controller=new AbortController();busy(true);button.disabled=true;say('Gladia transcrit votre consigne…');
  const payload=new FormData();payload.append('audio',audio,filename);
  try{
   const response=await fetch('/api/workspace/grading/transcribe',{method:'POST',body:payload,signal:controller.signal});
   const result=await response.json();if(!alive())return;
   const recognized=result.transcription||result.detail?.transcription;
   if(recognized?.text){transcript.textContent=recognized.text;transcript.hidden=false;}
   if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:result.detail?.message||'La transcription a échoué. Réessayez.');
   if(result.provider!=='Gladia'||!result.command)throw Error('La réponse de transcription est incomplète.');
   const error=checkGradingVoiceTarget(result.command,student,form.elements.title.value);
   if(error)throw Error(error);
   form.elements.maximum.value=String(result.command.maximum);form.elements.score.max=String(result.command.maximum);form.elements.score.value=String(result.command.score);
   if(result.command.appreciation!=null)form.elements.appreciation.value=result.command.appreciation;
   say('Note reconnue : '+result.command.score+' / '+result.command.maximum+'. Vérifiez les champs, puis enregistrez pour préparer le rapport et la capsule.');
   form.elements.score.focus();
  }catch(error){if(alive()&&error.name!=='AbortError')say(error.message||'Gladia est indisponible. Votre note saisie reste conservée.',true);}
  finally{if(active){controller=null;resetButton();}}
 }
 button.onclick=async()=>{
  if(recording){
   recording=false;button.disabled=true;button.textContent='Transcription…';clearTimeout(timer);recorder.stop();stopTracks();return;
  }
  if(requesting)return;
  if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined'){say('Ce navigateur ne permet pas l’enregistrement. Importez un vocal ou saisissez la note.',true);return;}
  requesting=true;busy(true);say('Autorisez le microphone, puis dictez la note.');
  try{
   const captured=await navigator.mediaDevices.getUserMedia({audio:true});
   if(!alive()){captured.getTracks().forEach(track=>track.stop());return;}
   stream=captured;
   const mimeType=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(type=>MediaRecorder.isTypeSupported(type));
   recorder=new MediaRecorder(stream,mimeType?{mimeType}:{});
   const chunks=[];let bytes=0;tooLarge=false;
   recorder.ondataavailable=event=>{if(event.data.size){bytes+=event.data.size;if(bytes>20*1024*1024){tooLarge=true;if(recorder.state==='recording')recorder.stop();stopTracks();}else chunks.push(event.data);}};
   recorder.onerror=()=>{if(active){say('L’enregistrement a échoué. Importez un vocal ou recommencez.',true);resetButton();}stopTracks();};
   recorder.onstop=()=>{
    clearTimeout(timer);stopTracks();
    if(!alive())return;
    if(tooLarge){say('Le vocal doit faire moins de 20 Mo.',true);resetButton();return;}
    const type=recorder.mimeType||mimeType||'audio/webm',extension=type.includes('mp4')?'m4a':type.includes('ogg')?'ogg':'webm';
    transcribeAudio(new Blob(chunks,{type}),'note-professeur.'+extension);
   };
   recorder.start(1000);recording=true;requesting=false;button.disabled=false;button.textContent='Arrêter et transcrire';say('Enregistrement en cours… Dictez la note, puis cliquez sur « Arrêter et transcrire ».');
   timer=setTimeout(()=>{if(recording&&alive())button.onclick();},60000);
  }catch(error){stopTracks();if(alive()){say(error.name==='NotAllowedError'?'Accès au microphone refusé. Importez un vocal ou saisissez la note.':'Le microphone est indisponible. Importez un vocal ou saisissez la note.',true);resetButton();}}
 };
 file.onchange=()=>{const audio=file.files?.[0];if(audio)return transcribeAudio(audio,audio.name);};
 function cleanup(){
  if(!active)return;active=false;clearTimeout(timer);controller?.abort();
  if(recorder?.state==='recording')recorder.stop();stopTracks();
  dialog.removeEventListener?.('close',cleanup);dialog.removeEventListener?.('cancel',cleanup);
 }
 dialog.addEventListener?.('close',cleanup);dialog.addEventListener?.('cancel',cleanup);
 return cleanup;
}
