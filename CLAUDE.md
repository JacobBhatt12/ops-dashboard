# CLAUDE.md — Thera Web Design Monthly Agent

This file tells Claude Code everything it needs to know about this project.
Read this first before touching any file.

---

## What This Project Does

Automated monthly client management agent for **Thera Web Design**.

When run (manually, or automatically on the schedule set in the dashboard), the agent:
1. Loops through every client in the `CLIENTS` list
2. Pulls live data from multiple sources (Hostinger API, SSL check, Google PageSpeed)
3. Builds a polished branded HTML email with a 28-day traffic graph embedded
4. Sends that email from `you@example.com` to each contact for that client
5. Texts the owner (via `YOUR_SMS_EMAIL` in `.env`) a bullet summary of every email sent

The dashboard (`Thera Dashboard.app` / `management_app.py`) has a **schedule
panel** for turning on an automatic monthly send (day of month + time). When
enabled, it installs a `launchd` LaunchAgent that runs independently of the
app — the automatic send fires even if `Thera Dashboard.app` isn't open,
as long as the Mac is on and the user is logged in. See "Automatic Monthly
Send" below.

---

## File Map

```
monthly_agent.py       ← The entire monthly client-report agent. Single-file. Start here.
management_app.py      ← Local dashboard server: monthly-report send API, schedule API,
                          customers API, Web3Forms-keys API, read-only outreach-bot status,
                          and the "sent today" / send-activity APIs (see below)
send_log.py            ← Append-only JSONL log of every report email the agent sends
                          (data/send_log.jsonl). Written from run_agent(); read by the dashboard.
dashboard/              ← Dashboard HTML, CSS, and JavaScript — 5 pages (see below). Shared:
                          styles.css (design tokens + components), shell.js (sidebar/topbar/
                          filter/badges), motion.js (GSAP animation helpers), vendor/gsap.min.js
                          (GSAP 3.12.5, vendored so the app works offline)
scheduled_send.sh       ← launchd entry point — runs monthly_agent.py for ALL clients, no TTY guard
schedule_config.json    ← Saved schedule (day/hour/minute/enabled) — written by the dashboard, gitignore-able
schedule_log.txt        ← stdout/stderr from the last automatic (launchd) run
SETUP_GUIDE.md          ← Human-readable setup instructions (non-developer friendly)
CLAUDE.md               ← This file
agent_log.txt           ← Historical output from a previous, now-removed scheduled workflow

bot/                    ← Cold-outreach bot (merged in from the former "Email Sender Bot"
                          project on 2026-09-14). Same venv, same launchd domain as this app.
                          bot/status_json.py is read directly (in-process import) by
                          management_app.py for the /outreach page — never subprocess.
config.yaml             ← Cold-outreach bot config (volume, schedule, safety limits)
data/                   ← client_secret.json, token.json, outreach.db, blocklist.txt,
                          Master List - All Contacts.xlsx (bot), plus customers.json and
                          web3forms_keys.json (dashboard) — all gitignored
logs/                   ← Cold-outreach bot's daily run logs (bot writes here directly)
requirements.txt        ← Combined dependency list for both the monthly agent and the bot
scripts/                ← com.nimble.emailsender.plist (outreach weekday-8AM launchd job),
                          status.sh, uninstall.sh — carried over from the merged project
```

## Dashboard pages

