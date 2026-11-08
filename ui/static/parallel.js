// Calli secondary views over the vendored H Parallel outing and practice (no framework, no external calls).
"use strict";

const $ = (id) => document.getElementById(id);
const FACTS = [["opening_time", "Ouverture"], ["closing_time", "Fermeture"], ["closed_on_date", "Fermé ce jour-là"],
  ["student_unit_price", "Entrée élève"], ["adult_unit_price", "Entrée adulte"], ["group_fee", "Réservation groupe"],
  ["max_group_size", "Taille maximale du groupe"]];
const STATUS = {preparing: "Préparation en cours…", ready: "Prêt.", partial: "Prêt en partie : certaines informations restent à confirmer.",
  failed: "Échec : rien n’a été inventé.", queued: "En attente…", running: "Préparation en cours…",
  review: "À relire avant téléchargement.", approved: "Relu : téléchargement disponible."};

async function api(path, body) {
  const init = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  const response = await fetch(path, init);
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(value.detail || `Erreur ${response.status}`);
  return value;
}

function text(node, value) { node.textContent = value == null ? "" : String(value); return node; }
function el(tag, value, attrs = {}) { const node = text(document.createElement(tag), value); Object.assign(node, attrs); return node; }
function trace(value) { return JSON.stringify(value, null, 2); }
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function outing() {
  const form = $("outing-form");
  const options = await api("/api/parallel/outings/options");
  for (const item of options.classes) form.class_id.append(el("option", item.name || item.id, {value: item.id}));
  for (const item of options.destinations) form.destination_id.append(el("option", item.name || item.id, {value: item.id}));
  for (const [key, value] of Object.entries(options.defaults)) if (form[key] && key !== "mode") form[key].value = value;
  form.hidden = false;
  const existing = new URLSearchParams(location.search).get("outing");
  if (existing) {
    try { $("outing-result").hidden = false; renderOuting(await api(`/api/parallel/outings/${encodeURIComponent(existing)}`)); }
    catch (error) { text($("outing-status"), error.message); }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    const body = Object.fromEntries(new FormData(form));
    body.duration_minutes = Number(body.duration_minutes);
    body.adults = Number(body.adults);
    body.mode = "live";
    try {
      let job = await api("/api/parallel/outings", body);
      history.replaceState(null, "", `?outing=${encodeURIComponent(job.id)}`);
      $("outing-result").hidden = false;
      while (true) {
        renderOuting(job);
        if (job.status !== "preparing") break;
        await sleep(1500);
        job = await api(`/api/parallel/outings/${encodeURIComponent(job.id)}`);
      }
    } catch (error) {
      $("outing-result").hidden = false;
      text($("outing-status"), error.message);
    } finally {
      button.disabled = false;
    }
  });
}

function outingStatus(job) {
  const collected = (job.tasks || []).some((t) => t.id !== "dossier" && t.status === "done");
  if (job.h_outcome) {
    const head = job.h_outcome === "timeout" ? "Délai dépassé : " : "Holo4 n’a pas terminé : ";
    return head + (job.h_error || "") + (collected ? " Les résultats reçus restent affichés, à vérifier."
      : " Aucun outil exécuté : rien n’a été préparé.");
  }
  if (job.calli_view && job.calli_view.nothing_prepared) return "Échec : aucune collecte n’a abouti, rien n’a été préparé.";
  if (job.status === "failed") return `Échec : ${job.error || "rien n’a été inventé."}`;
  return STATUS[job.status] || job.status;
}

