// Teacher workspace: context -> draft -> exact-text approval -> execution -> results; H preparation in a side panel.
// Every text from a document, a preparation or the journal is set with textContent, never innerHTML.
"use strict";

const $ = (id) => document.getElementById(id);
const MAX_CHARS = 255;
const ACTIVE = ["queued", "running"];
const WORDS = {
  pending: "À faire · en file", in_progress: "Saisie en cours…", verified: "Vérifiée", mismatch: "Non confirmée",
  unknown: "Non confirmé : vérification nécessaire", abstained: "Non écrite : à arbitrer", aborted: "Interrompue : vérifier dans PRONOTE",
  not_started: "Non commencée",
  not_found: "Non commencée : élève introuvable", queued: "En attente", running: "H prépare",
  ready: "Prête", failed: "Échec", stale: "Périmée", unavailable: "Indisponible",
};
// Result groups after TCH-10 (Scribe Phase 04 V4.2): unknown is "not confirmed", never a confirmed failure.
const GROUPS = [["Vérifiées", ["verified"]], ["Non confirmées", ["mismatch", "unknown", "aborted"]],
                ["En cours", ["in_progress"]], ["Non commencées", ["pending", "not_started", "abstained", "not_found"]]];
// `aborted` reads "not started" only with the store's proof (STOP drain or session end before hand-out); an older
// queue may hold `aborted` reported after the item was handed out, which may be a partial write.
const shown = (it) => (it.status === "aborted" && it.not_started === true ? "not_started" : it.status);
const ui = {
  roster: [], course: null, preparer: { available: false, reason: "" }, selected: null, epoch: 0,
  drafts: {}, previous: {}, cases: {}, prep: {}, items: [], journal: [], stopped: false, stopMode: null, approving: false, timers: {},
  dictation: { available: false, reason: "" }, dict: { phase: "idle" },
};
const SOURCES = { automatic_dictation: "dictée", workspace: "correction", ui: "écran manuel", retry: "reprise" };

function el(tag, attrs = {}, text) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

// ?embed=1: shown inside another teacher workspace (e.g. Francois's shell at /calli): keep the class, the dictation,
// the readback journal and STOP; drop Calli's own navigation and its parallel-preparation panes.
if (new URLSearchParams(location.search).get("embed") === "1") {
  document.body.classList.add("embedded");
  // The host's H design tokens (same origin); var() fallbacks in workspace.css keep the view intact without them.
  const tokens = Object.assign(document.createElement("link"), {rel: "stylesheet", href: "/static/h-kit/tokens.css"});
  document.head.prepend(tokens);
}

// Relative to the page, so the workspace works at / and when mounted under a prefix (e.g. /calli/workspace).
const rel = (path) => path.replace(/^\//, "");

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(rel(path), opts);
  let data = null;
  try { data = await r.json(); } catch (_) { data = null; }
  if (!r.ok) {
    let d = data && data.detail;
    if (Array.isArray(d)) d = d.map((x) => x.msg || JSON.stringify(x)).join("; ");
    throw new Error(d || `Erreur ${r.status}`);
  }
  return data;
}

function chars(text) { return [...text.trim()].length; }
const ROLES = { instructions: "Consigne", rubric: "Critères", pupil_work: "Travail de l’élève", teacher_notes: "Notes du professeur" };
function student(id) { return ui.roster.find((s) => s.student_id === id) || null; }
function contextParts(course) {
  const p = (course || "").split(",").map((x) => x.trim());
  return p.length === 3 ? { classe: p[0], matiere: p[1], periode: p[2] } : { classe: course || "?", matiere: "", periode: "" };
}
function nameKey(name) {
  return (name || "").normalize("NFC").toLocaleLowerCase("fr").split(/[\s,]+/).filter(Boolean).sort().join(" ");
}

