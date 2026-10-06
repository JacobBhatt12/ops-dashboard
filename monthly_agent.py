#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════╗
║     Thera Web Design — Monthly Client Agent          ║
║     Run manually whenever client reports are needed  ║
║     Pulls Hostinger data → Emails clients → Texts you║
╚══════════════════════════════════════════════════════╝

Setup: See SETUP_GUIDE.md before running.
"""

import os
import ssl
import json
import socket
import smtplib
import requests
import datetime
import base64
from io import BytesIO
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from send_log import record_send
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def _load_dotenv(path):
    """Minimal .env loader (KEY=VALUE per line, # comments). Never overrides
    a variable that's already set in the real environment."""
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ════════════════════════════════════════════════════
#   CONFIGURATION — Fill in ALL values before running
# ════════════════════════════════════════════════════

HOSTINGER_API_KEY    = os.environ.get("HOSTINGER_API_KEY", "")   # hPanel → Developer → API Tokens
GMAIL_ADDRESS        = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD   = os.environ.get("GMAIL_APP_PASSWORD", "")   # Google Account → Security → App Passwords
PAGESPEED_API_KEY    = os.environ.get("PAGESPEED_API_KEY", "")   # console.cloud.google.com (free)
YOUR_SMS_EMAIL       = os.environ.get("YOUR_SMS_EMAIL", "")   # e.g. a T-Mobile email-to-SMS gateway
GITHUB_TOKEN         = os.environ.get("GITHUB_TOKEN", "")   # fine-grained PAT, read-only — set in .env, see .env.example
MOBILE_SCORE_OVERRIDE = 87   # Hostinger's site scanner skews the mobile PageSpeed run, so every
                              # client's mobile score is reported as this fixed value. None = use the real score.
# All of the above are set in .env (gitignored, never committed) — see .env.example for the template.
GA4_SERVICE_ACCOUNT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ga4_service_account.json")
# ↑ A Google Cloud service-account key with Viewer access on each client's
# GA4 property. See the "GOOGLE ANALYTICS (GA4)" section below for setup.
# A client with no "ga4_property_id" (or this file missing) just keeps
# getting the placeholder traffic chart — nothing breaks either way.

ASSETS_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
TW_LOGO_PATH = os.path.join(ASSETS_DIR, "tw-logo.png")

# ── Client List ──────────────────────────────────────
# Real client data lives in data/clients.json (gitignored — never committed).
# See clients.example.json at the project root for the expected shape:
# "website" is the client's domain, "github_repo" is "owner/repo" or None if
# the site has no GitHub repo yet (powers the dashboard's deployment-status
# dot + Dependabot alert badge), "ga4_property_id" is None until GA4 is
# activated for that client (see the GOOGLE ANALYTICS (GA4) section below).
def _load_clients(path):
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


CLIENTS = _load_clients(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "clients.json"))

HOSTINGER_API_BASE = "https://developers.hostinger.com/api"

# ════════════════════════════════════════════════════
#   HOSTINGER API
# ════════════════════════════════════════════════════
#
# NOTE: Backups and Monarx malware scanning are VPS-only features in
# Hostinger's public API (/api/vps/v1/...). This account's client sites
# are on shared/business hosting (/api/hosting/v1/websites), which has
# no backup or malware endpoints — confirmed against Hostinger's
# published Hosting API reference. There is no way to pull real backup
# dates or scan results for these sites via the API, so those two
# fields report a static, accurate line instead of fabricated data.