function renderOuting(job) {
  const status = $("outing-status");
  text(status, outingStatus(job));
  const nothing = Boolean(job.calli_view && job.calli_view.nothing_prepared);
  status.classList.toggle("p-alert", Boolean(job.h_outcome) || job.status === "failed" || nothing);
  const cancel = job.session_cancel;
  $("outing-cancel").hidden = !cancel;
  text($("outing-cancel"), cancel ? (cancel.state === "cancel_failed" ? "La demande d’arrêt de la session H a échoué."
    : "Arrêt de la session H demandé (non confirmé par H).") : "");
  $("outing-tasks").replaceChildren(...(job.tasks || []).map((t) => {
    const li = el("li", `${t.label}${t.summary ? " — " + t.summary : ""}`);
    li.dataset.status = t.status;
    return li;
  }));
  const visit = job.visit || {};
  $("outing-facts").replaceChildren(...FACTS.flatMap(([key, label]) => {
    const value = visit[key];
    const known = value !== null && value !== undefined;
    const shown = typeof value === "boolean" ? (value ? "oui" : "non") : value;
    return [el("dt", label), el("dd", known ? shown : "non confirmé", {className: known ? "" : "p-unknown"})];
  }));
  const budget = job.budget;
  const box = $("outing-budget");
  if (!budget) {
    box.replaceChildren(el("p", job.status === "preparing" ? "En attente des vérifications." : "Aucun budget établi."));
  } else {
    const table = document.createElement("table");
    for (const line of budget.lines || []) {
      const row = table.insertRow();
      for (const cell of [line.label, line.quantity, line.total == null ? "à confirmer" : `${line.total} €`]) text(row.insertCell(), cell);
    }
    const summary = budget.complete
      ? el("p", `Total : ${budget.total} € · par élève : ${budget.per_student} €`)
      : el("p", `Budget incomplet, à confirmer : ${(budget.missing || []).join(", ")}.`, {className: "p-unknown"});
    box.replaceChildren(table, summary);
  }
  const collected = (job.tasks || []).some((t) => t.id !== "dossier" && t.status === "done");
  $("outing-dossier-box").hidden = !job.dossier || nothing || (Boolean(job.h_outcome) && !collected);
  text($("outing-dossier"), job.dossier ? job.dossier.text : "");
  $("outing-sources").replaceChildren(...((visit.sources || []).map((s) => {
    const li = document.createElement("li");
    li.append(el("a", s.title || s.url, {href: s.url, rel: "noopener noreferrer", target: "_blank"}));
    return li;
  })));
  text($("outing-trace"), trace({id: job.id, status: job.status, h_outcome: job.h_outcome, session_cancel: job.session_cancel,
    session_cleanup: job.session_cleanup, agent: job.agent, session_id: job.session_id,
    tool_calls: job.tool_calls, executions: job.executions, browser_evidence: job.browser_evidence, warnings: job.warnings}));
}

async function practice() {
  const form = $("practice-form");
  form.job.value = new URLSearchParams(location.search).get("job") || "";
  form.hidden = false;
  let current = form.job.value || null;
  if (current) {
    // Opening the page only reads the saved state: no POST, no provider session.
    const state = await api(`/api/parallel/practice/${encodeURIComponent(current)}`).catch((error) => ({status: "failed", message: error.message}));
    if (state.mode && form.querySelector(`input[name="mode"][value="${state.mode}"]`)) form.mode.value = state.mode;
    $("practice-result").hidden = false;
    renderPractice(current, state);
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    current = form.job.value.trim();
    clearFrame();
    try {
      let state = await api(`/api/parallel/practice/${encodeURIComponent(current)}`, {mode: form.mode.value});
      $("practice-result").hidden = false;
      while (true) {
        renderPractice(current, state);
        if (!["queued", "running", "preparing"].includes(state.status)) break;
        await sleep(3000);
        state = await api(`/api/parallel/practice/${encodeURIComponent(current)}`);
      }
    } catch (error) {
      $("practice-result").hidden = false;
      text($("practice-status"), error.message);
    } finally {
      button.disabled = false;
    }
  });
  $("practice-approve").addEventListener("click", async () => {
    try { renderPractice(current, await api(`/api/parallel/practice/${encodeURIComponent(current)}/approve`, {})); }
    catch (error) { text($("practice-status"), error.message); }
  });
}

function clearFrame() {
  const frame = $("practice-frame");
  frame.removeAttribute("src");
  frame.dataset.key = "";
  frame.hidden = true;
}

function renderPractice(job, state) {
  const simulated = state.simulated ? " (simulation, pas une sortie Devin)" : "";
  const ready = state.status === "ready" && Boolean(state.artifact_sha256);
  const reviewed = ready && Boolean(state.approved);
  text($("practice-status"), (ready ? (reviewed ? STATUS.approved : STATUS.review) : (STATUS[state.status] || state.status || "")) + simulated
    + ((state.status === "failed" || state.status === "not_started") && state.message ? ` ${state.message}` : ""));
  const frame = $("practice-frame");
  const key = ready ? `${job}|${state.mode}|${state.artifact_sha256}` : "";
  if (!ready) clearFrame();
  else if (frame.dataset.key !== key) {
    frame.dataset.key = key;
    frame.src = `/api/parallel/practice/${encodeURIComponent(job)}/preview?v=${encodeURIComponent(state.artifact_sha256)}`;
    frame.hidden = false;
  }
  $("practice-approve").hidden = !ready || reviewed;
  const link = $("practice-download");
  link.hidden = !reviewed;
  link.href = reviewed ? `/api/parallel/practice/${encodeURIComponent(job)}/download` : "#";
  text($("practice-trace"), trace({mode: state.mode, simulated: state.simulated, session_url: state.session_url,
    provider_state: state.validation && state.validation.provider_state, artifact_sha256: state.artifact_sha256,
    validation: state.validation, acus_consumed: state.acus_consumed}));
}

(async () => {
  const config = await api("/api/parallel/config").catch(() => ({enabled: false}));
  if (!config.enabled) { $("p-off").hidden = false; return; }
  if (document.body.dataset.view === "sortie") await outing(); else await practice();
})();