// One committed 5x2 atlas of AI-generated fictional portraits, in roster order s01..s10 (docs/ui.md).
const PORTRAITS = ["s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "s09", "s10"];

function avatarNode(s, big) {
  const box = el("span", { class: big ? "avatar big" : "avatar", "aria-hidden": "true" });
  if (!s) return box;
  const at = PORTRAITS.indexOf(s.student_id);
  if (at >= 0) {
    box.classList.add("portrait");
    box.style.backgroundPosition = `${(at % 5) * 25}% ${Math.floor(at / 5) * 100}%`;
  } else if (s.avatar) box.append(el("img", { src: rel(s.avatar), alt: "" }));
  else { box.textContent = s.initials || "?"; box.style.background = s.color || "#556"; }
  return box;
}

function badge(status, word) {
  return el("span", { class: `state state-${status}` }, word || WORDS[status] || status);
}

function showError(msg) { const e = $("global-error"); e.textContent = msg || ""; e.hidden = !msg; }

// ---- context --------------------------------------------------------------------------------------------

function renderRoster() {
  const list = $("roster");
  list.replaceChildren();
  for (const s of ui.roster) {
    const b = el("button", { type: "button", "data-id": s.student_id, "aria-current": String(s.student_id === ui.selected) });
    b.append(avatarNode(s), el("span", {}, s.display_name));
    if (s.case_id) b.append(el("span", { class: "tag" }, "dossier"));
    b.addEventListener("click", () => selectPupil(s.student_id));
    const li = el("li");
    li.append(b);
    list.append(li);
  }
}

function renderHeader() {
  const s = student(ui.selected);
  const head = $("pupil-avatar");
  head.replaceWith(Object.assign(avatarNode(s, true), { id: "pupil-avatar" }));
  $("pupil-name").textContent = s ? s.display_name : "Choisissez un élève";
  const c = contextParts(ui.course);
  const line = $("pupil-course");
  line.replaceChildren();
  if (s) {
    const ctx = el("span", { class: "ctx" });
    ctx.title = `Élève ${s.student_id}`;
    ctx.append(el("span", {}, `Classe ${c.classe}`),
               el("span", {}, `Matière ${c.matiere}`), el("span", {}, `Période ${c.periode}`));
    line.append(ctx);
  }
  const data = s && ui.cases[s.student_id];
  const kind = $("kind-badge");
  kind.hidden = !(data && data.case.source_kind === "authored_demo");
  kind.textContent = "Exemple fictif";
  kind.title = "Dossier rédigé pour la démonstration, pas un import PRONOTE";
}

function renderCase() {
  const s = student(ui.selected);
  const data = s && ui.cases[s.student_id];
  $("case").hidden = !data;
  const empty = $("case-empty");
  empty.hidden = !!data;
  if (!s) empty.textContent = "Sélectionnez un élève pour voir son dossier.";
  else if (!s.case_id) empty.textContent = `Pas de dossier source pour ${s.display_name}.`;
  else if (!data) empty.textContent = "Chargement du dossier…";
  if (!data) { updatePrepareButton(); return; }
  $("case-question").textContent = data.case.question;
  $("case-provenance").textContent = `${data.case.title}. ${data.case.provenance}`;
  const docs = $("documents");
  docs.replaceChildren();
  for (const d of data.case.documents) {
    const card = el("details", { class: "doc" });
    card.addEventListener("toggle", () => { if (card.open) observeOpen(data, d.id); });
    const sum = el("summary");
    sum.title = `${d.id} · ${d.role}`;
    sum.append(el("h3", {}, d.title), el("span", { class: "role" }, `${ROLES[d.role] || "Pièce du dossier"} · afficher`));
    card.append(sum, el("p", {}, d.text));
    docs.append(card);
  }
  updatePrepareButton();
}

async function selectPupil(id) {
  if (ui.selected === id) return;
  if (ui.selected) { ui.drafts[ui.selected] = $("draft").value; ui.previous[ui.selected] = $("previous").value; }
  if (ui.dict.phase !== "idle") cancelDictation("pupil_changed");
  $("transcript").textContent = "";
  $("dictation-result").hidden = true;
  ui.selected = id;
  const epoch = ++ui.epoch;
  $("draft").value = ui.drafts[id] || "";
  $("previous").value = ui.previous[id] || "";
  $("confirm-replace").checked = false;
  $("draft").disabled = false;
  $("previous").disabled = false;
  $("draft-label").textContent = `Appréciation pour ${student(id).display_name}`;
  $("approve-msg").textContent = "";
  renderRoster(); renderHeader(); renderCase(); renderPrep(); renderQueue(); updateApprove();
  const s = student(id);
  if (s.case_id && !ui.cases[id]) {
    try {
      const data = await api(`/api/workspace/cases/${encodeURIComponent(s.case_id)}`);
      if (epoch !== ui.epoch && ui.selected !== id) { ui.cases[id] = data; return; }
      ui.cases[id] = data;
      if (data.preparation) { ui.prep[id] = data.preparation; if (ACTIVE.includes(data.preparation.status)) pollPrep(id); }
    } catch (e) { if (ui.selected === id) showError(`Dossier illisible : ${e.message}`); return; }
    if (ui.selected === id) { renderHeader(); renderCase(); renderPrep(); }
  }
}

// ---- preparation (side panel) ---------------------------------------------------------------------------

function updatePrepareButton() {
  const b = $("prepare");
  const s = student(ui.selected);
  const job = s && ui.prep[s.student_id];
  b.disabled = !(s && ui.cases[s.student_id] && ui.preparer.available && !(job && ACTIVE.includes(job.status)));
  b.textContent = job && job.status === "failed" ? "Relancer la préparation" : "Préparer mon échange";
}

function renderPrep() {
  const s = student(ui.selected);
  const job = s && ui.prep[s.student_id];
  const status = $("prep-status");
  status.replaceChildren();
  $("prep-events").replaceChildren();
  $("prep-result").hidden = true;
  $("prep-trace").textContent = "";
  $("prep-tech").hidden = true;
  if (!ui.preparer.available) status.append(badge("unavailable"), document.createTextNode(` ${ui.preparer.reason || ""}`));
  else if (!s) status.textContent = "Choisissez un élève.";
  else if (!s.case_id) status.textContent = "Aucun dossier source pour cet élève : rien à préparer.";
  else if (!job) status.textContent = `Aucune préparation lancée pour ${s.display_name}. Rien n’est envoyé à H avant l’ouverture d’une pièce du dossier (observation active) ou votre clic.`;
  if (job) {
    status.append(badge(job.status), document.createTextNode(` ${job.student_name}`));
    if (job.error) status.append(el("p", { class: "error" }, job.error));
    for (const ev of job.events || []) {
      const li = el("li", { class: `ev ev-${ev.kind || "check"}` });
      li.append(el("span", { class: "ev-kind" }, KINDS[ev.kind] || KINDS.check),
                el("span", {}, ` ${(ev.at || "").slice(11, 19)} ${ev.text}`));
      $("prep-events").append(li);
    }
    const p = job.preparation;
    if (job.status === "ready" && p) {
      $("prep-summary").textContent = p.summary;
      const evl = $("prep-evidence"); evl.replaceChildren();
      for (const e of p.evidence) {
        const li = el("li");
        li.append(el("strong", {}, e.claim), el("blockquote", {}, e.quote),
                  el("span", { class: "meta" }, `${e.document_title} · ${e.quote_id}`));
        evl.append(li);
      }
      for (const [id, arr] of [["prep-unknowns", p.unknowns], ["prep-suggestions", p.suggestions]]) {
        const ul = $(id); ul.replaceChildren();
        if (!arr.length) ul.append(el("li", { class: "empty" }, "Rien."));
        for (const t of arr) ul.append(el("li", {}, t));
      }
      const res = p.resources, rl = $("prep-resource-list"); rl.replaceChildren();
      $("prep-resources").hidden = !res;
      if (res && res.status !== "ok") rl.append(el("li", { class: "empty" }, `Recherche ${res.status === "unavailable" ? "indisponible" : "en échec"}.`));
      else if (res && !res.sources.length) rl.append(el("li", { class: "empty" }, "Aucune source retenue."));
      for (const s of (res && res.sources) || []) {
        const li = el("li"), a = el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.title);
        li.append(a, el("span", { class: "meta" }, ` · ${s.host} · ${res.label}`));
        rl.append(li);
      }
      $("prep-result").hidden = false;
    }
    const trace = [`hash ${job.case_hash.slice(0, 12)}`, job.preparation_version];
    if (job.provider_session_id) trace.push(`session H ${job.provider_session_id}`);
    if (typeof job.elapsed_s === "number") trace.push(`${job.elapsed_s.toFixed(1)} s`);
    $("prep-trace").textContent = trace.join(" · ");
    $("prep-tech").hidden = false;
  }
  updatePrepareButton();
}