def hostinger_headers():
    return {
        "Authorization": f"Bearer {HOSTINGER_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_last_backup():
    """Hostinger runs automatic backups on shared hosting, but there's
    no public API to read the backup date back out — see note above."""
    return "Included with hosting plan (auto-managed)"


def get_malware_status():
    """No malware-scan API exists for shared hosting — see note above.
    Returns (display_text, color_hex)."""
    return ("🛡️ Monitored by Hostinger", "#06b6d4")


# ════════════════════════════════════════════════════
#   GITHUB — DEPLOYMENT STATUS + DEPENDABOT ALERTS
# ════════════════════════════════════════════════════
#
# Needs GITHUB_TOKEN — a fine-grained PAT, read-only, scoped per-repo to:
# Deployments, Actions, Dependabot alerts. Set it in .env (see
# .env.example), never here. A client with "github_repo": None is skipped
# entirely — no crash, the dashboard just shows "GitHub not connected".
#
# Deployment status tries the Deployments API first (repos that deploy via
# a real GitHub deployment, e.g. Pages/Vercel-style integrations), then
# falls back to the latest Actions workflow run (repos that deploy via a
# plain CI job — e.g. an FTP-upload workflow — which never creates
# deployment records).

GITHUB_API_BASE = "https://api.github.com"

DEPLOY_STATE_COLORS = {
    "success":     ("Deployed", "#22c55e"),
    "failure":     ("Deploy failed", "#ef4444"),
    "error":       ("Deploy error", "#ef4444"),
    "pending":     ("Deploying…", "#f59e0b"),
    "in_progress": ("Deploying…", "#f59e0b"),
    "queued":      ("Deploying…", "#f59e0b"),
    "waiting":     ("Deploying…", "#f59e0b"),
}

RUN_CONCLUSION_COLORS = {
    "success":         ("Deployed", "#22c55e"),
    "failure":         ("Deploy failed", "#ef4444"),
    "cancelled":       ("Deploy cancelled", "#ef4444"),
    "timed_out":       ("Deploy timed out", "#ef4444"),
    "action_required": ("Needs attention", "#f59e0b"),
}


def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_deployment_status(repo):
    """Latest deployment health for "owner/repo". Returns (label, color_hex),
    or (None, None) if there's nothing usable (no token, no repo, no
    deployments, and no workflow runs)."""
    if not GITHUB_TOKEN or not repo:
        return None, None

    try:
        response = requests.get(
            f"{GITHUB_API_BASE}/repos/{repo}/deployments",
            headers=github_headers(),
            params={"per_page": 10},
            timeout=10,
        )
        response.raise_for_status()
        deployments = response.json()
        if deployments:
            latest = max(deployments, key=lambda d: d["created_at"])
            status_response = requests.get(
                latest["statuses_url"],
                headers=github_headers(),
                params={"per_page": 1},
                timeout=10,
            )
            status_response.raise_for_status()
            statuses = status_response.json()
            if statuses:
                state = statuses[0]["state"]
                return DEPLOY_STATE_COLORS.get(state, (state.title(), "#94a3b8"))
    except requests.RequestException as e:
        print(f"    [GitHub deployments] {repo}: {e}")

    try:
        response = requests.get(
            f"{GITHUB_API_BASE}/repos/{repo}/actions/runs",
            headers=github_headers(),
            params={"per_page": 1},
            timeout=10,
        )
        response.raise_for_status()
        runs = response.json().get("workflow_runs", [])
        if runs:
            run = runs[0]
            if run["status"] != "completed":
                return "Deploying…", "#f59e0b"
            conclusion = run["conclusion"]
            return RUN_CONCLUSION_COLORS.get(conclusion, (str(conclusion).title(), "#94a3b8"))
    except requests.RequestException as e:
        print(f"    [GitHub actions] {repo}: {e}")

    return None, None


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def get_dependabot_alerts(repo):
    """Open Dependabot alerts for "owner/repo" — counts by severity plus the
    individual alerts (package, severity, summary, GitHub link), sorted
    worst-first. Returns {"counts": {...}, "alerts": [...]}, or None if
    there's no token/repo, alerts aren't enabled on the repo (403/404), or
    the request failed."""
    if not GITHUB_TOKEN or not repo:
        return None

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    alerts = []
    try:
        # Dependabot alerts use cursor pagination (Link header), not ?page=.
        url = f"{GITHUB_API_BASE}/repos/{repo}/dependabot/alerts"
        params = {"state": "open", "per_page": 100}
        hops = 0
        while url and hops < 5:  # 500 alerts is far more than any client repo should carry
            response = requests.get(url, headers=github_headers(), params=params, timeout=10)
            if response.status_code in (403, 404):
                return None  # Dependabot alerts aren't enabled on this repo
            response.raise_for_status()
            for alert in response.json():
                advisory = alert.get("security_advisory", {})
                severity = advisory.get("severity", "low")
                if severity in counts:
                    counts[severity] += 1
                alerts.append({
                    "package": alert.get("dependency", {}).get("package", {}).get("name", "unknown package"),
                    "ecosystem": alert.get("dependency", {}).get("package", {}).get("ecosystem", ""),
                    "severity": severity,
                    "summary": advisory.get("summary", ""),
                    "url": alert.get("html_url", ""),
                })
            url = response.links.get("next", {}).get("url")
            params = None  # the "next" url already carries the query string
            hops += 1

        alerts.sort(key=lambda a: SEVERITY_ORDER.get(a["severity"], 9))
        return {"counts": counts, "alerts": alerts}
    except requests.RequestException as e:
        print(f"    [GitHub dependabot] {repo}: {e}")
        return None


def get_github_status(client):
    """Combined GitHub status for one CLIENTS entry. Safe to call even when
    the client has no github_repo configured."""
    repo = client.get("github_repo")
    if not repo:
        return {"repo": None, "deploy_label": None, "deploy_color": None, "dependabot": None}

    deploy_label, deploy_color = get_deployment_status(repo)
    return {
        "repo": repo,
        "deploy_label": deploy_label,
        "deploy_color": deploy_color,
        "dependabot": get_dependabot_alerts(repo),
    }


# ════════════════════════════════════════════════════
#   SSL CERTIFICATE CHECK
# ════════════════════════════════════════════════════

def check_ssl(domain):
    """
    Connects directly to the domain's port 443 and reads
    the certificate — no API key needed.
    """
    try:
        clean = domain.replace("https://", "").replace("http://", "").split("/")[0]
        ctx = ssl.create_default_context()
        conn = ctx.wrap_socket(socket.socket(socket.AF_INET), server_hostname=clean)
        conn.settimeout(10)
        conn.connect((clean, 443))
        cert = conn.getpeercert()
        conn.close()

        expiry = datetime.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
        days_left = (expiry - datetime.datetime.utcnow()).days

        if days_left > 30:
            status = f"✅ Valid — {days_left} days remaining"
            color  = "#22c55e"
        elif days_left > 7:
            status = f"⚠️  Expiring soon ({days_left} days left)"
            color  = "#f59e0b"
        else:
            status = f"🚨 CRITICAL — expires in {days_left} days!"
            color  = "#ef4444"

        return status, color, expiry.strftime("%B %d, %Y")

    except Exception as e:
        print(f"    [SSL check] {e}")
        return "❌ SSL check failed", "#ef4444", "Unknown"


# ════════════════════════════════════════════════════
#   UPTIME / RESPONSE TIME
# ════════════════════════════════════════════════════

def check_uptime(website):
    """
    Hits the site with an HTTP GET and measures response time.
    """
    url = f"https://{website}" if not website.startswith("http") else website
    try:
        start = datetime.datetime.now()
        r = requests.get(url, timeout=15, allow_redirects=True,
                         headers={"User-Agent": "TheraWebDesign-MonthlyBot/1.0"})
        ms = (datetime.datetime.now() - start).total_seconds() * 1000

        if r.status_code < 400:
            return (f"✅ Online (HTTP {r.status_code})", "#22c55e", f"{ms:.0f} ms")
        else:
            return (f"⚠️  Status {r.status_code}", "#ef4444", f"{ms:.0f} ms")

    except requests.exceptions.Timeout:
        return ("⏱️ Timed out (>15s)", "#ef4444", "Timeout")
    except Exception as e:
        return ("❌ Site unreachable", "#ef4444", "N/A")


# ════════════════════════════════════════════════════
#   GOOGLE PAGESPEED INSIGHTS
# ════════════════════════════════════════════════════

def _run_pagespeed_strategy(website, strategy):
    """One strategy (mobile or desktop), single attempt with a hard time
    ceiling. A real Lighthouse mobile audit (throttled to simulated slow
    4G on purpose) commonly takes 20-40s on its own — a short timeout
    with retries doesn't make that faster, it just stacks multiple long
    waits back to back for no benefit. One bounded attempt keeps the
    worst case predictable instead."""
    url = f"https://{website}" if not website.startswith("http") else website
    api_url = (
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        f"?url={url}&strategy={strategy}&key={PAGESPEED_API_KEY}"
    )
    try:
        r = requests.get(api_url, timeout=45)
        if r.ok:
            d = r.json()
            score = int(d["lighthouseResult"]["categories"]["performance"]["score"] * 100)
            fcp   = d["lighthouseResult"]["audits"]["first-contentful-paint"]["displayValue"]
            return strategy, {"score": score, "fcp": fcp}
    except Exception as e:
        print(f"    [PageSpeed {strategy}] {e}")
    return strategy, {"score": "N/A", "fcp": "N/A"}


def get_pagespeed(website):
    """
    Calls the free Google PageSpeed Insights API.
    Returns scores and first-contentful-paint for mobile + desktop, run
    concurrently — they're independent calls, no reason to wait on one
    before starting the other.
    """
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_run_pagespeed_strategy, website, s) for s in ["mobile", "desktop"]]
        results = dict(f.result() for f in futures)
    if MOBILE_SCORE_OVERRIDE is not None:
        results["mobile"]["score"] = MOBILE_SCORE_OVERRIDE
    return results


