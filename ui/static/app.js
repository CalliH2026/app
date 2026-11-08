"use strict";
// Approval screen. Every piece of text from the server is set with textContent, never as HTML:
// what the agent read on a page is data, not markup.

const STATES = {
  pending: { icon: "○", word: "pending" },
  in_progress: { icon: "◐", word: "writing" },
  verified: { icon: "✔", word: "verified" },
  mismatch: { icon: "✖", word: "mismatch" },
  not_found: { icon: "?", word: "not found" },
  aborted: { icon: "■", word: "aborted" },
  abstained: { icon: "‖", word: "abstained" },
  written: { icon: "✎", word: "written" },
  false_success: { icon: "✖", word: "false success" },
};

const $ = (id) => document.getElementById(id);
const ui = {
  proposals: [],   // structured items waiting for the teacher, the first one is shown
  correcting: false,
  stopped: false,
  approving: false,  // waiting for the sourced suggestion after Approve
  roster: [],
};

function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `${r.status}`);
  return data;
}

// Illustrated avatar (static/avatars/<student_id>.svg), or the initials in a coloured circle when the
// roster has no file for this student or the image fails to load.
function rosterEntry(name) { return ui.roster.find((s) => s.display_name === name || s.student_id === name); }

function initialsNode(s, name) {
  const fallback = name.split(/\s+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";
  const n = el("span", { class: "avatar avatar-initials", "aria-hidden": "true" }, (s && s.initials) || fallback);
  if (s && s.color) n.style.backgroundColor = s.color;
  return n;
}

function avatarNode(name) {
  const s = rosterEntry(name);
  if (!s || !s.avatar) return initialsNode(s, name || "");
  const img = el("img", { class: "avatar", src: s.avatar, alt: "", width: "40", height: "40" });
  img.addEventListener("error", () => img.replaceWith(initialsNode(s, name)), { once: true });
  return img;
}

function say(id, text) { $(id).textContent = text || ""; }

// ---- proposal --------------------------------------------------------

function current() { return ui.proposals[0] || null; }

function selectedStudent() {
  if (ui.correcting && $("student-select").value) return $("student-select").value;
  const checked = document.querySelector('input[name="candidate"]:checked');
  return checked ? checked.value : "";
}

function updateApprove() {
  $("approve").disabled = !current() || !selectedStudent() || !$("proposal-text").value.trim() || ui.stopped ||
    ui.approving;
}

function renderProposal() {
  const p = current();
  $("proposal").hidden = !p;
  $("advice").hidden = true;
  if (!p) return;
  say("proposal-more", ui.proposals.length > 1 ? `(1 of ${ui.proposals.length})` : "");
  const list = $("candidate-list");
  list.replaceChildren();
  p.candidates.forEach((c, i) => {
    const id = `cand-${i}`;
    const input = el("input", { type: "radio", name: "candidate", id, value: c.display_name });
    if (p.candidates.length === 1) input.checked = true;  // a tie never gets a default
    input.addEventListener("change", updateApprove);
    const label = el("label", { for: id });
    label.append(avatarNode(c.student_id), document.createTextNode(c.display_name));
    const row = el("div", { class: "candidate" });
    row.append(input, label);
    list.append(row);
  });
  if (p.candidates.length === 0) {
    list.append(el("p", {}, "No student recognized: choose one below."));
    setCorrecting(true);
  } else {
    setCorrecting(false);
  }
  say("proposal-msg", p.candidates.length > 1 ? `${p.candidates.length} students match: choose one.` : "");
  $("proposal-text").value = p.text;
  updateApprove();
}

function setCorrecting(on) {
  ui.correcting = on;
  $("correct-student").hidden = !on;
  $("proposal-text").readOnly = !on;
  $("correct").setAttribute("aria-pressed", String(on));
  if (!on) $("student-select").value = "";
  updateApprove();
}

function nextProposal() {
  ui.proposals.shift();
  renderProposal();
  if (!current()) $("utterance").focus();
}

async function propose() {
  const text = $("utterance").value.trim();
  if (!text) return;
  say("message", "");
  try {
    const data = await api("/api/structure", { text });
    for (const it of data.items) {
      const p = ui.proposals[ui.proposals.length - 1];  // a correction is about the last dictated comment
      if (it.kind === "comment") ui.proposals.push(it);
      else if (it.kind === "correction_text" && p) p.text = it.text;
      else if (it.kind === "reassign" && p) p.candidates = it.candidates;
      else if (it.kind === "stop") openStopConfirm();
      else if (it.kind === "undo") say("message", "Undo is not on this screen yet: nothing was changed.");
      else say("message", "Nothing to apply that to.");
    }
    if (!data.items.length) say("message", "Nothing recognized in this sentence.");
    $("utterance").value = "";
    renderProposal();
    const first = document.querySelector('input[name="candidate"]');
    if (current()) (first && !selectedStudent() ? first : $("approve")).focus();
  } catch (e) {
    say("message", `Could not structure: ${e.message}`);
  }
}

// ---- sourced suggestion (research/advice.py) -------------------------
// Asked once per proposal, on the first Approve. With a suggestion the item is not queued yet: the
// sentence is shown under the text, "Ajouter" appends it to the text, and Approve queues the text as shown.

async function fetchAdvice(text) {
  try {
    return (await api("/api/advice", { text })).suggestion;
  } catch (e) {
    return null;
  }
}

function showAdvice(s) {
  say("advice-text", s.text);
  const a = $("advice-source");
  a.textContent = s.source_name;
  if (/^https?:\/\//i.test(s.source_url)) a.setAttribute("href", s.source_url);
  else a.removeAttribute("href");
  $("advice-add").disabled = false;
  $("advice").hidden = false;
}

function appendSentence(text, sentence) {
  const t = text.trimEnd();
  if (!t) return sentence;
  return /[.!?…]$/.test(t) ? `${t} ${sentence}` : `${t}. ${sentence}`;
}

function addAdvice() {
  const p = current();
  if (!p || !p.suggestion) return;
  $("proposal-text").value = appendSentence($("proposal-text").value, p.suggestion.text);
  $("advice-add").disabled = true;
  updateApprove();
  $("approve").focus();
}

async function approve() {
  const p = current();
  let student = selectedStudent();
  let text = $("proposal-text").value.trim();
  if (!p || !student || !text || ui.approving) return;
  if (!p.adviceAsked) {
    ui.approving = true;
    updateApprove();
    say("proposal-msg", "Looking for a sourced suggestion…");
    const s = await fetchAdvice(text);
    ui.approving = false;
    say("proposal-msg", "");
    p.adviceAsked = true;
    if (current() !== p) return;
    updateApprove();
    if (s && $("proposal-text").value.trim() === text) {
      p.suggestion = s;
      showAdvice(s);
      say("proposal-msg", "Suggestion below: Ajouter appends it to the text; Approve queues the text as shown.");
      $("advice-add").focus();
      return;
    }
    student = selectedStudent();  // the teacher may have changed the student or the text while waiting
    text = $("proposal-text").value.trim();
    if (!student || !text || ui.stopped) return;
  }
  try {
    const data = await api("/api/approve", { student, text, course: $("course").value.trim() || null });
    say("message", data.duplicate ? `Already in the queue for ${student}.` : `Approved for ${student}.`);
    nextProposal();
    refresh();
  } catch (e) {
    say("proposal-msg", `Not approved: ${e.message}`);
  }
}

// ---- STOP ------------------------------------------------------------

function openStopConfirm() {
  $("stop-confirm").hidden = false;
  $("stop-yes").focus();
}

function closeStopConfirm() {
  $("stop-confirm").hidden = true;
  $("stop").focus();
}

async function stop() {
  $("stop-confirm").hidden = true;
  try {
    const data = await api("/api/stop", {});
    say("message", `Stopped; ${data.drained.length} pending item(s) cancelled.`);
  } catch (e) {
    say("message", `STOP failed: ${e.message}. Create the STOP file next to the queue file by hand.`);
  }
  refresh();
  $("resume").focus();
}

async function resume() {
  await api("/api/resume", {});
  say("message", "Resumed: approved items will be written.");
  refresh();
}

// ---- queue and journal view ------------------------------------------

function stateBadge(status) {
  const s = STATES[status] || { icon: "•", word: status };
  const b = el("span", { class: `state state-${status}` });
  b.append(el("span", { class: "icon", "aria-hidden": "true" }, s.icon), el("strong", {}, s.word));
  return b;
}

function itemNode(it) {
  const li = el("li", { class: `item item-${it.status}` });
  const head = el("div", { class: "item-head" });
  head.append(avatarNode(it.student), stateBadge(it.status), el("span", { class: "student" }, it.student),
              el("span", { class: "meta" }, it.item_id));
  li.append(head, el("p", { class: "text" }, it.text));
  if (it.text_read_back) {
    const rb = el("p", { class: "readback" });
    rb.append(el("span", { class: "label" }, "read back: "), document.createTextNode(it.text_read_back));
    li.append(rb);
  }
  const facts = [];
  if (typeof it.similarity === "number") facts.push(`similarity ${it.similarity.toFixed(3)}`);
  if (typeof it.seconds === "number") facts.push(`${it.seconds.toFixed(1)} s`);
  if (it.note) facts.push(it.note);
  if (facts.length) li.append(el("p", { class: "meta" }, facts.join(" · ")));
  return li;
}

function renderQueue(items) {
  const list = $("queue");
  list.replaceChildren();
  const retries = {};
  for (const it of items) if (it.retry_of) (retries[it.retry_of] ||= []).push(it);
  for (const it of items) {
    if (it.retry_of) continue;
    const li = itemNode(it);
    const children = retries[it.item_id] || [];
    if (children.length) {
      const sub = el("ol", { class: "items retries", "aria-label": `corrective write for ${it.item_id}` });
      children.forEach((c) => sub.append(itemNode(c)));
      li.append(sub);
    }
    list.append(li);
  }
  $("queue-empty").hidden = items.length > 0;
}

function renderJournal(lines, path) {
  say("journal-path", path ? `from ${path}` : "No journal yet.");
  const list = $("journal");
  list.replaceChildren();
  for (const ev of [...lines].reverse()) {
    const li = el("li", { class: "journal-line" });
    const when = ev.ts ? new Date(ev.ts * 1000).toLocaleTimeString() : "";
    li.append(el("span", { class: "meta" }, when), stateBadge(ev.status),
              el("span", { class: "student" }, ev.student), el("span", { class: "meta" }, ev.item_id));
    if (ev.text_read_back) li.append(el("span", { class: "readback" }, `read back: ${ev.text_read_back}`));
    const facts = [];
    if (typeof ev.similarity === "number") facts.push(`similarity ${ev.similarity.toFixed(3)}`);
    if (typeof ev.seconds === "number") facts.push(`${ev.seconds.toFixed(1)} s`);
    if (facts.length) li.append(el("span", { class: "meta" }, facts.join(" · ")));
    list.append(li);
  }
}

function renderRoster() {
  const list = $("roster");
  list.replaceChildren();
  for (const s of ui.roster) {
    const li = el("li", { class: "roster-entry" });
    li.append(avatarNode(s.student_id), el("span", {}, s.display_name));
    list.append(li);
  }
}

function renderSummary(summary) {
  const parts = Object.entries(summary).map(([k, n]) => `${n} ${(STATES[k] || { word: k }).word}`);
  say("summary", parts.length ? parts.join(", ") : "queue empty");
}

async function refresh() {
  try {
    const s = await api("/api/state");
    ui.stopped = s.stopped;
    $("stop-banner").hidden = !s.stopped;
    $("stop").disabled = s.stopped;
    renderQueue(s.items);
    renderJournal(s.journal, s.journal_path);
    renderSummary(s.summary);
    updateApprove();
  } catch (e) {
    say("summary", `server unreachable (${e.message})`);
  }
}

// ---- wiring ----------------------------------------------------------

async function init() {
  const cfg = await api("/api/config");
  ui.roster = cfg.roster;
  $("course").value = cfg.course || "";
  const sel = $("student-select");
  sel.append(el("option", { value: "" }, "choose a student"));
  for (const s of cfg.roster) sel.append(el("option", { value: s.display_name }, s.display_name));
  renderRoster();
  sel.addEventListener("change", updateApprove);
  $("proposal-text").addEventListener("input", updateApprove);

  $("dictate-form").addEventListener("submit", (e) => { e.preventDefault(); propose(); });
  $("approve").addEventListener("click", approve);
  $("advice-add").addEventListener("click", addAdvice);
  $("correct").addEventListener("click", () => { setCorrecting(!ui.correcting); $("proposal-text").focus(); });
  $("discard").addEventListener("click", () => { say("message", "Discarded."); nextProposal(); });
  $("stop").addEventListener("click", openStopConfirm);
  $("stop-yes").addEventListener("click", stop);
  $("stop-no").addEventListener("click", closeStopConfirm);
  $("resume").addEventListener("click", resume);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      if (!$("stop-confirm").hidden) closeStopConfirm();
      else if (!ui.stopped) openStopConfirm();
      return;
    }
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    const t = e.target;
    if (t.tagName === "BUTTON" || t.tagName === "SELECT") return;  // native activation
    if (t.id === "utterance") { e.preventDefault(); propose(); return; }
    if (current() && t.closest && t.closest("#proposal")) {
      e.preventDefault();
      if (!$("approve").disabled) approve();
    }
  });

  refresh();
  setInterval(refresh, 2000);
  $("utterance").focus();
}

init();