function pollPrep(sid) {
  clearTimeout(ui.timers[sid]);
  ui.timers[sid] = setTimeout(async () => {
    const job = ui.prep[sid];
    if (!job) return;
    try {
      const data = await api(`/api/workspace/preparations/${encodeURIComponent(job.id)}`);
      ui.prep[sid] = data.preparation;
    } catch (e) { if (ui.selected === sid) showError(`Suivi de la préparation : ${e.message}`); }
    if (ui.selected === sid) renderPrep();
    if (ACTIVE.includes(ui.prep[sid].status)) pollPrep(sid);
  }, 1500);
}

async function prepare() {
  const s = student(ui.selected);
  if (!s || !s.case_id) return;
  const sid = s.student_id;
  const old = ui.prep[sid];
  $("prepare").disabled = true;
  try {
    const data = await api(`/api/workspace/cases/${encodeURIComponent(s.case_id)}/prepare`, { retry: !!(old && old.status === "failed") });
    ui.prep[sid] = data.preparation;
    showError("");
    if (ACTIVE.includes(data.preparation.status)) pollPrep(sid);
  } catch (e) { showError(`Préparation impossible : ${e.message}`); }
  if (ui.selected === sid) renderPrep();
}

// ---- draft and approval ---------------------------------------------------------------------------------

