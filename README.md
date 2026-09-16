# Thera Web Design — Client Dashboard

An automated monthly reporting system for a small web design agency. Every
client gets a branded "site health" email each month — uptime, SSL status,
PageSpeed scores, backup/malware status, and a real traffic chart — sent
without anyone manually checking each site by hand. A local dashboard
drives it: pick recipients and send on demand, turn on a fully automatic
monthly schedule, or just check in on client site health and a separate
cold-outreach bot's activity.

## What it does

Once a month (on demand, or automatically via a configurable schedule):

1. Loops through every client on the list
2. Pulls live data for each one — Hostinger (backups, malware scan), an SSL
   certificate check, Google PageSpeed (mobile + desktop scores), and a
   28-day traffic chart from Google Analytics (GA4) where it's been
   activated for that client
3. Builds a fully inline, table-based HTML email with the chart embedded
   as a base64 PNG — no external image hosting, renders correctly in
   Outlook and Gmail alike
4. Sends it from the agency's Gmail account to every contact for that
   client
5. Texts the owner a one-line summary of everything that just went out

The dashboard wraps all of this in a small local web app: a page to pick
recipients and trigger sends, a schedule panel that installs a macOS
`launchd` job for fully unattended monthly runs, a client site-health page
(SSL/uptime/PageSpeed/deploy status per client), and a monitoring page for
a separate cold-outreach bot that lives in the same project.

## Features

- **Live per-client health checks** — SSL expiry, uptime + response time,
  PageSpeed mobile/desktop scores, Hostinger backup date and malware scan
  results, GitHub deployment status and Dependabot alerts where a client
  has a repo connected
- **Real traffic data** — GA4 integration is built and wired up; it's a
  clean per-client opt-in (one shared service account, then a property ID
  per client), and falls back to a clearly-labeled placeholder chart for
  anyone not yet on GA4, so nothing ever breaks
- **One-click and hands-off sending** — trigger a send for selected
  contacts from the dashboard, or flip on a monthly schedule and it runs
  unattended in the background via `launchd`, even if the dashboard app
  isn't open
- **Append-only send log** — every report the agent sends or fails to
  send is logged, which feeds the dashboard's daily send counts, a 14-day
  activity chart, and per-day breakdowns by client
- **Local-only by design** — the dashboard binds to loopback only; nothing
  about it is reachable from outside the machine it runs on
- **A second automation living alongside it** — a cold-outreach bot with
  its own rate limits, do-not-contact list, and daily schedule, monitored
  (read-only) from the same dashboard

## How it's built

- **Python** (3.8+) for the agent and the local server — standard library
  where it'll do (`smtplib`, `ssl`, `socket`), `matplotlib` for the traffic
  chart, no web framework, no ORM
- **Vanilla JS + GSAP** for the dashboard frontend — no build step, no
  framework, five plain HTML pages sharing a small set of hand-written JS
  modules for layout, motion, and API calls
- **Hostinger API**, **Google PageSpeed Insights API**, and the
  **Google Analytics Data API (GA4)** for live site data
- **macOS `launchd`** for scheduling both the monthly agent and the
  cold-outreach bot, each as its own LaunchAgent

## Project layout

```
monthly_agent.py       The agent: pulls data, builds the email, sends it
management_app.py      Local dashboard server — sends, schedule, site
                        health, customers, send-activity APIs
send_log.py            Append-only log of every report sent
dashboard/              Dashboard HTML/CSS/JS (5 pages, shared shell + motion)
bot/                    Cold-outreach bot — separate automation, same project
data/                   Real client list, credentials, bot state — gitignored
clients.example.json   Template showing the shape data/clients.json needs
.env.example            Template for the credentials data/.env needs
```

## Running it

```bash
python3 -m venv venv && source venv/bin/activate
pip3 install -r requirements.txt

cp .env.example .env                       # then fill in your own keys
cp clients.example.json data/clients.json  # then add your real clients

python3 management_app.py
```

The dashboard opens at `http://127.0.0.1:8787` (as a native window via
`pywebview` if it's installed, otherwise your default browser). `.env` and
`data/` are gitignored — real credentials and client contact info never
leave your machine.

## Credentials

Everything sensitive lives in `.env`, loaded at runtime — nothing is
hardcoded in the source. See `.env.example` for the full list: a
Hostinger API token, a Gmail address + app password, a free PageSpeed API
key, an SMS delivery address (any carrier's email-to-SMS gateway works),
and an optional fine-grained GitHub token for the deployment-status
checks.
