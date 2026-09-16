const warningBox = document.querySelector("#outreach-warning");
const refreshButton = document.querySelector("#refresh-outreach");
const statToday = document.querySelector("#stat-today");
const statTodayTarget = document.querySelector("#stat-today-target");
const statTodayNote = document.querySelector("#stat-today-note");
const statJob = document.querySelector("#stat-job");
const statJobLabel = document.querySelector("#stat-job-label");
const statJobNote = document.querySelector("#stat-job-note");
const statLifetime = document.querySelector("#stat-lifetime");
const statLifetimeTrend = document.querySelector("#stat-lifetime-trend");
const statLifetimeNote = document.querySelector("#stat-lifetime-note");
const statLifetimeBlocks = document.querySelector("#stat-lifetime-blocks");
const statBlocked = document.querySelector("#stat-blocked");
const statBlockedNote = document.querySelector("#stat-blocked-note");
const scheduleState = document.querySelector("#schedule-state");
const sparkline = document.querySelector("#sparkline");
const activityChart = document.querySelector("#activity-chart");
const seriesButtons = [...document.querySelectorAll(".segmented-item[data-series]")];
const blocksList = document.querySelector("#blocks-list");
const blocksDonut = document.querySelector("#blocks-donut");
const blocksLegend = document.querySelector("#blocks-legend");
const blocksFooterLine = document.querySelector("#blocks-footer-line");

const chart = { runDays: [], series: "sent" };

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value == null ? "" : String(value);
  return element.innerHTML;
}

function showWarning(text) { warningBox.textContent = text; warningBox.hidden = false; }
function hideWarning() { warningBox.hidden = true; }

function formatHour12(hour) {
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h} ${hour < 12 ? "AM" : "PM"}`;
}

function formatShortDate(isoDate) {
  const date = new Date(`${isoDate}T00:00:00`);
  return Number.isNaN(date.getTime()) ? isoDate : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function renderToday(data) {
  const { today, config } = data;
  Motion.countUp(statToday, today.sent);
  statTodayTarget.textContent = `/ ${config.daily_target}`;
  statTodayNote.className = today.remaining === 0 ? "kpi-delta up" : "kpi-delta";
  statTodayNote.textContent = `${today.remaining} remaining · ${String(config.start_hour).padStart(2, "0")}:00–${String(config.end_hour).padStart(2, "0")}:00 window`;
  statJobLabel.textContent = `Weekday ${formatHour12(config.start_hour)} job`;
  statJobNote.textContent = `Weekdays only · min ${config.min_gap_days} days between repeats`;
}

/* ── Bar chart with Sent / By bot / Errors toggle ───────────────── */
function seriesValue(day, series) {
  if (series === "by_bot") return day.by_bot || 0;
  if (series === "errors") return day.errors || 0;
  return day.sent;
}

function drawBars(animateBars) {
  const points = [...chart.runDays].reverse();
  if (!points.length) { activityChart.innerHTML = ""; return; }

  const rect = activityChart.getBoundingClientRect();
  const W = Math.max(rect.width, 320);
  const H = Math.max(rect.height, 180);
  const padL = 32, padR = 8, padT = 10, padB = 26;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  activityChart.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const values = points.map((p) => seriesValue(p, chart.series));
  const max = Math.max(...values, 4);
  const slot = plotW / points.length;
  const barW = Math.min(slot * 0.6, 40);
  const isError = chart.series === "errors";

  const gridlines = [0, 0.25, 0.5, 0.75, 1].map((fraction) => {
    const y = padT + plotH - fraction * plotH;
    return `<line x1="${padL}" x2="${W - padR}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" class="chart-grid"></line>
            <text x="${padL - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="chart-axis-label">${Math.round(max * fraction)}</text>`;
  }).join("");

  const existing = activityChart.querySelectorAll("rect[data-y]").length === points.length;
  const bars = points.map((p, i) => {
    const value = values[i];
    const h = value > 0 ? Math.max((value / max) * plotH, 2) : 0;
    const y = padT + plotH - h;
    const x = padL + i * slot + (slot - barW) / 2;
    const label = formatShortDate(p.date);
    return `
      <g class="chart-bar-group">
        <title>${escapeHtml(`${label}: ${p.sent} sent, ${p.by_bot || 0} by bot${p.errors ? `, ${p.errors} error${p.errors === 1 ? "" : "s"}` : ""}`)}</title>
        <rect x="${x.toFixed(1)}" y="${(padT + plotH).toFixed(1)}" width="${barW.toFixed(1)}" height="0" rx="3" class="chart-bar${isError ? " error" : ""}" data-y="${y.toFixed(1)}" data-h="${h.toFixed(1)}"></rect>
        <text x="${(x + barW / 2).toFixed(1)}" y="${H - 8}" text-anchor="middle" class="chart-axis-label">${escapeHtml(label)}</text>
      </g>`;
  }).join("");

  // On a series switch we keep the current bar heights as the starting point
  // so the bars tween between the two datasets instead of re-growing from 0.
  const previous = existing ? [...activityChart.querySelectorAll("rect[data-y]")].map((r) => ({ y: r.getAttribute("y"), h: r.getAttribute("height") })) : null;
  activityChart.innerHTML = gridlines + bars;
  if (previous) {
    activityChart.querySelectorAll("rect[data-y]").forEach((r, i) => { r.setAttribute("y", previous[i].y); r.setAttribute("height", previous[i].h); });
  }
  Motion.growBars(activityChart, { stagger: previous ? 0.015 : 0.04, duration: previous ? 0.6 : 0.9 });
}