function updateApprove() {
  const text = $("draft").value;
  const n = chars(text);
  const counter = $("counter");
  counter.textContent = n > MAX_CHARS
    ? `${n} / ${MAX_CHARS} caractères : trop long de ${n - MAX_CHARS}. Raccourcissez, rien n’est tronqué.`
    : `${n} / ${MAX_CHARS} caractères (limite PRONOTE)`;
  counter.classList.toggle("over", n > MAX_CHARS);
  const prev = $("previous").value.trim();
  $("replace-confirm").hidden = !prev;
  $("replace-old").textContent = prev;
  $("replace-new").textContent = text.trim();
  if (!prev) $("confirm-replace").checked = false;
  $("approve").disabled = !ui.selected || n === 0 || n > MAX_CHARS || ui.approving || ui.stopped
    || (!!prev && !$("confirm-replace").checked);
}

async function approve() {
  const s = student(ui.selected);
  if (!s || ui.approving) return;
  const text = $("draft").value;
  const prev = $("previous").value.trim();
  ui.approving = true; updateApprove();
  const msg = $("approve-msg");
  msg.textContent = "Envoi…";
  try {
    const r = await api("/api/workspace/approve", {
      student_id: s.student_id, student_name: s.display_name, course: ui.course, text,
      previous_value: prev || null, confirm_replace: !!prev && $("confirm-replace").checked,
    });
    ui.drafts[s.student_id] = ""; ui.previous[s.student_id] = "";
    if (ui.selected === s.student_id) { $("draft").value = ""; $("previous").value = ""; $("confirm-replace").checked = false; }
    msg.textContent = r.duplicate ? `Déjà en file pour ${s.display_name} (${r.item.item_id}).`
                                  : `Correction en file pour ${s.display_name} : ${r.item.item_id}.`;
    refresh();
  } catch (e) {
    msg.textContent = `Refusé : ${e.message}`;
  } finally { ui.approving = false; updateApprove(); }
}

// ---- execution and results ------------------------------------------------------------------------------

function renderQueue() {
  const s = student(ui.selected);
  const items = s ? ui.items.filter((it) => it.student === s.display_name) : [];
  const list = $("queue");
  list.replaceChildren();
  for (const it of items) {
    const li = el("li", { class: "item", title: it.item_id });
    const head = el("div", { class: "jhead" });
    head.append(badge(shown(it)), el("span", { class: "source-tag" }, SOURCES[it.source] || it.source || ""),
                el("span", { class: "meta" }, it.retry_of ? "nouvelle tentative" : ""));
    li.append(head, el("p", {}, it.text));
    if (it.previous_value) li.append(el("p", { class: "meta" }, `Remplace : ${it.previous_value}`));
    list.append(li);
  }
  const summary = $("queue-summary");
  summary.replaceChildren();
  for (const [label, sts] of GROUPS) {
    const n = items.filter((it) => sts.includes(shown(it))).length;
    if (n) summary.append(el("span", { class: "group" }, `${label} : ${n}`));
  }
  summary.hidden = !summary.childElementCount;
  $("queue-empty").hidden = items.length > 0;
  $("queue-empty").textContent = s ? `Aucune appréciation en file pour ${s.display_name}.` : "Choisissez un élève.";
}