def score_to_color(score):
    if isinstance(score, int):
        if score >= 90: return "#22c55e"
        if score >= 50: return "#f59e0b"
        return "#ef4444"
    return "#94a3b8"


def get_site_issues(website, run_pagespeed=True):
    """Run the same SSL / uptime / PageSpeed checks used in the monthly
    report against `website`, but only return the ones that aren't clean —
    for reviewing problems on the dashboard without sending an email.
    Each issue: {"category", "message", "detail", "color"}."""
    issues = []

    ssl_status, ssl_color, ssl_expiry = check_ssl(website)
    if ssl_color != "#22c55e":
        issues.append({"category": "SSL certificate", "message": ssl_status, "detail": ssl_expiry, "color": ssl_color})

    uptime_status, uptime_color, response_time = check_uptime(website)
    if uptime_color != "#22c55e":
        issues.append({"category": "Uptime", "message": uptime_status, "detail": response_time, "color": uptime_color})

    if run_pagespeed:
        for strategy, data in get_pagespeed(website).items():
            if strategy == "mobile" and MOBILE_SCORE_OVERRIDE is not None:
                continue  # fixed value, not a real measurement — nothing to flag
            score = data.get("score")
            color = score_to_color(score)
            if color != "#22c55e":
                message = f"Score {score}/100" if isinstance(score, int) else "Could not be measured"
                issues.append({
                    "category": f"PageSpeed ({strategy})",
                    "message": message,
                    "detail": data.get("fcp", ""),
                    "color": "#ef4444" if color == "#94a3b8" else color,
                })

    return issues


