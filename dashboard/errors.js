const checkIssuesButton = document.querySelector("#check-issues");
const copyIssuesButton = document.querySelector("#copy-issues");
const issuesList = document.querySelector("#issues-list");
const issuesStatus = document.querySelector("#issues-status");
const deploysList = document.querySelector("#deploys-list");

let recipients = [];
let githubStatus = {};
let lastIssuesByClient = {};
let checkedAt = null;

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

async function copyToClipboard(text, button) {
  const originalLabel = button.textContent;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const scratch = document.createElement("textarea");
      scratch.value = text;
      scratch.style.position = "fixed";
      scratch.style.opacity = "0";
      document.body.appendChild(scratch);
      scratch.select();
      document.execCommand("copy");
      scratch.remove();
    }
    button.textContent = "Copied!";
  } catch (error) {
    button.textContent = "Couldn't copy";
  } finally {
    setTimeout(() => { button.textContent = originalLabel; }, 1500);
  }
}

function githubIssuesFor(clientName) {
  const status = githubStatus[clientName];
  if (!status) return [];

  const issues = [];
  if (status.deploy_color === "#ef4444") {
    issues.push({ category: "Deployment", message: status.deploy_label, detail: status.repo, color: status.deploy_color });
  }
  if (status.dependabot) {
    const counts = status.dependabot.counts;
    const critHigh = counts.critical + counts.high;
    if (critHigh > 0) {
      issues.push({
        category: "Dependabot",
        message: `${critHigh} high/critical open alert${critHigh === 1 ? "" : "s"}`,
        detail: status.repo,
        color: "#ef4444",
      });
    }
  }
  return issues;
}

function renderIssuesList(siteIssues) {
  const clientNames = [...new Set(recipients.map((r) => r.client_name))];
  lastIssuesByClient = {};

  const sections = clientNames.map((name) => {
    const issues = [...(siteIssues[name] || []), ...githubIssuesFor(name)];
    if (!issues.length) return "";
    lastIssuesByClient[name] = issues;

    const rows = issues.map((issue) => `
      <div class="issue-row">
        <span class="dot" style="--dot-color:${escapeHtml(issue.color || "")}"></span>
        <span class="issue-category">${escapeHtml(issue.category)}</span>
        <span class="issue-message">${escapeHtml(issue.message)}${issue.detail ? ` <small>(${escapeHtml(issue.detail)})</small>` : ""}</span>
      </div>
    `).join("");

    return `
      <div class="issue-client" data-searchable>
        <h4>${escapeHtml(name)}</h4>
        ${rows}
      </div>
    `;
  }).join("");

  issuesList.innerHTML = sections || (checkedAt
    ? '<div class="empty-state">No errors found across your client sites.</div>'
    : '<div class="empty-state">Not checked yet. Press “Check for errors” in the top bar.</div>');
  copyIssuesButton.hidden = Object.keys(lastIssuesByClient).length === 0;
  Motion.rows(issuesList);
  document.dispatchEvent(new Event("listrendered"));
}

function issuesAsText() {
  return Object.entries(lastIssuesByClient).map(([name, issues]) => {
    const lines = issues.map((issue) =>
      `  [${issue.category}] ${issue.message}${issue.detail ? ` (${issue.detail})` : ""}`
    );
    return [name, ...lines].join("\n");
  }).join("\n\n");
}

function buildStatusBadges(status) {
  if (!status || !status.repo) {
    return "";
  }

  const parts = [];
  if (status.deploy_label) {
    parts.push(
      `<span class="status-dot" style="--dot-color:${escapeHtml(status.deploy_color || "")}" title="${escapeHtml(status.deploy_label)}"></span>` +
      `<span class="pill">${escapeHtml(status.deploy_label)}</span>`
    );
  } else {
    parts.push('<span class="pill muted">No deploy data</span>');
  }

  if (status.dependabot) {
    const counts = status.dependabot.counts;
    const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
    const critHigh = counts.critical + counts.high;
    const tone = total === 0 ? "ok" : critHigh > 0 ? "danger" : "warn";
    const label = total === 0 ? "No open alerts" : `${total} open alert${total === 1 ? "" : "s"}`;
    if (total === 0) {
      parts.push(`<span class="pill ${tone}" title="Dependabot alerts">${label}</span>`);
    } else {
      parts.push(
        `<button type="button" class="pill pill-button ${tone}" data-role="toggle-alerts" aria-expanded="false">${label} ▾</button>`
      );
    }
  } else {
    parts.push('<span class="pill muted">Dependabot off</span>');
  }

  return parts.join("");
}

function alertsAsText(clientName, status) {
  const alerts = status.dependabot.alerts;
  const header = `${clientName} — Dependabot alerts (${status.repo})`;
  const lines = alerts.map((a) =>
    `[${a.severity.toUpperCase()}] ${a.package}${a.ecosystem ? ` (${a.ecosystem})` : ""}: ${a.summary}${a.url ? ` — ${a.url}` : ""}`
  );
  return [header, ...lines].join("\n");
}