function diffInto(node, text, other) {
  let p = 0;
  while (p < text.length && p < other.length && text[p] === other[p]) p++;
  let q = 0;
  while (q < text.length - p && q < other.length - p && text[text.length - 1 - q] === other[other.length - 1 - q]) q++;
  node.replaceChildren(document.createTextNode(text.slice(0, p)));
  const mid = text.slice(p, text.length - q);
  if (mid) node.append(el("mark", {}, mid));
  else if (text !== other) node.append(el("mark", { "aria-label": "texte manquant" }, "∅"));
  node.append(document.createTextNode(text.slice(text.length - q)));
}

function renderJournal() {
  const byId = Object.fromEntries(ui.items.map((it) => [it.item_id, it]));
  const list = $("journal-list");
  list.replaceChildren();
  const lines = [...ui.journal].reverse();
  for (const ev of lines) {
    const it = byId[ev.item_id];
    const li = el("li", { class: "jline", title: ev.item_id || "" });
    const head = el("div", { class: "jhead" });
    head.append(badge(ev.status), el("strong", {}, ev.student || (it && it.student) || "?"),
                el("span", { class: "meta" }, ev.ts ? new Date(ev.ts * 1000).toLocaleTimeString("fr-FR") : ""));
    li.append(head);
    const approved = it ? it.text : (ev.after ?? null);
    if (approved !== null || ev.text_read_back) {
      const cmp = el("div", { class: "compare" });
      const a = el("div"); const b = el("div");
      const pa = el("p"); const pb = el("p");
      diffInto(pa, approved || "", ev.text_read_back || "");
      diffInto(pb, ev.text_read_back || "", approved || "");
      a.append(el("span", { class: "label" }, it && it.source === "automatic_dictation" ? "Texte dicté" : "Texte approuvé"), pa);
      b.append(el("span", { class: "label" }, "Texte relu"), pb);
      cmp.append(a, b);
      li.append(cmp);
    }
    if (ev.student_seen !== undefined && ev.student_seen !== null || ev.status === "verified" || ev.status === "mismatch") {
      const expected = ev.student || (it && it.student) || "";
      const ok = ev.student_seen && nameKey(ev.student_seen) === nameKey(expected);
      li.append(el("p", { class: ok ? "identity" : "identity bad" },
        ev.student_seen ? `Nom rapporté par l’agent : ${ev.student_seen} (${ok ? "correspond à" : "ne correspond pas à"} ${expected})`
                        : `Aucun nom rapporté par l’agent (attendu : ${expected})`));
    }
    if (ev.note) li.append(el("p", { class: "meta" }, ev.note));
    list.append(li);
  }
  $("journal-empty").hidden = lines.length > 0;
}

function renderStop() {
  // A launch-time STOP (review/preview) halts writes exactly like a pressed STOP; only its wording is quiet.
  const preview = ui.stopped && ui.stopMode === "preview";
  $("preview-banner").hidden = !preview;
  $("stop-banner").hidden = !ui.stopped || preview;
  $("stop").disabled = ui.stopped && !preview;
  if (ui.stopped && ui.dict.phase !== "idle") cancelDictation("stop_pressed");
  updateApprove();
  updateMic();
}

async function refresh() {
  try {
    const st = await api("/api/state");
    ui.items = st.items || []; ui.journal = st.journal || []; ui.stopped = !!st.stopped; ui.stopMode = st.stop_mode || null;
    renderQueue(); renderJournal(); renderStop();
  } catch (e) { showError(`État indisponible : ${e.message}`); }
}

async function stop() {
  cancelDictation("stop_pressed");
  try { await api("/api/stop", {}); ui.stopped = true; ui.stopMode = "user"; renderStop(); refresh(); }
  catch (e) { showError(`STOP refusé : ${e.message}`); }
}

async function resume() {
  try { await api("/api/resume", {}); ui.stopped = false; ui.stopMode = null; renderStop(); refresh(); }
  catch (e) { showError(`Reprise refusée : ${e.message}`); }
}

// ---- automatic dictation: microphone -> local WebSocket -> Gladia -> server guards -> queue -------------------

