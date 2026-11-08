/* Human-readable tool details. Original payloads stay in storage, never in the report UI. */
(() => {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const parse = value => {
    if (value && typeof value === 'object') return value;
    if (typeof value !== 'string') return null;
    try { const parsed = JSON.parse(value); return parsed && typeof parsed === 'object' ? parsed : null; } catch { return null; }
  };
  const labels = {dossier:'Dossier',summary:'Synthèse',question:'Question',evidence:'Éléments de preuve',claim:'Constat',quote:'Extrait cité',source_ids:'Sources',sources:'Sources',scenes:'Séquences',evidence_count:'Nombre de preuves',valid:'Vérification réussie',validated_dossier_id:'Référence du dossier',documents:'Documents',document_ids:'Pièces demandées',id:'Référence',title:'Titre',text:'Texte',provider:'Service',query:'Recherche',topic:'Sujet',purpose:'Usage',url:'Adresse',excerpt:'Extrait',unknowns:'Points à éclaircir',teacher_assessment:'Évaluation du professeur',score:'Note',maximum:'Barème',appreciation:'Appréciation',narration:'Explication',visual:'Support visuel',learning_objective:'Objectif pédagogique'};
  function formatted(value, depth = 0) {
    if (value == null) return '<span class="fine">Non renseigné</span>';
    if (depth > 8) return '<span class="fine">Détail disponible dans les sources du rapport.</span>';
    if (typeof value === 'string') {
      const nested = parse(value);
      if (nested) return formatted(nested, depth + 1);
      if (/^\s*[\[{]/.test(value)) return '<span class="fine">Détail incomplet dans le journal enregistré.</span>';
      return escape(({exercise:'Exercice',explanation:'Explication',reference:'Référence pédagogique'})[value] || value);
    }
    if (typeof value === 'boolean') return value ? 'Oui' : 'Non';
    if (Array.isArray(value)) return value.length ? `<ul class="tool-detail-list">${value.map(item=>`<li>${formatted(item,depth+1)}</li>`).join('')}</ul>` : '<span class="fine">Aucun élément</span>';
    if (typeof value === 'object') return `<table class="tool-detail-table"><tbody>${Object.entries(value).map(([key,item])=>`<tr><th scope="row">${escape(labels[key] || key.replaceAll('_',' '))}</th><td>${formatted(item,depth+1)}</td></tr>`).join('')}</tbody></table>`;
    return escape(value);
  }
  const outcomes = {
    get_evidence_catalog:'Catalogue des pièces récupéré.', read_native_documents:'Pièces du dossier récupérées.',
    transcribe_audio:'Vocal transcrit. Le texte est disponible dans la question entendue.',
    search_resources:'Ressources pédagogiques récupérées.',
    validate_dossier:'Vérification du dossier terminée.',
    render_capsule:'Capsule créée.', inspect_capsule:'Inspection de la capsule terminée.',
    read_repair_context:'Preuves relues pour la correction.', read_native_repair_context:'Preuves relues pour la correction.',
    list_pronote_routes:'Vues PRONOTE disponibles récupérées.', read_pronote_view:'Vue PRONOTE lue.'
  };
  window.renderReportTool = (call, index) => {
    const args = parse(call.arguments), result = parse(call.result_summary);
    const raw = call.result_summary == null ? '' : typeof call.result_summary === 'object' ? JSON.stringify(call.result_summary) : String(call.result_summary);
    const structured = /^\s*[\[{]/.test(raw);
    let summary = call.status === 'running' ? 'L’outil travaille…' : call.status === 'failed' ? 'L’appel a échoué. Le journal conserve le détail.' : call.status === 'succeeded' ? outcomes[call.name] || 'Appel terminé.' : 'État indisponible.';
    if (call.status === 'succeeded' && call.name === 'validate_dossier' && result?.valid === true) {
      summary = 'Dossier vérifié.';
      if (Number.isInteger(result.evidence_count) && result.evidence_count >= 0) summary += ` ${result.evidence_count} éléments de preuve`;
      if (Number.isInteger(result.scenes) && result.scenes >= 0) summary += ` · ${result.scenes} séquences`;
    } else if (raw && !structured && call.status !== 'running') summary = raw;
    let input = '';
    if (args && typeof args.topic === 'string') input += `<div><dt>Sujet</dt><dd>${escape(args.topic)}</dd></div>`;
    if (args && typeof args.purpose === 'string') input += `<div><dt>Usage</dt><dd>${escape(({exercise:'Exercice',explanation:'Explication',reference:'Référence pédagogique'})[args.purpose] || args.purpose)}</dd></div>`;
    if (args && Array.isArray(args.document_ids) && args.document_ids.length) input += `<div><dt>Pièces demandées</dt><dd>${args.document_ids.map(escape).join(' · ')}</dd></div>`;
    const hasParameters = args && Object.keys(args).length > 0;
    const details = hasParameters || result;
    return `<div class="tool-readable">${input ? `<dl class="tool-input-fields">${input}</dl>` : ''}<p class="tool-call-result">${escape(summary)}</p></div>${details ? `<details class="tool-journal" data-report-section="tool-${Number(index)}"><summary>Détails de cette étape</summary>${hasParameters ? `<h4>Demande</h4>${formatted(args)}` : ''}${result ? `<h4>Résultat</h4>${formatted(result)}` : ''}</details>` : ''}`;

  };
})();