| Route | Page | Purpose |
|---|---|---|
| `/` | Client reports | Pick recipients, send the monthly Website Care email. **Clients only** — no outreach data here (owner's call, 2026-09-15) |
| `/outreach` | Cold outreach | Read-only status of `bot/` — KPIs, run-day bar chart, and a Blocks radial whose footer is a dropdown listing every blocked address (`status_json` now returns the full `blocks` list) — plus, at the bottom, *all* email activity (reports + outreach): 14-day area chart, "Today by client" radial, and the "Emails sent today" table that resets at midnight |
| `/errors` | Errors | SSL/uptime/PageSpeed/deploy/Dependabot checks for every client site |
| `/customers` | Customers | Searchable list from `data/customers.json` — update that file to keep it in sync |
| `/keys` | Web3Forms keys | Per-client Web3Forms keys, released only after the PIN in `data/web3forms_keys.json` is entered (`/api/web3forms-keys/unlock`) — a local convenience gate, not real auth |

## Dashboard design & motion

The dashboard is modeled on the Zenith shadcn CRM template (`design.md` has the
reverse-engineered tokens): pure grayscale surfaces, colour only in charts and
status pills, 260px collapsible sidebar, blurred sticky topbar with a ⌘K page
filter, 4-up KPI row with full-bleed sparklines, a 12-column content grid
(8/4 and 7/5 splits), 20px card padding, 16px gaps, 44px table rows.

Motion is GSAP (`dashboard/vendor/gsap.min.js`, loaded before `motion.js`).
`window.Motion` exposes: `reveal` (cards stagger in — anything with
`data-reveal`), `countUp` (KPI numbers), `sparkline` (line draws itself),
`radial` (shadcn-style stacked half-radial: rounded 5px-corner sections with
2px gaps sweep in across a 180° arc, total centred at the base; legend hover
dims the other sections),
`growBars` (bars grow from baseline, and tween between datasets on the
segmented toggle), `tweenArray` (the home-page area chart morphs between
All / Reports / Outreach), `fillBars`, `rows`, `pulse`. Everything falls back to
the final state instantly under `prefers-reduced-motion` or if GSAP fails to
load. `html.motion [data-reveal]` starts at opacity 0 with a 2 s CSS safety
animation so content can never stay hidden.

## Emails sent today (resets daily)

The Cold outreach page's "Emails sent today" table, "Today by client" radial,
the home page's "Reports sent today" KPI, and the sidebar badges all come from
`GET /api/sent-today`, which merges two sources
for the **local calendar date** (so the view naturally resets at midnight):

- `data/send_log.jsonl` — every Website Care report the monthly agent sent or
  failed to send (`send_log.record_send`, called inside `run_agent()` so both
  dashboard sends and the unattended launchd send are captured).
- `data/outreach.db` `sends` table — the cold-outreach bot's own record, opened
  read-only.

`GET /api/send-activity?days=14` returns per-day `reports` / `outreach` /
`failed` counts for the area chart and KPI sparkline.

Static files: anything under `dashboard/` is served by path (with a
traversal guard); the five page routes map to their HTML files explicitly.

## Merged cold-outreach bot (`bot/`)

This was originally a separate project (`Email Sender Bot/`, briefly at `theraweb-outreach-bot/`
before that). It was folded into this project on 2026-09-14 so the whole business runs out of
one folder with one venv. Its own `README.md`-level operational detail:

- Sends the "Your branded website" cold email from `you@example.com`, weekdays, one
  batch a day (`config.yaml` → `volume.daily_target`), spread across `schedule.start_hour`–`end_hour`.
- `bot/config.py`'s `ROOT` is `Path(__file__).resolve().parent.parent` — i.e. wherever `bot/`
  physically lives. Nothing in `bot/` hardcodes this project's path, so it stays portable.
- Scheduled via its own launchd job, `com.nimble.emailsender` (separate from this app's
  `com.theraweb.monthlyagent`), weekdays at 10 AM (moved from 8 AM on 2026-09-15 — no reliable
  wifi at home before ~10, campus wifi by then) — **only fires while the Mac is awake and
  logged in; a fully shut-down Mac skips that day entirely, no catch-up.** Re-register it with:
  ```bash
  PROJECT="$(pwd)"; PY="$PROJECT/venv/bin/python3"
  sed -e "s|__PYTHON__|$PY|g" -e "s|__PROJECT__|$PROJECT|g" \
      scripts/com.nimble.emailsender.plist > /tmp/com.nimble.emailsender.plist
  launchctl bootout "gui/$(id -u)/com.nimble.emailsender" 2>/dev/null
  cp /tmp/com.nimble.emailsender.plist "$HOME/Library/LaunchAgents/com.nimble.emailsender.plist"
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.nimble.emailsender.plist"
  ```
  Do this again any time this project folder is renamed or moved — the plist embeds an absolute
  path and does not update itself.
- Manual runs: `venv/bin/python3 -m bot.run_daily --dry-run|--preview N|--limit N|--now`.
- `venv/bin/python3 -m bot.status_json` prints the same JSON the `/outreach` page reads.

---

## Architecture — How the Agent Is Structured

`monthly_agent.py` is divided into clearly labelled sections:

| Section | What it does |
|---|---|
| **CONFIGURATION** | Loads API keys/credentials from `.env` and the `CLIENTS` list from `data/clients.json`. Edit those files, not this block. |
| **HOSTINGER API** | Calls `api.hostinger.com/v1` for backup dates and Monarx malware results |
| **SSL CHECK** | Uses Python's built-in `ssl` module — no API key needed |
| **UPTIME CHECK** | Simple HTTP GET to measure if site is up and how fast it responds |
| **GOOGLE PAGESPEED** | Calls PageSpeed Insights API v5 for mobile + desktop scores |
| **TRAFFIC GRAPH** | Generates a 28-day chart via `matplotlib`, encoded as base64 PNG |
| **EMAIL TEMPLATE** | `build_email_html()` — full inline HTML/CSS email, table-based layout |
| **SEND EMAIL** | Gmail SMTP over SSL port 465 using an App Password |
| **SMS SUMMARY** | Same Gmail account, via a carrier email-to-SMS gateway — sends one text to the owner after all emails sent |
| **MAIN AGENT** | `run_agent()` — orchestrates all of the above in sequence |

---

## Data Sources Per Report Field

| Report Field | Source | Notes |
|---|---|---|
| Uptime Status | HTTP GET to site URL | Built-in, no key needed |
| Response Time | Measured during uptime check | milliseconds |
| SSL Certificate | Python `ssl` module direct connect | Shows days until expiry |
| Last Backup | Hostinger API `/vps/backups` | VPS plans only; shared hosting may differ |
| Malware Scan | Hostinger API `/vps/monarx` | Monarx scanner results |
| Cache Status | Hardcoded string | Hostinger LiteSpeed is always-on; update if needed |
| PageSpeed Mobile | Google PageSpeed Insights API v5 | Requires free API key |
| PageSpeed Desktop | Google PageSpeed Insights API v5 | Same key |
| 28-Day Traffic Graph | **Real GA4 data if configured per client, placeholder otherwise** | See below |

---

## Traffic Graph — GA4 integration (built, needs activating per client)

Hostinger's public API doesn't expose visitor analytics, so this was placeholder
data for a while. The real GA4 integration is now built and live in the code
(`get_ga4_traffic()` in `monthly_agent.py`) — it's just **off for every client
by default** until each one is switched on individually. A client with no
`ga4_property_id` set, or if `data/ga4_service_account.json` doesn't exist,
silently keeps getting the placeholder chart — nothing ever breaks or crashes
either way, and the placeholder is clearly labelled in the chart title so it's
obvious which clients still need this.

**To activate it for a client, in order:**

1. **The client's own site needs GA4 already installed and collecting data.**
   This is on their end (or whoever manages their site tag/GTM) — most of
   these small-business sites probably don't have this yet. Nothing here can
   create traffic history retroactively; a freshly-added GA4 property starts
   empty and fills in going forward.
2. **One shared service account for this whole project** (not one per client):
   - In Google Cloud Console (the same project used for `PAGESPEED_API_KEY`,
     or a fresh one), enable the **Google Analytics Data API**.
   - Create a **Service Account**, download its JSON key, save it as
     `data/ga4_service_account.json` (gitignored, same pattern as the other
     credential files in `data/`).
3. **Per client**: in Google Analytics Admin → that property → **Property
   Access Management**, add the service account's email (from the JSON key,
   looks like `...@...iam.gserviceaccount.com`) as a **Viewer**.