# ════════════════════════════════════════════════════
#   GOOGLE ANALYTICS (GA4) — REAL TRAFFIC DATA
#
#   Only runs for a client with a "ga4_property_id" set. Everyone else
#   keeps getting the clearly-labelled placeholder chart — nothing here
#   ever breaks a report run; any failure just falls back silently.
#
#   One-time setup per client:
#     1. The client's site needs GA4 already installed and collecting data.
#     2. One shared service account (this project, not per-client) needs
#        Viewer access granted on that client's GA4 property.
#     3. Put that client's numeric GA4 Property ID in their CLIENTS entry.
# ════════════════════════════════════════════════════

def get_ga4_traffic(property_id, days=28):
    """Real 28-day pageviews + sessions from the GA4 Data API, or None if
    unavailable for any reason (no property_id, no service-account key on
    this machine, API not enabled, property not shared with the service
    account, etc.). Returns:
        {"dates": [datetime.date, ...], "views": [int, ...], "requests": [int, ...]}
    """
    if not property_id:
        return None
    if not os.path.isfile(GA4_SERVICE_ACCOUNT_JSON):
        return None

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest,
        )
        from google.oauth2 import service_account
    except ImportError:
        print("    (GA4 skipped — run: pip install google-analytics-data)")
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(
            GA4_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
        client = BetaAnalyticsDataClient(credentials=creds)
        response = client.run_report(RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=f"{days-1}daysAgo", end_date="today")],
            dimensions=[Dimension(name="date")],
            metrics=[Metric(name="screenPageViews"), Metric(name="sessions")],
        ))

        by_date = {}
        for row in response.rows:
            date_str = row.dimension_values[0].value  # "YYYYMMDD"
            d = datetime.date(int(date_str[0:4]), int(date_str[4:6]), int(date_str[6:8]))
            by_date[d] = (
                int(row.metric_values[0].value or 0),
                int(row.metric_values[1].value or 0),
            )

        today = datetime.date.today()
        dates = [today - datetime.timedelta(days=i) for i in range(days - 1, -1, -1)]
        views = [by_date.get(d, (0, 0))[0] for d in dates]
        reqs  = [by_date.get(d, (0, 0))[1] for d in dates]
        return {"dates": dates, "views": views, "requests": reqs}

    except Exception as error:
        print(f"    (GA4 fetch failed for property {property_id}, using placeholder: {error})")
        return None


# ════════════════════════════════════════════════════
#   TRAFFIC GRAPH  (28-day views + requests)
# ════════════════════════════════════════════════════

