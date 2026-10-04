/* Lead Finder page: import businesses, check their sites, review and approve. */
const $ = (sel) => document.querySelector(sel);
const PAGE = 50;

const ISSUE_LABELS = {
  site_down: ["Site won't load", "danger"],
  parked: ["Domain parked", "danger"],
  social_only: ["Social page only", "warn"],
  no_website: ["No website", "warn"],
  no_https: ["Not secure", "danger"],
  no_mobile: ["Not mobile friendly", "warn"],
  outdated: ["Outdated", "warn"],
  builder: ["Site builder", "warn"],
  slow: ["Slow", "warn"],
};
const HOOK_ORDER = Object.keys(ISSUE_LABELS);

let summary = null;
let status = "ready";
let leads = [];
let total = 0;
let selected = new Set();
let pollTimer = null;
let searchTimer = null;

function esc(value) {
  const el = document.createElement("span");
  el.textContent = value == null ? "" : String(value);
  return el.innerHTML;
}

function showMessage(text, type = "") {
  const box = $("#leads-message");
  box.textContent = text;
  box.className = `message ${type}`.trim();
  box.hidden = false;
  Motion.pulse(box);
}

async function api(path, body) {
  const options = body === undefined
    ? { cache: "no-store" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function fmt(n) { return Number(n || 0).toLocaleString(); }

function ago(iso) {
  if (!iso) return "never";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/* ── Summary / KPIs ─────────────────────────────────────────────── */
function renderSummary() {
  const c = summary.counts;
  const checked = c.total - c.new;
  Motion.countUp($("#stat-total"), c.total);
  $("#stat-total-note").textContent = c.total ? `${fmt(c.new)} sites not checked yet` : "Import a state to start";
  const pct = c.total ? Math.round((checked / c.total) * 100) : 0;
  $("#stat-checked-bar").style.width = `${pct}%`;
  $("#stat-checked-note").textContent = `${pct}% checked`;

  Motion.countUp($("#stat-ready"), c.ready);
  const days = [...summary.daily].reverse();
  const max = Math.max(1, ...days.map((d) => d.found));
  $("#found-bars").innerHTML = days.map((d) => `<i style="height:${Math.max(3, (d.found / max) * 28)}px" title="${esc(d.day)}: ${d.found} found"></i>`).join("");
  const today = summary.daily[0];
  const isToday = today && today.day === new Date().toLocaleDateString("en-CA");
  $("#found-note").textContent = today ? `${fmt(today.found)} found ${isToday ? "today" : `on ${today.day}`} from ${fmt(today.checked)} sites` : "No sites checked yet";

  Motion.countUp($("#stat-approved"), c.approved);
  const s = summary.settings;
  const perDay = s.send_enabled ? s.per_day : 0;
  $("#stat-approved-note").textContent = s.send_enabled
    ? (c.approved ? `About ${Math.ceil(c.approved / Math.max(1, perDay))} weekday${Math.ceil(c.approved / Math.max(1, perDay)) === 1 ? "" : "s"} of sends at ${perDay}/day` : "Approve leads to queue them")
    : "Sending is off";
  $("#stat-approved-note").className = `kpi-delta ${s.send_enabled ? "" : "warn"}`;
  Motion.countUp($("#stat-sent"), c.sent);

  $("#review-desc").textContent = `${fmt(c.ready)} ready · ${fmt(c.approved)} approved · ${fmt(c.no_email)} no email · ${fmt(c.dead + c.bad_email)} dead or bad`;

  const rel = summary.last_release ? `Overture release ${summary.last_release}` : "Nothing imported yet";
  $("#import-meta").textContent = `${rel}. Last import ${ago(summary.last_import)}. ` +
    (summary.by_state.length ? summary.by_state.map((r) => `${r.state || "?"}: ${fmt(r.total)}`).join(" · ") : "");

  document.querySelectorAll("#status-tabs [data-status]").forEach((tab) => {
    const n = c[tab.dataset.status] || 0;
    tab.textContent = `${tab.textContent.replace(/\s*\(.*\)$/, "")} (${fmt(n)})`;
  });
  renderJob(summary.job);
}

function renderSettings() {
  const s = summary.settings;
  $("#states-box").innerHTML = summary.states.map((st) => `
    <label class="lf-chip"><input type="checkbox" name="state" value="${st}" ${s.states.includes(st) ? "checked" : ""}><span>${st}</span></label>`).join("");
  $("#categories-box").innerHTML = summary.categories.map((cat) => `
    <label class="lf-chip"><input type="checkbox" name="category" value="${cat.key}" ${s.categories.includes(cat.key) ? "checked" : ""}><span>${esc(cat.label)}</span></label>`).join("");
  updateStateCount();

  $("#send-enabled").checked = s.send_enabled;
  $("#per-day").value = s.per_day;
  $("#nightly-enabled").checked = s.nightly_enabled;
  $("#nightly-limit").value = s.nightly_limit;
  $("#skip-healthy").checked = s.skip_healthy_sites;
  const hour = $("#nightly-hour");
  hour.innerHTML = Array.from({ length: 24 }, (_, h) => {
    const label = new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });
    return `<option value="${h}" ${h === s.nightly_hour ? "selected" : ""}>${label}</option>`;
  }).join("");
  updateShare();
}

function updateStateCount() {
  const n = document.querySelectorAll('input[name="state"]:checked').length;
  $("#states-count").textContent = n ? `(${n} selected)` : "";
}

function updateShare() {
  const daily = (summary && summary.daily_target) || 200;
  const per = Math.max(0, Number($("#per-day").value || 0));
  const on = $("#send-enabled").checked;
  $("#realtor-share").value = on ? `${Math.max(0, daily - per)} of ${daily}` : `${daily} of ${daily}`;
  const nightly = $("#nightly-enabled").checked;
  $("#send-summary").innerHTML = on
    ? `<span>Weekdays from 10 AM: <strong>${per} business leads</strong> + realtors, through your Gmail with bounce and opt-out checks.</span>`
    : `<span>Business leads are <strong>not being sent</strong>. Turn sending on when your queue looks good.</span>`;
  if (nightly) {
    $("#send-summary").innerHTML += `<span class="muted"> Nightly check: ${fmt($("#nightly-limit").value)} sites.</span>`;
  }
}

/* ── Background job status ──────────────────────────────────────── */
function renderJob(job) {
  const box = $("#job-box");
  const busy = Boolean(job && job.running);
  $("#import-btn").disabled = busy;
  $("#crawl-btn").disabled = busy;
  if (!job || !job.message) { box.hidden = true; return; }
  box.hidden = false;
  box.classList.toggle("is-done", !busy);
  $("#job-text").textContent = job.error ? job.message : job.message;
  $("#job-text").style.color = job.error ? "var(--danger)" : "";
  const pct = job.total ? Math.round((job.progress / job.total) * 100) : (busy ? 8 : 100);
  $("#job-bar").style.width = `${pct}%`;
  if (busy && !pollTimer) pollTimer = setInterval(poll, 3000);
  if (!busy && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function poll() {
  try {
    const wasRunning = summary && summary.job && summary.job.running;
    summary = await api("/api/leads/summary");
    renderSummary();
    if (wasRunning && !summary.job.running) loadLeads(true);
  } catch (error) { /* keep polling */ }
}

async function startJob(body) {
  try {
    await saveSettings(true);
    await api("/api/leads/job", body);
    showMessage(body.job === "import"
      ? "Import started. Pulling one state usually takes a few minutes."
      : "Website check started. You can leave this page; it keeps running.", "success");
    summary.job = { running: true, message: "Starting...", progress: 0, total: 0 };
    renderJob(summary.job);
  } catch (error) {
    showMessage(error.message, "error");
  }
}

/* ── Settings ───────────────────────────────────────────────────── */
async function saveSettings(quiet = false) {
  const states = [...document.querySelectorAll('input[name="state"]:checked')].map((i) => i.value);
  const categories = [...document.querySelectorAll('input[name="category"]:checked')].map((i) => i.value);
  const body = {
    states, categories,
    send_enabled: $("#send-enabled").checked,
    per_day: Number($("#per-day").value),
    nightly_limit: Number($("#nightly-limit").value),
    nightly_hour: Number($("#nightly-hour").value),
    skip_healthy_sites: $("#skip-healthy").checked,
  };
  if ($("#nightly-enabled").checked !== summary.settings.nightly_enabled) body.nightly_enabled = $("#nightly-enabled").checked;
  try {
    const data = await api("/api/leads/settings", body);
    summary.settings = data.settings;
    if (!quiet) showMessage("Settings saved.", "success");
    renderSummary();
  } catch (error) {
    showMessage(error.message, "error");
    throw error;
  }
}

/* ── Review table ───────────────────────────────────────────────── */
function topIssue(issues) {
  for (const key of HOOK_ORDER) if ((issues || []).includes(key)) return key;
  return null;
}

function issuePill(lead) {
  const key = topIssue(lead.issues);
  if (!key) return `<span class="pill muted">Looks fine</span>`;
  const [label, tone] = ISSUE_LABELS[key];
  let text = label;
  if (key === "builder" && lead.platform) text = lead.platform;
  if (key === "outdated" && lead.copyright_year) text = `© ${lead.copyright_year}`;
  const more = (lead.issues || []).filter((i) => ISSUE_LABELS[i]).length - 1;
  return `<span class="pill ${tone}" title="${esc((lead.issues || []).map((i) => (ISSUE_LABELS[i] || [i])[0]).join(", "))}">${esc(text)}${more > 0 ? ` +${more}` : ""}</span>`;
}

function selectable() { return status === "ready" || status === "approved" || status === "rejected"; }

function renderTable() {
  const table = $("#leads-table");
  const check = selectable();
  $("#bulk-bar").hidden = !check;
  $("#approve-btn").hidden = status === "approved";
  $("#approve-next-btn").hidden = status !== "ready";
  $("#reject-btn").hidden = status === "rejected";
  $("#unapprove-btn").hidden = status === "ready";
  if (!leads.length) {
    const empty = {
      ready: summary && summary.counts.total ? "No leads waiting. Check more sites to find emails." : "Nothing here yet. Pick a state above and import businesses.",
      approved: "Nothing approved yet.",
      sent: "Nothing sent yet.",
      no_email: "No sites without an email so far.",
      rejected: "Nothing rejected.",
    }[status];
    table.innerHTML = `<div class="empty-state">${esc(empty)}</div>`;
    $("#more-btn").hidden = true;
    updateSelection();
    return;
  }
  const rowClass = `table-row lead-row${check ? "" : " no-check"}`;
  const head = `<div class="${rowClass} table-head">${check ? "<span></span>" : ""}<span>Business</span><span>Email</span><span class="lf-hide-sm">Location</span><span class="lf-hide-sm">Opening line</span><span></span></div>`;
  const rows = leads.map((l) => `
    <div class="${rowClass}" data-id="${l.id}">
      ${check ? `<span><input type="checkbox" name="lead" value="${l.id}" ${selected.has(l.id) ? "checked" : ""} aria-label="Select ${esc(l.name)}"></span>` : ""}
      <span class="cell-stack"><span class="ellipsis strong">${esc(l.name)}</span><small>${esc((l.category || "").replace(/_/g, " "))}${l.website ? ` · <a href="${esc(l.website)}" target="_blank" rel="noreferrer">${esc(l.domain || "site")}</a>` : ""}</small></span>
      <span class="cell-stack"><span class="ellipsis">${esc(l.email || "–")}</span><small>${esc(l.status === "sent" ? `sent ${ago(l.sent_at)}` : (l.status_detail || (l.email_source === "overture" ? "from Overture listing" : l.email_source ? "published on their site" : "")))}</small></span>
      <span class="muted ellipsis lf-hide-sm">${esc([l.city, l.state].filter(Boolean).join(", "))}</span>
      <span class="lf-hide-sm">${status === "no_email" ? `<span class="muted">${esc(l.phone || "no phone")}</span>` : issuePill(l)}</span>
      <span class="right">${l.email ? `<button class="btn ghost" type="button" data-preview="${l.id}">Preview</button>` : ""}</span>
    </div>`).join("");
  table.innerHTML = head + rows;
  Motion.rows(table);
  $("#more-btn").hidden = leads.length >= total;
  updateSelection();
  document.dispatchEvent(new CustomEvent("listrendered"));
}

function updateSelection() {
  const n = selected.size;
  $("#selected-count").textContent = `${n} selected`;
  $("#approve-btn").disabled = !n;
  $("#reject-btn").disabled = !n;
  $("#unapprove-btn").disabled = !n;
  const boxes = document.querySelectorAll('input[name="lead"]');
  $("#check-all").checked = boxes.length > 0 && [...boxes].every((b) => b.checked);
}

async function loadLeads(reset = true) {
  if (reset) { leads = []; selected = new Set(); }
  const q = $("#page-search").value.trim();
  try {
    const data = await api(`/api/leads/list?status=${status}&limit=${PAGE}&offset=${leads.length}&q=${encodeURIComponent(q)}`);
    leads = leads.concat(data.leads);
    total = data.total;
    renderTable();
  } catch (error) {
    $("#leads-table").innerHTML = `<div class="empty-state">${esc(error.message)}</div>`;
  }
}

async function review(action, ids) {
  try {
    const body = action === "approve_next" ? { action, n: 25 } : { action, ids };
    const data = await api("/api/leads/review", body);
    const verb = { approve: "Approved", approve_next: "Approved", reject: "Rejected", unapprove: "Moved back" }[action];
    showMessage(`${verb} ${fmt(data.changed)} lead${data.changed === 1 ? "" : "s"}.`, "success");
    summary = await api("/api/leads/summary");
    renderSummary();
    loadLeads(true);
  } catch (error) {
    showMessage(error.message, "error");
  }
}

async function openPreview(id) {
  try {
    const data = await api(`/api/leads/preview?id=${id}`);
    $("#preview-meta").textContent = `To ${data.to} · Subject: ${data.subject}`;
    $("#preview-body").textContent = data.text;
    $("#preview-dialog").showModal();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

/* ── Wiring ─────────────────────────────────────────────────────── */
function wire() {
  $("#states-box").addEventListener("change", updateStateCount);
  ["#per-day", "#send-enabled", "#nightly-enabled", "#nightly-limit"].forEach((s) => $(s).addEventListener("input", updateShare));
  $("#save-settings").addEventListener("click", () => saveSettings().catch(() => {}));
  $("#import-btn").addEventListener("click", () => {
    const n = document.querySelectorAll('input[name="state"]:checked').length;
    if (!n) { showMessage("Pick at least one state first.", "error"); return; }
    startJob({ job: "import" });
  });
  $("#crawl-btn").addEventListener("click", () => startJob({ job: "crawl", limit: Number($("#crawl-limit").value || 500) }));

  $("#status-tabs").addEventListener("click", (event) => {
    const tab = event.target.closest("[data-status]");
    if (!tab) return;
    document.querySelectorAll("#status-tabs [data-status]").forEach((t) => {
      const on = t === tab;
      t.classList.toggle("is-active", on);
      t.setAttribute("aria-selected", String(on));
    });
    status = tab.dataset.status;
    loadLeads(true);
  });

  $("#leads-table").addEventListener("change", (event) => {
    if (event.target.name !== "lead") return;
    const id = Number(event.target.value);
    event.target.checked ? selected.add(id) : selected.delete(id);
    updateSelection();
  });
  $("#leads-table").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-preview]");
    if (btn) openPreview(Number(btn.dataset.preview));
  });
  $("#check-all").addEventListener("change", (event) => {
    document.querySelectorAll('input[name="lead"]').forEach((box) => {
      box.checked = event.target.checked;
      const id = Number(box.value);
      box.checked ? selected.add(id) : selected.delete(id);
    });
    updateSelection();
  });
  $("#approve-btn").addEventListener("click", () => review("approve", [...selected]));
  $("#reject-btn").addEventListener("click", () => review("reject", [...selected]));
  $("#unapprove-btn").addEventListener("click", () => review("unapprove", [...selected]));
  $("#approve-next-btn").addEventListener("click", () => review("approve_next"));
  $("#more-btn").addEventListener("click", () => loadLeads(false));
  $("#preview-close").addEventListener("click", () => $("#preview-dialog").close());
  $("#preview-dialog").addEventListener("click", (event) => { if (event.target.id === "preview-dialog") event.target.close(); });

  // Topbar search filters server side (the list is paged).
  $("#page-search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadLeads(true), 250);
  });
}

async function init() {
  wire();
  try {
    summary = await api("/api/leads/summary");
    renderSettings();
    renderSummary();
    loadLeads(true);
  } catch (error) {
    showMessage(`Could not load the Lead Finder: ${error.message}`, "error");
    $("#leads-table").innerHTML = '<div class="empty-state">Restart the dashboard and try again.</div>';
  }
}

init();