4. **Per client**: copy the numeric **GA4 Property ID** (Admin → Property
   details) into that client's `"ga4_property_id"` field in `CLIENTS`
   (`monthly_agent.py`). It's `None` for every client right now.
5. Install the one new dependency: `pip3 install -r requirements.txt`
   (adds `google-analytics-data`).

That's it — no code changes needed per client, just steps 3–4 above. The next
report run for that client pulls real page views + sessions for the last 28
days automatically.

---

## Credentials Required (all stored in `.env`, gitignored — see `.env.example`)

| Variable | Where to get it |
|---|---|
| `HOSTINGER_API_KEY` | hPanel → Developer Tools → API Tokens |
| `GMAIL_ADDRESS` | The Gmail address reports are sent from |
| `GMAIL_APP_PASSWORD` | Google Account → Security → App Passwords (2FA must be on) |
| `PAGESPEED_API_KEY` | console.cloud.google.com → Enable PageSpeed Insights API → Credentials |
| `YOUR_SMS_EMAIL` | The owner's SMS summary address — a carrier email-to-SMS gateway (e.g. `number@tmomail.net`) or any email address |
| `GITHUB_TOKEN` | github.com → Settings → Developer settings → Fine-grained tokens (read-only, per-repo Deployments/Actions/Dependabot alerts) |

No Twilio or third-party SMS service is used — the SMS summary rides on the same Gmail account via a carrier's email-to-SMS gateway.

---

## Client List

Real client data (names, domains, GitHub repos, contact emails) lives in
`data/clients.json` — gitignored, never committed. `monthly_agent.py` loads
`CLIENTS` from that file at runtime via `_load_clients()`. See
`clients.example.json` at the project root for the exact shape each entry
needs: `name`, `website`, `github_repo` (`"owner/repo"`, or `null` if the
site has no GitHub repo yet — that client is then skipped for
deployment/Dependabot checks, no crash, the dashboard just shows "GitHub not
connected"), `ga4_property_id` (`null` until GA4 is activated for that
client), and a `contacts` list of `{"name", "email"}`.