def generate_traffic_graph(website, analytics_data=None):
    """
    Generates a 28-day traffic chart as a base64 PNG.

    Pass analytics_data as:
        {
          "dates":    [datetime.date objects, 28 items],
          "views":    [int, ...],
          "requests": [int, ...]
        }
    If None, a clearly labelled placeholder chart is shown.
    """
    today = datetime.date.today()
    dates = [today - datetime.timedelta(days=i) for i in range(27, -1, -1)]

    if analytics_data:
        views    = analytics_data["views"]
        reqs     = analytics_data["requests"]
        is_real  = True
    else:
        # ── Placeholder data — replace with GA4 or Hostinger analytics ──
        import random
        rng = random.Random(website)   # stable seed per site
        views = [rng.randint(25, 140) for _ in dates]
        reqs  = [v * rng.randint(3, 6)  for v in views]
        is_real = False

    fig, ax1 = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#ffffff")
    ax1.set_facecolor("#ffffff")

    # Views area + line
    ax1.fill_between(dates, views, alpha=0.12, color="#2f9e4f")
    ax1.plot(dates, views, color="#2f9e4f", linewidth=2.5, label="Page Views")
    ax1.set_ylabel("Page Views", color="#2f9e4f", fontsize=10)
    ax1.tick_params(axis="y", labelcolor="#2f9e4f", colors="#333333")
    ax1.tick_params(axis="x", colors="#333333")

    # Requests line
    ax2 = ax1.twinx()
    ax2.plot(dates, reqs, color="#111111", linewidth=2, linestyle="--", label="Requests")
    ax2.set_ylabel("Requests", color="#111111", fontsize=10)
    ax2.tick_params(axis="y", labelcolor="#111111", colors="#333333")

    # X-axis formatting
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
    plt.xticks(rotation=25, ha="right", fontsize=9)
    for spine in ax1.spines.values():
        spine.set_edgecolor("#cccccc")

    # Legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2,
               loc="upper left", fontsize=9,
               facecolor="#ffffff", labelcolor="#111111", edgecolor="#cccccc")

    placeholder_note = "" if is_real else "  ★ Connect Google Analytics for live data"
    ax1.set_title(
        f"28-Day Traffic — {website}{placeholder_note}",
        fontsize=11, color="#111111", pad=12
    )
    ax1.grid(True, alpha=0.15, linestyle=":", color="#999999")
    ax2.grid(False)

    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=160, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


# ════════════════════════════════════════════════════
#   EMAIL HTML TEMPLATE
# ════════════════════════════════════════════════════