function buildAlertsPanel(status) {
  const alerts = status && status.dependabot ? status.dependabot.alerts : [];
  if (!alerts || !alerts.length) return "";

  const rows = alerts.map((alert) => `
    <div class="alert-row severity-${escapeHtml(alert.severity)}">
      <span class="alert-severity">${escapeHtml(alert.severity)}</span>
      <span class="alert-package">${escapeHtml(alert.package)}${alert.ecosystem ? ` <small>(${escapeHtml(alert.ecosystem)})</small>` : ""}</span>
      <span class="alert-summary">${escapeHtml(alert.summary)}</span>
      ${alert.url ? `<a class="alert-link" href="${escapeHtml(alert.url)}" target="_blank" rel="noreferrer">View</a>` : ""}
    </div>
  `).join("");

  return `
    <div class="alerts-panel-header">
      <span>${alerts.length} open alert${alerts.length === 1 ? "" : "s"}</span>
      <button type="button" class="btn ghost" data-role="copy-alerts">Copy list</button>
    </div>
    ${rows}
  `;
}

function renderDeploysList() {
  const clientNames = [...new Set(recipients.map((r) => r.client_name))];

  if (!clientNames.length) {
    deploysList.innerHTML = '<div class="empty-state">No client contacts are configured yet.</div>';
    return;
  }

  deploysList.innerHTML = clientNames.map((name) => `
    <div class="issue-client" data-searchable>
      <h4>${escapeHtml(name)}</h4>
      <div class="site-status" data-role="site-status"></div>
      <div class="alerts-panel" data-role="alerts-panel" hidden></div>
    </div>
  `).join("");

  deploysList.querySelectorAll(".issue-client").forEach((card) => {
    const clientName = card.querySelector("h4").textContent;
    const status = githubStatus[clientName];
    const badgeTarget = card.querySelector('[data-role="site-status"]');
    const panelTarget = card.querySelector('[data-role="alerts-panel"]');

    badgeTarget.innerHTML = buildStatusBadges(status) || '<span class="pill muted">Not connected to GitHub</span>';
    panelTarget.innerHTML = buildAlertsPanel(status);
    panelTarget.hidden = true;

    const copyButton = panelTarget.querySelector('[data-role="copy-alerts"]');
    if (copyButton) {
      copyButton.onclick = () => copyToClipboard(alertsAsText(clientName, status), copyButton);
    }

    const toggle = badgeTarget.querySelector('[data-role="toggle-alerts"]');
    if (toggle) {
      toggle.onclick = () => {
        panelTarget.hidden = !panelTarget.hidden;
        toggle.setAttribute("aria-expanded", String(!panelTarget.hidden));
      };
    }
  });
}

function relativeTime(isoString) {
  if (!isoString) return null;
  const seconds = Math.round((Date.now() - new Date(isoString).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function setStatusLine() {
  issuesStatus.textContent = checkedAt
    ? `Last checked ${relativeTime(checkedAt)}. Click "Check for errors" to run a fresh check.`
    : "Not checked yet in this session. Press “Check for errors” to run SSL, uptime, and PageSpeed checks.";
}

async function loadSharedContext() {
  const [recipientsRes, githubRes] = await Promise.all([
    fetch("/api/recipients", { cache: "no-store" }),
    fetch("/api/github-status", { cache: "no-store" }),
  ]);
  if (recipientsRes.ok) recipients = (await recipientsRes.json()).recipients || [];
  if (githubRes.ok) githubStatus = (await githubRes.json()).clients || {};
}

async function loadCachedIssues() {
  // Instant — only ever reads whatever was last checked, never blocks on a live run.
  try {
    await loadSharedContext();
    renderDeploysList();
    const response = await fetch("/api/site-issues", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load site errors");
    const data = await response.json();
    checkedAt = data.checked_at;
    renderIssuesList(data.clients || {});
    setStatusLine();
  } catch (error) {
    issuesStatus.textContent = "Could not load site errors.";
  }
}

async function checkSiteIssues() {
  checkIssuesButton.disabled = true;
  checkIssuesButton.querySelector("span").textContent = "Checking…";
  issuesStatus.textContent = "Running SSL, uptime, and PageSpeed checks for every client site. Usually under a minute.";

  try {
    if (!recipients.length) await loadSharedContext();

    const response = await fetch("/api/site-issues/check", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not check site errors");

    checkedAt = data.checked_at;
    renderIssuesList(data.clients || {});
    setStatusLine();
  } catch (error) {
    issuesStatus.textContent = error.message || "Could not check site errors. Try again.";
  } finally {
    checkIssuesButton.disabled = false;
    checkIssuesButton.querySelector("span").textContent = "Check for errors";
  }
}

checkIssuesButton.addEventListener("click", checkSiteIssues);
copyIssuesButton.addEventListener("click", () => copyToClipboard(issuesAsText(), copyIssuesButton));

loadCachedIssues();