To add a real client, add an entry to `data/clients.json` matching that
shape — no code changes needed, they're picked up on the next run.

---

## How to Add a New Client

Add a new entry to the `CLIENTS` array in `data/clients.json`:

```json
{
    "name": "Client Display Name",
    "website": "theirdomain.com",
    "github_repo": null,
    "ga4_property_id": null,
    "contacts": [
        {"name": "First Name", "email": "email@domain.com"},
        {"name": "Second Person", "email": "other@domain.com"}
    ]
}
```

No other changes needed. They'll be picked up on the next run.

---

## How to Open the Dashboard

```bash
cd /path/to/project
python3 management_app.py
```

The dashboard server listens at `http://127.0.0.1:8787` and, by default, opens
in its own native macOS window (via `pywebview`) rather than a browser tab.
Select individual contacts or use **Select all**, then click **Send
management emails**. The send API calls `run_agent()` with only those
selected recipient IDs.

---

## Automatic Monthly Send

The dashboard's schedule panel lets the owner turn on a fully automatic
monthly send (e.g. "the 15th at 10:00 AM") without opening the app that day.

How it works:
- Saving a schedule POSTs `{enabled, day, hour, minute}` to `/api/schedule`
  in `management_app.py` (`save_schedule` / `apply_schedule`).
- That writes `schedule_config.json` and installs a `launchd` **LaunchAgent**
  at `~/Library/LaunchAgents/com.theraweb.monthlyagent.plist`, using
  `launchctl bootstrap gui/<uid> <plist>` (and `bootout` first, since launchd
  doesn't pick up in-place edits to an already-loaded plist).
- The plist's `StartCalendarInterval` fires `scheduled_send.sh`, which runs
  `monthly_agent.py` directly — i.e. `run_agent()` with no recipient filter,
  so **every** configured client contact gets the report, plus the usual SMS
  summary to the owner. `scheduled_send.sh` deliberately does *not* use
  `run_thera_agent.sh`'s interactive-terminal guard, since launchd invokes it
  with no TTY.
- Turning the schedule off calls `launchctl bootout` and deletes the plist.
- Day is capped to 1–28 in both the UI and the `/api/schedule` validation, so
  every month always has that day (no 30th/31st edge cases).
- **Scope**: this is a *LaunchAgent*, not a LaunchDaemon — it only fires while
  the owner is logged into their Mac (screen-locked is fine; if asleep at the
  scheduled time, it fires on wake). It will NOT fire if the Mac is fully
  shut down or logged out at that moment. Confirmed acceptable for this
  owner's setup (Mac stays on and logged in). If that ever changes, this
  would need to move to a system LaunchDaemon (root-owned, requires sudo to
  install).
- Logs from automatic runs land in `schedule_log.txt`.

---

## Running the Agent

Manual sends have no automatic-send behavior on their own — launch via
**`/Applications/Thera Dashboard.app`** (drag to the Dock for one-click
access), double-click `Open Management Dashboard.command`, or run
`run_thera_agent.sh` from Terminal. All three run the same
`management_app.py` entry point and let you pick specific recipients.
Fully automatic, unattended sends to *all* clients go through the schedule
described above instead.

---

## Dependencies

```
pip3 install requests twilio matplotlib pillow pywebview
```

`pywebview` (with `pyobjc-framework-Cocoa`/`WebKit`, installed automatically as
its dependencies) renders the dashboard in a native macOS window instead of a
browser tab. If it isn't installed, `management_app.py` falls back to opening
the default web browser. Pass `--browser` to force browser mode even when
`pywebview` is available.

Standard library used: `ssl`, `socket`, `smtplib`, `datetime`, `base64`, `json`, `io`

Python 3.8+ required.

---

## Sender Identity

All emails sent as:
```
From: Thera Web Design <GMAIL_ADDRESS>
```

SMS summary sent to `YOUR_SMS_EMAIL` (the owner's phone, via carrier email-to-SMS gateway). Both are set in `.env`.

---

## What to Work On Next

If continuing development, priority order:

1. **Activate GA4 for each client** — the integration is built (see "Traffic Graph" section above); it just needs a service account + per-client property ID
2. **Verify Hostinger endpoints** — backup and Monarx endpoints target VPS API; confirm they match the hosting plan type used for client sites
3. **Add error email** — if a client's checks fail, optionally notify the owner
4. **HTML email preview** — open `build_email_html()` output in a browser to verify layout before sending to real clients
5. **Send log rotation** — `data/send_log.jsonl` is append-only; if it ever grows large, `send_log.daily_counts()` scans the whole file