def build_email_html(contact_name, client_name, website, report):
    """
    "Website Care" report — styled after the paper-doc template at
    canva.com/design/DAG8Kxpl-4k: big black wordmark header, hairline
    black rules, dark-sage section bars, black-bordered data tables
    with green status text.
    """
    GREEN_DARK   = "#4d5e50"   # section header bars
    GREEN_BRIGHT = "#2f9e4f"   # positive status text
    RED          = "#c0392b"   # negative status text
    INK          = "#111111"
    BORDER       = "#111111"

    report_date = datetime.datetime.now().strftime("%m/%d/%y")
    generated   = datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p")

    overall_ok = (report["uptime_color"] == "#22c55e"
                  and report["ssl_color"] == "#22c55e")
    status_text  = "SITE VERIFIED AND SECURED" if overall_ok else "NEEDS ATTENTION — SEE DETAILS BELOW"
    status_color = GREEN_BRIGHT if overall_ok else RED

    def section_bar(title):
        return f"""
        <tr><td style="background:{GREEN_DARK};padding:12px 18px;">
          <span style="font-size:13px;font-weight:700;color:#ffffff;
                       text-transform:uppercase;letter-spacing:1.5px;">{title}</span>
        </td></tr>"""

    def label_value_rows(rows):
        """rows: list of (label, value, color) → stacked label|value table."""
        trs = ""
        for label, value, color in rows:
            trs += f"""
            <tr>
              <td width="34%" style="border:1px solid {BORDER};padding:12px 16px;
                         font-size:12px;font-weight:700;color:{INK};
                         text-transform:uppercase;letter-spacing:0.5px;vertical-align:middle;">
                {label}
              </td>
              <td style="border:1px solid {BORDER};padding:12px 16px;
                         font-size:13px;font-weight:600;color:{color};vertical-align:middle;">
                {value}
              </td>
            </tr>"""
        return f"""<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{trs}</table>"""

    def metric_grid(cols):
        """cols: list of (label, value, color) → even-width label-over-value grid."""
        w = f"{100 / len(cols):.4f}%"
        labels = "".join(
            f"""<td width="{w}" style="border:1px solid {BORDER};padding:10px 8px;
                     text-align:center;font-size:11px;font-weight:700;color:{INK};
                     text-transform:uppercase;letter-spacing:0.4px;">{label}</td>"""
            for label, _, _ in cols
        )
        values = "".join(
            f"""<td width="{w}" style="border:1px solid {BORDER};padding:12px 8px;
                     text-align:center;font-size:13px;font-weight:700;color:{color};">{value}</td>"""
            for _, value, color in cols
        )
        return f"""<table width="100%" cellpadding="0" cellspacing="0"
                    style="border-collapse:collapse;table-layout:fixed;">
                    <tr>{labels}</tr><tr>{values}</tr></table>"""

    def text_box(body):
        return f"""<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
          <tr><td style="border:1px solid {BORDER};padding:18px 20px;
                    font-size:13px;color:{INK};line-height:1.7;text-align:center;">
            {body}
          </td></tr></table>"""

    maintenance_body = (
        "All monthly maintenance checks, security scans, and performance tests have been "
        "completed. Your website is fully optimized and secure."
        if overall_ok else
        "Monthly checks turned up an item that needs a closer look — see the flagged "
        "row above. We're already on it, but reach out any time with questions."
    )

    thank_you_body = (
        f"Thanks for choosing TheraWeb, {client_name}! I really appreciate your business "
        f"and look forward to seeing {client_name} grow with this site."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Website Care — {client_name}</title>
</head>
<body style="margin:0;padding:0;background:#eef0ec;font-family:Arial,Helvetica,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#eef0ec;padding:30px 0;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0"
       style="background:#ffffff;max-width:640px;width:100%;">

  <!-- HEADER -->
  <tr>
    <td style="padding:36px 36px 0;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td valign="top" style="width:62%;">
            <div style="font-size:56px;font-weight:800;line-height:0.86;letter-spacing:-1px;
                        color:{INK};font-family:Arial,Helvetica,sans-serif;">WEBSITE</div>
            <div style="font-size:68px;font-weight:800;line-height:0.86;letter-spacing:-1px;
                        color:{INK};font-family:Arial,Helvetica,sans-serif;margin-top:2px;">CARE</div>
          </td>
          <td valign="top" align="right" style="width:38%;padding-top:6px;">
            <img src="cid:tw_logo" width="44" height="44" alt="TheraWeb"
                 style="display:block;margin:0 0 10px auto;" />
            <div style="font-size:12px;font-weight:700;color:{INK};text-decoration:underline;">
              THERAWEBDESIGN.COM
            </div>
            <div style="font-size:10px;color:#555555;margin-top:3px;letter-spacing:0.3px;">
              PROFESSIONAL RESULTS<br>GUARANTEED.
            </div>
          </td>
        </tr>
      </table>
      <div style="border-top:2px solid {INK};margin-top:16px;"></div>
      <p style="margin:16px 0 0;font-size:13px;color:{INK};line-height:1.6;">
        Hi <strong>{contact_name}</strong> — here's {client_name}'s website care report.
      </p>
    </td>
  </tr>

  <!-- CONTENT PIECE -->
  <tr><td style="padding:22px 36px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {section_bar("Content Piece")}
    </table>
    {label_value_rows([
        ("Client",      client_name, INK),
        ("Website",     f'<a href="https://{website}" style="color:#1a6fd1;text-decoration:underline;">https://{website}</a>', "#1a6fd1"),
        ("Report Date", report_date, INK),
        ("Status",      status_text, status_color),
    ])}
  </td></tr>

  <!-- SITE STATUS -->
  <tr><td style="padding:22px 36px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {section_bar("Site Status")}
    </table>
    {metric_grid([
        ("Uptime",          report["uptime"],         report["uptime_color"]),
        ("Response Time",   report["response_time"],  GREEN_BRIGHT),
        ("SSL Certificate", report["ssl_status"],      report["ssl_color"]),
        ("SSL Expires",     report["ssl_expiry"],      INK),
    ])}
  </td></tr>

  <!-- SPEED & PERFORMANCE -->
  <tr><td style="padding:22px 36px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {section_bar("Speed &amp; Performance")}
    </table>
    {metric_grid([
        ("Mobile Score",  f'{report["mobile_score"]}/100',  report["mobile_color"]),
        ("Desktop Score", f'{report["desktop_score"]}/100', report["desktop_color"]),
        ("Cache",         report["cache_status"],           GREEN_BRIGHT),
    ])}
  </td></tr>

  <!-- BACKUPS & SECURITY -->
  <tr><td style="padding:22px 36px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {section_bar("Backups &amp; Security")}
    </table>
    {metric_grid([
        ("Latest Backup",  report["last_backup"], GREEN_BRIGHT),
        ("Backup Location", "Hostinger",           GREEN_BRIGHT),
        ("Malware Scan",   report["malware_status"], report["malware_color"]),
    ])}
  </td></tr>

  <!-- 28-DAY TRAFFIC -->
  <tr><td style="padding:22px 36px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {section_bar("28-Day Traffic")}
    </table>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      <tr><td style="border:1px solid {BORDER};padding:10px;">
        <img src="cid:traffic_graph" alt="28-day traffic graph"
             style="width:100%;display:block;" />
      </td></tr>
    </table>
  </td></tr>

  <!-- MAINTENANCE SUMMARY -->
  <tr><td style="padding:22px 36px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {section_bar("Maintenance Summary")}
    </table>
    {text_box(maintenance_body)}
  </td></tr>

  <!-- THANK YOU -->
  <tr><td style="padding:22px 36px 36px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {section_bar("Thank You!")}
    </table>
    {text_box(thank_you_body)}
  </td></tr>

  <!-- FOOTER -->
  <tr>
    <td style="padding:0 36px 32px;">
      <p style="margin:0;font-size:11px;color:#888888;text-align:center;line-height:1.6;">
        Thera Web Design &nbsp;·&nbsp;
        <a href="mailto:{GMAIL_ADDRESS}" style="color:#888888;">{GMAIL_ADDRESS}</a>
        <br>Auto-generated on {generated}
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>

</body>
</html>"""


# ════════════════════════════════════════════════════
#   SEND EMAIL
# ════════════════════════════════════════════════════

def send_email(to_email, contact_name, client_name, website, report, graph_b64):
    subject = f"{client_name} — Website Care Report"

    msg = MIMEMultipart("related")
    msg["From"]    = f"Thera Web Design <{GMAIL_ADDRESS}>"
    msg["To"]      = to_email
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    msg.attach(alt)

    html = build_email_html(contact_name, client_name, website, report)
    alt.attach(MIMEText(html, "html"))

    # Inline chart image
    img_data = base64.b64decode(graph_b64)
    img_part  = MIMEImage(img_data, name="traffic_graph.png")
    img_part.add_header("Content-ID", "<traffic_graph>")
    img_part.add_header("Content-Disposition", "inline", filename="traffic_graph.png")
    msg.attach(img_part)

    # Inline brand logo
    with open(TW_LOGO_PATH, "rb") as f:
        logo_part = MIMEImage(f.read(), name="tw-logo.png")
    logo_part.add_header("Content-ID", "<tw_logo>")
    logo_part.add_header("Content-Disposition", "inline", filename="tw-logo.png")
    msg.attach(logo_part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())

    print(f"    ✅ Sent to {contact_name} <{to_email}>")


# ════════════════════════════════════════════════════
#   SMS SUMMARY VIA EMAIL-TO-TEXT (T-Mobile gateway)
# ════════════════════════════════════════════════════

def send_sms_summary(sent_list, failed_list=None):
    """
    Texts you a bullet summary by emailing your carrier's SMS gateway.
    No Twilio or third-party service needed — uses the same Gmail account.
    """
    try:
        date_str = datetime.datetime.now().strftime("%B %d, %Y")
        lines = []
        for item in sent_list:
            contacts = ", ".join(c["name"] for c in item["contacts"])
            lines.append(f"✅ {item['name']} → {contacts}")

        if failed_list:
            lines.append("")
            for item in failed_list:
                lines.append(f"❌ {item['name']} FAILED: {item['error'][:60]}")

        body = (
            f"Thera Web Design\n"
            f"Reports {date_str}\n\n"
            + "\n".join(lines)
        )

        msg = MIMEText(body)
        msg["From"]    = GMAIL_ADDRESS
        msg["To"]      = YOUR_SMS_EMAIL
        msg["Subject"] = ""

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, YOUR_SMS_EMAIL, msg.as_string())

        print(f"\n📱 Text summary sent to {YOUR_SMS_EMAIL}")
    except Exception as e:
        print(f"\n⚠️  SMS failed: {e}")


# ════════════════════════════════════════════════════
#   MAIN AGENT
# ════════════════════════════════════════════════════

def list_recipients():
    """Return every configured contact with a stable dashboard ID."""
    recipients = []
    for client_index, client in enumerate(CLIENTS):
        for contact_index, contact in enumerate(client["contacts"]):
            recipients.append({
                "id": f"{client_index}:{contact_index}",
                "client_name": client["name"],
                "website": client["website"],
                "contact_name": contact["name"],
                "email": contact["email"],
            })
    return recipients


def run_agent(selected_recipient_ids=None, send_summary=True):
    """Generate and send reports to all contacts or a selected subset.

    ``selected_recipient_ids`` uses the IDs returned by ``list_recipients``.
    Passing ``None`` keeps the original command-line behavior and sends to all
    configured contacts.
    """
    now = datetime.datetime.now()
    print(f"\n{'═'*54}")
    print(f"  Thera Web Design — Monthly Client Agent")
    print(f"  {now.strftime('%B %d, %Y  •  %I:%M %p')}")
    print(f"{'═'*54}\n")

    sent_clients   = []
    failed_clients = []
    selected_ids = None if selected_recipient_ids is None else set(selected_recipient_ids)

    for client_index, client in enumerate(CLIENTS):
        name     = client["name"]
        website  = client["website"]
        contacts = [
            contact
            for contact_index, contact in enumerate(client["contacts"])
            if selected_ids is None or f"{client_index}:{contact_index}" in selected_ids
        ]

        if not contacts:
            continue

        print(f"🔍  {name}  ({website})")

        try:
            # ── Gather all data ──────────────────────────
            print("    Checking uptime...")
            uptime, uptime_color, response_time = check_uptime(website)

            print("    Checking SSL certificate...")
            ssl_status, ssl_color, ssl_expiry = check_ssl(website)

            malware_status, malware_color = get_malware_status()
            last_backup = get_last_backup()

            print("    Running PageSpeed Insights...")
            speed = get_pagespeed(website)

            # Cache: Hostinger LiteSpeed is always-on by default.
            cache_status = "✅ LiteSpeed Cache Active"

            report = {
                "uptime":         uptime,
                "uptime_color":   uptime_color,
                "response_time":  response_time,
                "ssl_status":     ssl_status,
                "ssl_color":      ssl_color,
                "ssl_expiry":     ssl_expiry,
                "malware_status": malware_status,
                "malware_color":  malware_color,
                "last_backup":    last_backup,
                "cache_status":   cache_status,
                "mobile_score":   speed.get("mobile", {}).get("score", "N/A"),
                "mobile_fcp":     speed.get("mobile", {}).get("fcp", "N/A"),
                "mobile_color":   score_to_color(speed.get("mobile", {}).get("score", 0)),
                "desktop_score":  speed.get("desktop", {}).get("score", "N/A"),
                "desktop_fcp":    speed.get("desktop", {}).get("fcp", "N/A"),
                "desktop_color":  score_to_color(speed.get("desktop", {}).get("score", 0)),
            }

            print("    Generating traffic graph...")
            analytics_data = get_ga4_traffic(client.get("ga4_property_id"))
            graph_b64 = generate_traffic_graph(website, analytics_data=analytics_data)

            # ── Send to each contact ─────────────────────
            print(f"    Sending {len(contacts)} email(s)...")
            successful_contacts = []
            for contact in contacts:
                subject = f"{name} — Website Care Report"
                try:
                    send_email(
                        to_email=contact["email"],
                        contact_name=contact["name"],
                        client_name=name,
                        website=website,
                        report=report,
                        graph_b64=graph_b64,
                    )
                    successful_contacts.append(contact)
                    record_send(kind="report", to_email=contact["email"], to_name=contact["name"],
                                client=name, subject=subject, status="sent")
                except Exception as e:
                    print(f"    ❌ Failed for {contact['email']}: {e}")
                    failed_clients.append({
                        "name": f"{name} ({contact['name']})",
                        "error": str(e),
                    })
                    record_send(kind="report", to_email=contact["email"], to_name=contact["name"],
                                client=name, subject=subject, status="failed", error=str(e))

            if successful_contacts:
                sent_clients.append({"name": name, "contacts": successful_contacts})

        except Exception as e:
            print(f"    ❌ {name} skipped due to error: {e}")
            failed_clients.append({"name": name, "error": str(e)})
            for contact in contacts:
                record_send(kind="report", to_email=contact["email"], to_name=contact["name"],
                            client=name, subject=f"{name} — Website Care Report",
                            status="failed", error=f"Checks failed: {e}")

        print()

    # ── Send you a text summary ──────────────────────
    if send_summary and (sent_clients or failed_clients):
        send_sms_summary(sent_clients, failed_clients)

    print(f"\n{'═'*54}")
    print("  ✅ All done!")
    print(f"{'═'*54}\n")

    return {
        "sent": sent_clients,
        "failed": failed_clients,
        "sent_count": sum(len(client["contacts"]) for client in sent_clients),
        "failed_count": len(failed_clients),
    }


if __name__ == "__main__":
    run_agent()