function setSeries(series) {
  chart.series = series;
  seriesButtons.forEach((button) => {
    const active = button.dataset.series === series;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  drawBars(true);
}
seriesButtons.forEach((button) => button.addEventListener("click", () => setSeries(button.dataset.series)));

function renderSchedule(launchd) {
  if (!launchd.loaded) {
    statJob.textContent = "Off";
    scheduleState.className = "pill danger";
    scheduleState.textContent = "Not registered with launchd";
    return;
  }
  if (!launchd.program_exists) {
    statJob.textContent = "Broken";
    scheduleState.className = "pill danger";
    scheduleState.textContent = `Missing path: ${launchd.program_path || "unknown"}`;
    return;
  }
  const healthy = launchd.last_exit_status === 0 || launchd.last_exit_status === null;
  statJob.textContent = "Scheduled";
  scheduleState.className = healthy ? "pill ok" : "pill warn";
  scheduleState.textContent = healthy ? "Pointing at the current bot folder" : `Last run exited with status ${launchd.last_exit_status}`;
}

function formatBlockTime(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString.slice(0, 16).replace("T", " ");
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

const DONUT_COLORS = { bounce: "var(--chart-1)", seed: "var(--chart-4)", optout: "var(--chart-2)", "opt-out": "var(--chart-2)", manual: "var(--chart-3)" };
function donutColorFor(source) { return DONUT_COLORS[source.toLowerCase()] || "var(--chart-5)"; }

function renderDonut(blocksBySource) {
  const total = blocksBySource.reduce((sum, b) => sum + b.count, 0);
  const segments = blocksBySource.map((b) => ({ value: b.count, color: donutColorFor(b.source), label: b.source }));
  Motion.radial(blocksDonut, segments, { label: "Blocked", delay: 0.3 });
  blocksLegend.innerHTML = segments.map((segment, index) => `
      <div class="legend-row" data-index="${index}">
        <span class="dot" style="--dot-color:${segment.color}"></span>
        <span class="legend-label" style="text-transform:capitalize">${escapeHtml(segment.label)}</span>
        <span class="legend-count">${segment.value}</span>
      </div>`).join("");
  const arcs = blocksDonut.querySelector(".radial-arcs");
  blocksLegend.querySelectorAll(".legend-row").forEach((row) => {
    const arc = blocksDonut.querySelector(`path[data-index="${row.dataset.index}"]`);
    row.addEventListener("mouseenter", () => { if (arc) { arc.classList.add("is-hot"); arcs.classList.add("has-hot"); } });
    row.addEventListener("mouseleave", () => { if (arc) { arc.classList.remove("is-hot"); arcs.classList.remove("has-hot"); } });
  });
  blocksFooterLine.className = total ? "card-footer-line down" : "card-footer-line";
  blocksFooterLine.innerHTML = total
    ? `<span>${total} address${total === 1 ? "" : "es"} on the do-not-send list</span><svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><path d="m4.9 4.9 14.2 14.2"></path></svg>`
    : "<span>No blocks yet</span>";
}

const blocksToggle = document.querySelector("#blocks-toggle");
const blocksDropdown = document.querySelector("#blocks-dropdown");
const blocksToggleHint = document.querySelector("#blocks-toggle-hint");

function setBlocksOpen(open) {
  blocksToggle.setAttribute("aria-expanded", String(open));
  blocksToggleHint.textContent = open ? "Click to hide" : "Click to see every address";
  if (!open) {
    if (!Motion.animate) { blocksDropdown.hidden = true; return; }
    gsap.to(blocksDropdown, { height: 0, opacity: 0, duration: 0.3, ease: "power2.inOut", onComplete: () => { blocksDropdown.hidden = true; gsap.set(blocksDropdown, { clearProps: "height,opacity" }); } });
    return;
  }
  blocksDropdown.hidden = false;
  if (!Motion.animate) return;
  gsap.from(blocksDropdown, { height: 0, opacity: 0, duration: 0.4, ease: "power3.out", clearProps: "height,opacity" });
  Motion.rows(blocksList);
}
blocksToggle.addEventListener("click", () => setBlocksOpen(blocksToggle.getAttribute("aria-expanded") !== "true"));

function renderBlocks(blocksBySource, allBlocks) {
  renderDonut(blocksBySource);
  const total = blocksBySource.reduce((sum, b) => sum + b.count, 0);
  Motion.countUp(statBlocked, total);
  statBlockedNote.textContent = total ? blocksBySource.map((b) => `${b.count} ${b.source}`).join(" · ") : "Nobody blocked yet";
  statLifetimeBlocks.className = total ? "pill warn" : "pill ok";
  statLifetimeBlocks.textContent = total ? `${total} on the do-not-send list` : "No blocks yet";
  blocksToggle.disabled = !allBlocks.length;

  blocksList.innerHTML = allBlocks.length
    ? `<div class="table-row table-head blocks-row"><span>When</span><span>Address</span><span class="right">Reason</span></div>
       ${allBlocks.map((block) => `
        <div class="table-row blocks-row" data-searchable>
          <span class="muted">${escapeHtml(formatBlockTime(block.added_at))}</span>
          <span class="cell-stack"><span class="ellipsis">${escapeHtml(block.email)}</span><small style="text-transform:capitalize">${escapeHtml(block.source || "")}</small></span>
          <span class="right"><span class="pill">${escapeHtml(block.reason || "")}</span></span>
        </div>`).join("")}`
    : '<div class="empty-state">No blocks recorded.</div>';
  document.dispatchEvent(new Event("listrendered"));
}

async function loadOutreachStatus() {
  refreshButton.disabled = true;
  refreshButton.textContent = "Refreshing…";
  try {
    const response = await fetch("/api/outreach-status", { cache: "no-store" });
    const data = await response.json();

    if (!data.available) {
      hideWarning();
      statTodayNote.textContent = "Bot status unavailable";
      statJob.textContent = "–";
      statJobNote.textContent = "";
      scheduleState.className = "pill danger";
      scheduleState.textContent = data.error || "Could not read the outreach bot's status";
      sparkline.innerHTML = "";
      activityChart.innerHTML = "";
      blocksList.innerHTML = "";
      return;
    }

    if (!data.launchd.loaded || !data.launchd.program_exists) {
      showWarning("The weekday auto-send schedule needs attention. See the job tile below.");
    } else {
      hideWarning();
    }

    renderToday(data);
    renderSchedule(data.launchd);
    chart.runDays = data.run_days;
    drawBars(true);
    Motion.sparkline(sparkline, [...data.run_days].reverse().map((d) => d.sent), { delay: 0.3 });
    renderBlocks(data.blocks_by_source, data.blocks || data.recent_blocks);
    Motion.countUp(statLifetime, data.lifetime.sends);
    statLifetimeNote.textContent = `To ${data.lifetime.people} people`;

    const recentSent = data.run_days.reduce((sum, d) => sum + d.sent, 0);
    if (recentSent > 0) {
      statLifetimeTrend.className = "kpi-delta up";
      statLifetimeTrend.innerHTML = `<svg class="icon" viewBox="0 0 24 24"><path d="M23 6 13.5 15.5 8.5 10.5 1 18"></path><path d="M17 6h6v6"></path></svg> +${recentSent} over last ${data.run_days.length} run days`;
    } else {
      statLifetimeTrend.className = "kpi-delta";
      statLifetimeTrend.textContent = "No recent sends";
    }
  } catch (error) {
    showWarning("Could not reach the dashboard server for outreach status.");
  } finally {
    refreshButton.disabled = false;
    refreshButton.textContent = "Refresh";
  }
}

let resizeTimer = null;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { drawBars(false); drawEmailActivity(); }, 120); });
refreshButton.addEventListener("click", loadOutreachStatus);
loadOutreachStatus();
setInterval(loadOutreachStatus, 30000);