const REASONS = {
  no_known_name: "Aucun nom d’élève de la classe reconnu : dites le prénom et le nom.",
  ambiguous: "Nom ambigu, plusieurs élèves possibles : dites le nom complet.",
  pupil_mismatch: "Le nom dicté n’est pas celui de l’élève sélectionné.",
  low_name_confidence: "Nom reconnu avec trop peu de certitude.",
  low_asr_confidence: "Transcription peu sûre : à relire avant d’écrire.",
  several_comments: "Plusieurs appréciations dans une même dictée : une à la fois.",
  correction_command: "Correction vocale : utilisez « Corriger ou saisir au clavier ».",
  too_long: "Plus de 255 caractères : raccourcissez, rien n’est tronqué.",
  empty: "Rien n’a été entendu.", stopped: "STOP actif : rien n’est écrit.",
  stale_context: "Le contexte a changé : rechargez la page.", unknown_pupil: "Élève inconnu.",
  no_course: "Aucun cours configuré sur le serveur.", unavailable: "Dictée indisponible.",
  speech_to_text_failed: "La transcription a échoué : rien n’est écrit.",
  speech_to_text_timeout: "La transcription n’a pas répondu : rien n’est écrit.",
  pupil_changed: "Élève changé pendant la dictée : rien n’est écrit.",
  stop_pressed: "STOP pendant la dictée : rien n’est écrit.",
  cancelled: "Dictée annulée : rien n’est écrit.", disconnected: "Connexion perdue : rien n’est écrit.",
  spoken_stop: "« Stop » entendu : STOP activé.", bad_turn_id: "Requête invalide.",
};
const DSTATUS = { queued: "En file, en attente d’écriture dans PRONOTE", needs_correction: "À corriger, rien n’est mis en file",
                  refused: "Non mis en file", cancelled: "Dictée annulée", stopped: "STOP activé",
                  interrupted: "Interrompu : état inconnu" };

function updateMic() {
  const b = $("mic"), d = ui.dict;
  b.disabled = !ui.dictation.available || ui.stopped || d.phase === "starting" || d.phase === "finishing";
  b.textContent = d.phase === "listening" ? "Terminer la dictée" : d.phase === "finishing" ? "Transcription…" : "Commencer la dictée";
  b.setAttribute("aria-pressed", String(d.phase === "listening"));
  const st = $("mic-status");
  if (!ui.dictation.available) {
    // Embedded in the teacher workspace: one plain sentence; the technical cause stays in the tooltip.
    const embedded = document.body.classList.contains("embedded") || document.documentElement.classList.contains("embedded");
    st.textContent = embedded ? "Dictée vocale non activée sur ce serveur." : `Dictée indisponible : ${ui.dictation.reason}`;
    st.title = ui.dictation.reason || "";
  }
  else if (ui.stopped && ui.stopMode === "preview") st.textContent = "Mode aperçu : dictée inactive, rien n’est écrit.";
  else if (ui.stopped) st.textContent = "STOP actif : dictée bloquée.";
  else if (d.phase === "starting") st.textContent = "Ouverture du micro…";
  else if (d.phase === "listening" && !d.captured) st.textContent = "Ouverture du micro… attendez ce message avant de parler.";
  else if (d.phase === "listening") st.textContent = "Micro actif : nom de l’élève, puis l’appréciation.";
  else if (d.phase === "finishing") st.textContent = "Micro coupé, fin de la transcription…";
  else st.textContent = "Micro inactif. Une dictée terminée part directement à l’écriture si l’élève et le texte sont clairs.";
}

function releaseMic() {
  const d = ui.dict;
  if (d.node) { d.node.port.onmessage = null; d.node.disconnect(); }
  if (d.source) d.source.disconnect();
  if (d.stream) d.stream.getTracks().forEach((t) => t.stop());
  if (d.ctx) d.ctx.close().catch(() => {});
  d.node = d.source = d.stream = d.ctx = null;
}

