/* Agency Finder page: search Google Maps for web design / SEO agencies,
   review them, preview the pitch, and control agency sending. */
(() => {
  const $ = (id) => document.getElementById(id);
  const PAGE = 50;
  let summary = null;
  let status = "ready";
  let offset = 0;
  let total = 0;
  let rows = [];
  let selected = new Set();
  let pollTimer = null;
  let searchTimer = null;

  const esc = (v) => { const el = document.createElement("span"); el.textContent = v == null ? "" : String(v); return el.innerHTML; };
  const fmt = (n) => Number(n || 0).toLocaleString();

  async function api(path, body) {
    const response = await fetch(`/api/agencies/${path}`, body === undefined ? { cache: "no-store" } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }

  function showMessage(text, type = "") {
    const box = $("agency-message");
    box.textContent = text;
    box.className = `message ${type}`.trim();
    box.hidden = false;
    if (window.Motion) Motion.pulse(box);
  }

  /* ── Summary ─────────────────────────────────────────────────── */
  function renderSummary() {
    const c = summary.counts;
    const count = (el, n) => (window.Motion ? Motion.countUp(el, n) : (el.textContent = fmt(n)));
    count($("ag-total"), c.total);
    $("ag-total-note").textContent = c.total ? `${fmt(c.no_email)} without an email` : "Searches run on the Mac";
    const done = summary.searches_total - summary.searches_left;
    const pct = summary.searches_total ? Math.round((done / summary.searches_total) * 100) : 0;
    $("ag-search-bar").style.width = `${pct}%`;
    $("ag-search-note").textContent = `${fmt(done)} of ${fmt(summary.searches_total)} searches done`;

    count($("ag-ready"), c.ready + c.approved);
    $("ag-ready-note").textContent = `${fmt(c.ready)} ready · ${fmt(c.approved)} approved`;
    const days = [...summary.daily].reverse();
    const max = Math.max(1, ...days.map((d) => d.found));
    $("ag-found-bars").innerHTML = days.map((d) => `<i style="height:${Math.max(3, (d.found / max) * 28)}px" title="${esc(d.day)}: ${d.found} found"></i>`).join("");
    const t = summary.daily[0];
    $("ag-found-note").textContent = t ? `${fmt(t.found)} found on ${t.day} from ${fmt(t.searched)} searches` : "Pushed from the Mac";

    const st = summary.sent_today;
    const agencyCap = summary.settings.send_enabled ? summary.settings.per_day : 0;
    const cap = summary.client_per_day + agencyCap;
    count($("ag-today"), st.client + st.agency);
    $("ag-today-note").textContent = `of ${fmt(cap)} today`;
    $("ag-today-bar").style.width = `${cap ? Math.min(100, Math.round(((st.client + st.agency) / cap) * 100)) : 0}%`;
    $("ag-today-split").textContent = `${fmt(st.client)} client · ${fmt(st.agency)} agency`;
    count($("ag-sent"), c.sent);

    const recent = summary.recent_sends || [];
    $("ag-recent").innerHTML = recent.length
      ? `<table><thead><tr><th>Time</th><th>List</th><th>Business</th><th>Email</th></tr></thead><tbody>` +
        recent.map((r) => `<tr><td>${esc(new Date(r.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }))}</td>
          <td><span class="pill ${r.stream === "agency" ? "warn" : "muted"}">${r.stream === "agency" ? "Agency" : "Client"}</span></td>
          <td>${esc(r.company || "")}</td><td>${esc(r.email)}</td></tr>`).join("") + "</tbody></table>"
      : '<div class="empty-state">Nothing sent yet today.</div>';
    $("agency-docker").textContent = summary.docker.message;
    $("agency-docker").style.color = summary.docker.ok ? "" : "var(--danger)";

    const s = summary.settings;
    const per = s.send_enabled ? s.per_day : 0;
    const hours = Math.max(1, summary.end_hour - summary.start_hour);
    const totalDay = summary.client_per_day + per;
    const gap = totalDay ? (hours * 60) / totalDay : 0;
    $("agency-sent").innerHTML = s.send_enabled
      ? `<span>Every day ${summary.start_hour}:00 to ${summary.end_hour}:00: <strong>${summary.client_per_day} client</strong> + <strong>${per} agency</strong> emails, alternating. About one email every ${gap.toFixed(1)} minutes (each list every ${((hours * 60) / Math.max(1, Math.max(per, summary.client_per_day))).toFixed(1)}).</span>`
      : `<span>Agency emails are <strong>not being sent</strong>. Preview a few, then turn sending on.</span>`;
    renderJob(summary.job);
  }

  function renderSettings() {
    const s = summary.settings;
    $("agency-states").innerHTML = summary.states.map((st) => `
      <label class="lf-chip" title="${esc(st.name)}"><input type="checkbox" name="agency-state" value="${st.code}" ${s.states.includes(st.code) ? "checked" : ""}><span>${st.code}</span></label>`).join("");
    updateStateCount();
    $("agency-terms").value = s.search_terms.join("\n");
    $("agency-per-night").value = s.searches_per_night;
    $("agency-enabled").checked = s.send_enabled;
    $("agency-per-day").value = s.per_day;
    $("agency-auto").checked = s.auto_approve;
    $("agency-nightly").checked = s.nightly_enabled;
  }

  function updateStateCount() {
    const n = document.querySelectorAll('input[name="agency-state"]:checked').length;
    $("agency-states-count").textContent = n ? `(${n} selected)` : "(whole country)";
  }

  function renderJob(job) {
    const busy = Boolean(job && job.running);
    $("agency-find").disabled = busy;
    $("agency-job").textContent = job && job.message ? job.message : "No search running.";
    $("agency-job").style.color = job && job.error ? "var(--danger)" : "";
    if (busy && !pollTimer) pollTimer = setInterval(poll, 5000);
    if (!busy && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  async function poll() {
    try {
      const was = summary && summary.job && summary.job.running;
      summary = await api("summary");
      renderSummary();
      if (was && !summary.job.running) loadList(true);
    } catch (error) { /* keep polling */ }
  }

  /* ── Settings ───────────────────────────────────────────────── */
  async function saveSettings(quiet = false) {
    const body = {
      states: [...document.querySelectorAll('input[name="agency-state"]:checked')].map((i) => i.value),
      search_terms: $("agency-terms").value.split("\n").map((t) => t.trim()).filter(Boolean),
      searches_per_night: Number($("agency-per-night").value),
      send_enabled: $("agency-enabled").checked,
      per_day: Number($("agency-per-day").value),
      auto_approve: $("agency-auto").checked,
      nightly_enabled: $("agency-nightly").checked,
    };
    const data = await api("settings", body);
    summary.settings = data.settings;
    summary = await api("summary");
    renderSummary();
    if (!quiet) showMessage("Settings saved.", "success");
  }

  /* ── List ───────────────────────────────────────────────────── */
  const selectable = () => ["ready", "approved", "rejected"].includes(status);

  function renderTable() {
    const check = selectable();
    document.querySelector(".lf-bulk").hidden = !check;
    $("agency-approve").hidden = status === "approved";
    $("agency-approve-next").hidden = status !== "ready";
    $("agency-reject").hidden = status === "rejected";
    $("agency-unapprove").hidden = status === "ready";
    if (!rows.length) {
      $("agency-table").innerHTML = `<div class="empty-state">${status === "ready"
        ? "No agencies waiting. Click Find agencies now to search Google Maps." : "Nothing here."}</div>`;
    } else {
      $("agency-table").innerHTML = `<table><thead><tr>${check ? "<th></th>" : ""}<th>Agency</th><th>Email</th><th>Location</th><th>Rating</th><th></th></tr></thead><tbody>` +
        rows.map((a) => `<tr>
          ${check ? `<td><input type="checkbox" name="agency" value="${a.id}" ${selected.has(a.id) ? "checked" : ""} aria-label="Select ${esc(a.name)}"></td>` : ""}
          <td><strong>${esc(a.name)}</strong><br><small class="muted">${esc(a.category || "")}${a.website ? ` · <a href="${esc(a.website)}" target="_blank" rel="noreferrer">${esc(a.domain || "site")}</a>` : ""}</small></td>
          <td>${esc(a.email || "–")}<br><small class="muted">${esc(a.status === "sent" ? `sent ${a.sent_at || ""}` : (a.status_detail || (a.email_source === "google" ? "on their Google profile" : a.email_source ? "published on their site" : "")))}</small></td>
          <td>${esc([a.city, a.state].filter(Boolean).join(", "))}</td>
          <td>${a.rating ? `${esc(a.rating)} ★ <small class="muted">(${fmt(a.reviews)})</small>` : "–"}</td>
          <td>${a.email ? `<button class="btn ghost" type="button" data-preview="${a.id}">Preview</button>` : ""}</td>
        </tr>`).join("") + "</tbody></table>";
    }
    $("agency-page").textContent = total ? `${offset + 1}–${Math.min(offset + PAGE, total)} of ${fmt(total)}` : "";
    $("agency-previous").disabled = offset === 0;
    $("agency-next").disabled = offset + PAGE >= total;
    updateSelection();
  }

  function updateSelection() {
    $("agency-selected").textContent = `${selected.size} selected`;
    ["agency-approve", "agency-reject", "agency-unapprove"].forEach((id) => { $(id).disabled = !selected.size; });
    const boxes = document.querySelectorAll('input[name="agency"]');
    $("agency-select-all").checked = boxes.length > 0 && [...boxes].every((b) => b.checked);
  }

  async function loadList(reset = false) {
    if (reset) { offset = 0; selected = new Set(); }
    const q = ($("page-search") && $("page-search").value.trim()) || "";
    try {
      const data = await api(`list?status=${status}&limit=${PAGE}&offset=${offset}&q=${encodeURIComponent(q)}`);
      rows = data.agencies;
      total = data.total;
      renderTable();
    } catch (error) {
      $("agency-table").innerHTML = `<div class="empty-state">${esc(error.message)}</div>`;
    }
  }

  async function review(action) {
    try {
      const body = action === "approve_next" ? { action, n: 150 } : { action, ids: [...selected] };
      const data = await api("review", body);
      showMessage(`Updated ${fmt(data.changed)} agenc${data.changed === 1 ? "y" : "ies"}.`, "success");
      summary = await api("summary");
      renderSummary();
      loadList(true);
    } catch (error) { showMessage(error.message, "error"); }
  }

  async function preview(id) {
    try {
      const data = await api(`preview?id=${id}`);
      $("agency-preview-meta").textContent = `To ${data.to} · Subject: ${data.subject}`;
      $("agency-preview").textContent = data.text;
      $("agency-preview").scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (error) { showMessage(error.message, "error"); }
  }

  /* ── Wiring ─────────────────────────────────────────────────── */
  function wire() {
    $("agency-states").addEventListener("change", updateStateCount);
    $("agency-states-all").addEventListener("click", () => {
      document.querySelectorAll('input[name="agency-state"]').forEach((b) => { b.checked = false; });
      updateStateCount();
    });
    $("agency-settings").addEventListener("submit", (event) => {
      event.preventDefault();
      saveSettings().catch((error) => showMessage(error.message, "error"));
    });
    ["agency-enabled", "agency-auto", "agency-nightly"].forEach((id) => $(id).addEventListener("change",
      () => saveSettings().catch((error) => showMessage(error.message, "error"))));
    $("agency-per-day").addEventListener("change", () => saveSettings().catch((error) => showMessage(error.message, "error")));
    $("agency-find").addEventListener("click", async () => {
      try {
        await saveSettings(true);
        await api("job", { job: "scrape", searches: Number($("agency-query-count").value || 16) });
        showMessage("Search started. Each batch of 8 searches takes a few minutes; you can leave this page.", "success");
        summary.job = { running: true, message: "Starting..." };
        renderJob(summary.job);
      } catch (error) { showMessage(error.message, "error"); }
    });
    $("agency-status").addEventListener("change", (event) => { status = event.target.value; loadList(true); });
    $("agency-table").addEventListener("change", (event) => {
      if (event.target.name !== "agency") return;
      const id = Number(event.target.value);
      event.target.checked ? selected.add(id) : selected.delete(id);
      updateSelection();
    });
    $("agency-table").addEventListener("click", (event) => {
      const btn = event.target.closest("[data-preview]");
      if (btn) preview(Number(btn.dataset.preview));
    });
    $("agency-select-all").addEventListener("change", (event) => {
      document.querySelectorAll('input[name="agency"]').forEach((box) => {
        box.checked = event.target.checked;
        const id = Number(box.value);
        box.checked ? selected.add(id) : selected.delete(id);
      });
      updateSelection();
    });
    $("agency-approve").addEventListener("click", () => review("approve"));
    $("agency-reject").addEventListener("click", () => review("reject"));
    $("agency-unapprove").addEventListener("click", () => review("unapprove"));
    $("agency-approve-next").addEventListener("click", () => review("approve_next"));
    $("agency-previous").addEventListener("click", () => { offset = Math.max(0, offset - PAGE); loadList(); });
    $("agency-next").addEventListener("click", () => { offset += PAGE; loadList(); });
    if ($("page-search")) {
      $("page-search").addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => loadList(true), 250);
      });
    }
  }

  async function init() {
    wire();
    setInterval(() => { if (!document.hidden) poll(); }, 60000);  // live send count
    try {
      summary = await api("summary");
      renderSettings();
      renderSummary();
      loadList(true);
    } catch (error) {
      showMessage(`Could not load the Agency Finder: ${error.message}`, "error");
    }
  }

  init();
})();