/* ── Everything that went out today (reports + outreach) ───────── */
const emailChart = document.querySelector("#email-activity-chart");
const emailTooltip = document.querySelector("#email-activity-tooltip");
const emailSeriesButtons = [...document.querySelectorAll(".segmented-item[data-email-series]")];
const todayDonut = document.querySelector("#today-donut");
const todayLegend = document.querySelector("#today-legend");
const todayFooterLine = document.querySelector("#today-footer-line");
const todayDonutDesc = document.querySelector("#today-donut-desc");
const sentTable = document.querySelector("#sent-table");
const sentDatePill = document.querySelector("#sent-date-pill");
const refreshSentButton = document.querySelector("#refresh-sent");
const CHART_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

const emailActivity = { days: [], series: "all", values: [], hoverIndex: -1 };

function emailSeriesValue(day, series) {
  if (series === "reports") return day.reports;
  if (series === "outreach") return day.outreach;
  return day.reports + day.outreach;
}

function niceMax(value) {
  if (value <= 4) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = magnitude / 2;
  return Math.ceil(value / step) * step;
}

function drawEmailActivity() {
  const days = emailActivity.days;
  if (!emailChart || !days.length) { if (emailChart) emailChart.innerHTML = ""; return; }

  const rect = emailChart.getBoundingClientRect();
  const W = Math.max(rect.width, 320);
  const H = Math.max(rect.height, 200);
  const padL = 36, padR = 12, padT = 12, padB = 26;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  emailChart.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const target = days.map((d) => emailSeriesValue(d, emailActivity.series));
  const max = niceMax(Math.max(...target, ...emailActivity.values, 1));
  const stepX = plotW / (days.length - 1);
  const points = emailActivity.values.map((v, i) => [padL + i * stepX, padT + plotH - (v / max) * plotH]);
  const line = Motion.smoothPath(points);
  const fill = `${line} L${(padL + plotW).toFixed(1)},${(padT + plotH).toFixed(1)} L${padL},${(padT + plotH).toFixed(1)} Z`;

  const ticks = 4;
  const gridlines = Array.from({ length: ticks + 1 }, (_, i) => {
    const y = padT + plotH - (i / ticks) * plotH;
    return `<line x1="${padL}" x2="${padL + plotW}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" class="chart-grid"></line>
            <text x="${padL - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="chart-axis-label">${Math.round((i / ticks) * max)}</text>`;
  }).join("");

  const labelEvery = days.length > 10 ? 2 : 1;
  const labels = days.map((d, i) => {
    const last = i === days.length - 1;
    if (i % labelEvery !== 0 && !last) return "";
    if (last && days.length > 10 && (i - 1) % labelEvery === 0) return "";
    const anchor = i === 0 ? "start" : last ? "end" : "middle";
    return `<text x="${(padL + i * stepX).toFixed(1)}" y="${H - 8}" text-anchor="${anchor}" class="chart-axis-label">${escapeHtml(formatShortDate(d.date))}</text>`;
  }).join("");

  const hover = emailActivity.hoverIndex >= 0 ? (() => {
    const [x, y] = points[emailActivity.hoverIndex];
    return `<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${padT}" y2="${padT + plotH}" class="hover-line"></line>
            <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" class="area-dot"></circle>`;
  })() : "";

  emailChart.innerHTML = `${Motion.gradientDefs("area-grad", "var(--chart-2)")}${gridlines}
    <path class="area-fill" d="${fill}"></path>
    <path class="area-line" d="${line}"></path>
    ${hover}${labels}`;
}