function showResult(rec, turn) {
  const box = $("dictation-result");
  box.replaceChildren();
  box.className = `result ${rec.status}`;
  const head = el("p");
  head.append(el("strong", {}, DSTATUS[rec.status] || rec.status));
  box.append(head);
  const startedFor = turn && turn.sid ? student(turn.sid).display_name : "aucun élève sélectionné";
  if (turn && turn.sid !== ui.selected) box.append(el("p", { class: "meta" }, `Dictée commencée pour : ${startedFor}`));
  if (rec.reason) box.append(el("p", {}, REASONS[rec.reason] || rec.reason));
  if (rec.student_name) box.append(el("p", {}, `Élève reconnu : ${rec.student_name}`));
  if (rec.text) box.append(el("p", {}, `Texte : « ${rec.text} »`));
  if (rec.status === "queued") box.append(el("p", { class: "meta" }, `${rec.item_id} · le rédacteur l’écrira et le relira`));
  if (rec.status === "interrupted") box.append(el("p", {}, "Le serveur n’a pas confirmé le résultat : vérifiez la file et le journal, rien n’est renvoyé."));
  if (rec.status === "needs_correction" && (rec.text || rec.transcript)) {
    const fix = el("button", { type: "button", class: "secondary" }, "Corriger");
    fix.addEventListener("click", () => {
      $("correction-box").open = true;
      if (ui.selected) { $("draft").value = rec.text || rec.transcript; updateApprove(); $("draft").focus(); }
      else $("approve-msg").textContent = "Sélectionnez d’abord l’élève voulu.";
    });
    box.append(fix);
  }
  box.hidden = false;
}

function finishTurn() {
  const d = ui.dict;
  releaseMic();
  if (d.ws && d.ws.readyState <= 1) d.ws.close();
  ui.dict = { phase: "idle" };
  updateMic();
}

function onDictationMessage(turnId, m) {
  const d = ui.dict;
  if (d.turnId !== turnId) return;
  if (m.type === "listening") {
    for (const chunk of d.early) d.ws.send(chunk);  // audio captured while the connection opened
    d.early = [];
    d.phase = "listening";
    updateMic();
  } else if (m.type === "final") {
    d.finals.push(m.text);
    $("transcript").textContent = d.finals.join(" ");
  } else if (m.type === "result") {
    finishTurn();
    showResult(m, d);
    refresh();
  }
}

async function startDictation() {
  if (ui.dict.phase !== "idle" || !ui.dictation.available || ui.stopped) return;
  const d = ui.dict = { phase: "starting", turnId: crypto.randomUUID(), sid: ui.selected, finals: [], early: [] };
  $("transcript").textContent = "";
  $("dictation-result").hidden = true;
  updateMic();
  try {
    d.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    d.ctx = new AudioContext();
    if (d.ctx.state === "suspended") await d.ctx.resume();
    await d.ctx.audioWorklet.addModule("static/pcm-worklet.js");
  } catch (e) {
    if (ui.dict === d) { finishTurn(); $("mic-status").textContent = `Micro indisponible (${e.name || e.message}) : utilisez la saisie clavier.`; }
    return;
  }
  if (ui.dict !== d) { d.stream.getTracks().forEach((t) => t.stop()); d.ctx.close().catch(() => {}); return; }
  // capture starts now; chunks wait in d.early until the server is listening, so the first words are kept
  d.early = [];
  d.source = d.ctx.createMediaStreamSource(d.stream);
  d.node = new AudioWorkletNode(d.ctx, "pcm-worklet");
  d.node.port.onmessage = (e) => {
    if (e.data === "flushed") { if (d.onFlushed) d.onFlushed(); return; }
    if (!d.captured) { d.captured = true; updateMic(); }
    if ((d.phase === "listening" || d.phase === "finishing") && d.ws.readyState === 1) d.ws.send(e.data);
    else if (d.phase === "starting" && d.early.length < 300) d.early.push(e.data);
  };
  d.source.connect(d.node);
  d.node.connect(d.ctx.destination);
  const wsUrl = new URL("ws/dictation", location.href);
  wsUrl.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(wsUrl.href);
  d.ws = ws;
  ws.onopen = () => ws.send(JSON.stringify({ type: "start", turn_id: d.turnId, student_id: d.sid, course: ui.course }));
  ws.onmessage = (ev) => onDictationMessage(d.turnId, JSON.parse(ev.data));
  ws.onclose = () => {
    if (ui.dict === d) { finishTurn(); reconcile(d); }  // closed before any result: ask the server, never assume
  };
}

async function endDictation() {
  const d = ui.dict;
  if (d.phase !== "listening") return;
  d.phase = "finishing";
  updateMic();
  if (d.stream) d.stream.getTracks().forEach((t) => t.stop());  // microphone off at once
  await new Promise((resolve) => {  // the worklet posts its last partial chunk, then "flushed"
    d.onFlushed = resolve;
    d.node.port.postMessage("flush");
    setTimeout(resolve, 500);
  });
  releaseMic();
  if (ui.dict === d && d.ws && d.ws.readyState === 1) d.ws.send(JSON.stringify({ type: "end" }));
}