function setEmailSeries(series, animateChange = true) {
  emailActivity.series = series;
  emailSeriesButtons.forEach((button) => {
    const active = button.dataset.emailSeries === series;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const target = emailActivity.days.map((d) => emailSeriesValue(d, series));
  if (emailActivity.values.length !== target.length) emailActivity.values = target.map(() => 0);
  if (animateChange) Motion.tweenArray(emailActivity.values, target, drawEmailActivity);
  else { emailActivity.values = target; drawEmailActivity(); }
}

function emailPointer(event) {
  if (!emailActivity.days.length) return;
  const rect = emailChart.getBoundingClientRect();
  const padL = 36, padR = 12;
  const stepX = (rect.width - padL - padR) / (emailActivity.days.length - 1);
  const x = event.clientX - rect.left;
  const index = Math.max(0, Math.min(emailActivity.days.length - 1, Math.round((x - padL) / stepX)));
  if (index === emailActivity.hoverIndex) return;
  emailActivity.hoverIndex = index;
  drawEmailActivity();
  const day = emailActivity.days[index];
  emailTooltip.innerHTML = `<strong>${escapeHtml(formatShortDate(day.date))}</strong>
    <span>Reports <b>${day.reports}</b></span><span>Outreach <b>${day.outreach}</b></span>${day.failed ? `<span>Failed <b>${day.failed}</b></span>` : ""}`;
  emailTooltip.hidden = false;
  emailTooltip.style.left = `${padL + index * stepX + 20}px`;
  emailTooltip.style.top = `${event.clientY - rect.top + 12}px`;
}

if (emailChart) {
  emailChart.addEventListener("pointermove", emailPointer);
  emailChart.addEventListener("pointerleave", () => {
    emailActivity.hoverIndex = -1;
    emailTooltip.hidden = true;
    drawEmailActivity();
  });
}
emailSeriesButtons.forEach((button) => button.addEventListener("click", () => setEmailSeries(button.dataset.emailSeries)));

async function loadEmailActivity() {
  try {
    const response = await fetch("/api/send-activity?days=14", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load activity");
    const data = await response.json();
    emailActivity.days = data.days || [];
    setEmailSeries(emailActivity.series, true);
  } catch (error) {
    if (emailChart) emailChart.innerHTML = "";
  }
}

function formatClock(isoString) {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return (isoString || "").slice(11, 16);
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function initials(name) {
  return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0].toUpperCase()).join("") || "?";
}

const SENT_PAGE = 40;
let showAllSent = false;

function renderSentTable(sends) {
  if (!sends.length) {
    sentTable.innerHTML = '<div class="empty-state">Nothing sent yet today. Reports you send and outreach the bot sends will show up here until midnight.</div>';
    document.dispatchEvent(new Event("listrendered"));
    return;
  }
  const visible = showAllSent ? sends : sends.slice(0, SENT_PAGE);
  const head = `
    <div class="table-row table-head sent-row">
      <span>Time</span><span>Recipient</span><span>Client / company</span><span>Type</span><span class="right">Status</span>
    </div>`;
  const rows = visible.map((send) => {
    const failed = send.status === "failed";
    const typePill = send.kind === "report" ? '<span class="pill ink">Report</span>' : '<span class="pill">Outreach</span>';
    const statusPill = failed
      ? `<span class="pill solid-danger" title="${escapeHtml(send.error || "")}">Failed</span>`
      : '<span class="pill solid-ok">Sent</span>';
    return `
      <div class="table-row sent-row" data-searchable>
        <span class="muted">${escapeHtml(formatClock(send.sent_at))}</span>
        <span class="row-with-avatar">
          <span class="row-avatar" aria-hidden="true">${escapeHtml(initials(send.to_name))}</span>
          <span class="cell-stack"><span class="ellipsis">${escapeHtml(send.to_name)}</span><small>${escapeHtml(send.to_email)}</small></span>
        </span>
        <span class="cell-stack"><span class="ellipsis">${escapeHtml(send.client || "—")}</span><small>${escapeHtml(send.subject || "")}</small></span>
        <span>${typePill}</span>
        <span class="right">${statusPill}</span>
      </div>`;
  }).join("");
  const foot = sends.length > SENT_PAGE
    ? `<div class="table-foot"><button class="btn ghost" type="button" id="sent-toggle">${showAllSent ? "Show fewer" : `Show all ${sends.length}`}</button></div>`
    : "";
  sentTable.innerHTML = head + rows + foot;
  const toggle = sentTable.querySelector("#sent-toggle");
  if (toggle) toggle.addEventListener("click", () => { showAllSent = !showAllSent; renderSentTable(sends); });
  Motion.rows(sentTable);
  document.dispatchEvent(new Event("listrendered"));
}

function attachLegendHover(legend, svg) {
  const arcs = svg.querySelector(".radial-arcs");
  legend.querySelectorAll(".legend-row").forEach((row) => {
    const arc = svg.querySelector(`path[data-index="${row.dataset.index}"]`);
    row.addEventListener("mouseenter", () => { if (arc) { arc.classList.add("is-hot"); arcs.classList.add("has-hot"); } });
    row.addEventListener("mouseleave", () => { if (arc) { arc.classList.remove("is-hot"); arcs.classList.remove("has-hot"); } });
  });
}

function renderTodayDonut(byClient, counts) {
  const segments = byClient.map((entry, index) => ({ label: entry.label, value: entry.count, color: CHART_COLORS[index % CHART_COLORS.length] }));
  Motion.radial(todayDonut, segments, { label: "Sent today", delay: 0.3 });
  todayDonutDesc.textContent = counts.total ? `${byClient.length} recipient group${byClient.length === 1 ? "" : "s"} today` : "Who received email today";
  todayLegend.innerHTML = segments.map((segment, index) => `
      <div class="legend-row" data-index="${index}">
        <span class="dot" style="--dot-color:${segment.color}"></span>
        <span class="legend-label">${escapeHtml(segment.label)}</span>
        <span class="legend-count">${segment.value}</span>
      </div>`).join("");
  attachLegendHover(todayLegend, todayDonut);

  const trend = '<svg class="icon" viewBox="0 0 24 24"><path d="M23 6 13.5 15.5 8.5 10.5 1 18"></path><path d="M17 6h6v6"></path></svg>';
  if (counts.total) {
    todayFooterLine.className = "card-footer-line up";
    todayFooterLine.innerHTML = `<span>${counts.reports} report${counts.reports === 1 ? "" : "s"} and ${counts.outreach} outreach sent today</span>${trend}`;
  } else {
    todayFooterLine.className = "card-footer-line";
    todayFooterLine.innerHTML = "<span>Nothing sent yet today</span>";
  }
}

async function loadToday() {
  refreshSentButton.disabled = true;
  try {
    const response = await fetch("/api/sent-today", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load today's sends");
    const data = await response.json();
    sentDatePill.textContent = new Date(`${data.date}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    renderTodayDonut(data.by_client, data.counts);
    renderSentTable(data.sends);
  } catch (error) {
    sentTable.innerHTML = '<div class="empty-state">Could not load today\'s sends.</div>';
  } finally {
    refreshSentButton.disabled = false;
  }
}

refreshSentButton.addEventListener("click", () => { loadToday(); loadEmailActivity(); });
loadToday();
loadEmailActivity();
setInterval(loadToday, 60000);