function cancelDictation(reason) {
  const d = ui.dict;
  if (d.phase === "idle") return;
  if (d.ws && d.ws.readyState === 1) d.ws.send(JSON.stringify({ type: "cancel", reason }));
  finishTurn();
  reconcile(d);  // the server may have queued the turn just before the cancel: show what it recorded
}

async function reconcile(d) {
  showResult({ status: "interrupted" }, d);
  for (let attempt = 0; attempt < 5; attempt++) {
    await new Promise((r) => setTimeout(r, 400 * (attempt + 1)));
    try {
      const r = await fetch(`api/workspace/dictations/${encodeURIComponent(d.turnId)}`);
      if (r.ok) { showResult((await r.json()).dictation, d); refresh(); return; }
    } catch (_) { /* server unreachable: keep the unknown state */ }
  }
  refresh();
}

// ---- observation inside Calli: opening a source proposes a preparation (server validates and dedupes) ----------

const KINDS = { observed: "Observé dans Calli", model_tool: "Outil appelé par H", app_api: "Appel d’API", check: "Vérification" };

function renderObserve() {
  $("observe-status").textContent = ui.observePaused ? "Assistance parallèle en pause" : "Assistance parallèle active · dans Calli";
  $("observe-toggle").textContent = ui.observePaused ? "Reprendre" : "Mettre en pause";
  $("observe-toggle").setAttribute("aria-pressed", String(ui.observePaused));
}

async function toggleObserve() {
  try { ui.observePaused = (await api("/api/workspace/observation", { paused: !ui.observePaused })).paused; }
  catch (e) { showError(`Pause impossible : ${e.message}`); }
  renderObserve();
}

async function observeOpen(data, documentId) {
  const sid = data.case.student_id;
  if (ui.observePaused || ui.selected !== sid) return;
  const key = `${data.case.case_hash}:${documentId}`;
  ui.observed = ui.observed || {};
  if (ui.observed[key]) return;  // one event per source and case version in this page
  ui.observed[key] = true;
  try {
    const r = await api("/api/workspace/observations", {
      event_id: crypto.randomUUID(), event_type: "document_opened", source_kind: "calli_workspace",
      student_id: sid, course: ui.course, case_id: data.case.case_id, document_id: documentId,
      case_hash: data.case.case_hash, observed_at: new Date().toISOString() });
    if (r.preparation) {
      ui.prep[sid] = r.preparation;
      if (ACTIVE.includes(r.preparation.status)) pollPrep(sid);
      if (ui.selected === sid) renderPrep();
    }
  } catch (e) { ui.observed[key] = false; showError(`Observation refusée : ${e.message}`); }
}

async function init() {
  const editReplacement = () => { $("confirm-replace").checked = false; updateApprove(); };
  $("draft").addEventListener("input", editReplacement);
  $("previous").addEventListener("input", editReplacement);
  $("confirm-replace").addEventListener("change", updateApprove);
  $("approve").addEventListener("click", approve);
  $("observe-toggle").addEventListener("click", toggleObserve);
  $("mic").addEventListener("click", () => (ui.dict.phase === "listening" ? endDictation() : startDictation()));
  $("prepare").addEventListener("click", prepare);
  $("stop").addEventListener("click", stop);
  $("resume").addEventListener("click", resume);
  try {
    const data = await api("/api/workspace/cases");
    ui.roster = data.roster; ui.course = data.course; ui.preparer = data.preparer;
    ui.dictation = data.dictation || ui.dictation;
    ui.observePaused = !!(data.observation && data.observation.paused);
    const c = contextParts(ui.course);
    $("course-line").textContent = ui.course ? `Classe ${c.classe} · ${c.matiere} · ${c.periode}` : "Aucun cours configuré.";
    if (data.cases_error) showError(data.cases_error);
  } catch (e) { showError(`Espace indisponible : ${e.message}`); }
  renderRoster(); renderHeader(); renderCase(); renderPrep(); updateApprove(); updateMic(); renderObserve();
  // ?student=sNN (from the host workspace's pupil list) preselects that pupil, only if it is on this roster.
  const wanted = new URLSearchParams(location.search).get("student");
  if (wanted && ui.roster.some((s) => s.student_id === wanted)) await selectPupil(wanted);
  await refresh();
  setInterval(refresh, 2000);
}

init();
