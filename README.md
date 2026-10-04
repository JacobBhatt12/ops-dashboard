# Agency Ops Dashboard

A small web design agency's back office, running unattended on a tiny
always-on Linux server. It sends every client a monthly site-health report
and keeps a steady pipeline of new business: each night it finds local
businesses with a published email, and each weekday it emails 200 of them
on a natural-looking schedule.

## What it does

**Client reports (monthly).** For every client: uptime, SSL expiry,
PageSpeed scores, Hostinger backup and malware status, and a 28-day GA4
traffic chart, built into one inline HTML email (the chart is an embedded
PNG, so it renders in Gmail and Outlook alike) and sent from the agency's
Gmail.

**Lead Finder (nightly + weekdays).**

1. *Import:* pulls small businesses for a state from the free
   [Overture Maps](https://overturemaps.org/) places dataset with DuckDB
   (home services, beauty, fitness, health, auto, pets, professional
   services, food, retail; chains excluded).
2. *Crawl (1:07am):* visits each business's website, finds a published
   email (mailto links, page text, contact pages), checks the domain
   accepts mail, and notes anything worth mentioning (site down, no
   HTTPS, not mobile-friendly, old copyright year, site-builder site,
   slow). Stops once enough leads are queued for the next day.
3. *Send (weekdays, 10am-10pm):* the outreach bot sends 200 emails through
   the Gmail API at randomized intervals. Each email opens with one real
   observation about that business's site; the rest is a fixed template
   with a signature and a CAN-SPAM opt-out and postal address.

**Safety rails.** Nobody is emailed twice. Before every run the bot scans
the inbox for opt-out replies and bounces and blocks those addresses for
good. All sending pauses if the hard-bounce rate passes 3%. The bot
refuses to send at all if the postal address isn't configured.

**Dashboard.** A local web app (vanilla JS + GSAP, no build step) with
pages for client reports, Lead Finder (counts, review queue, email
previews, settings), client site errors (GitHub deploy status and a site
issue checker), customers, and form keys.

## How it runs

```
1:07am daily     leadfinder.run nightly    import if the pool is low, crawl until 300 leads are queued
10:00 weekdays   bot.run_daily             scan replies/bounces, send 200 between 10am and 10pm
15th, 10:00      monthly_agent.py          client site-health reports
always           management_app.py         dashboard on port 8787 (systemd service)
```

Everything fits on a 1 GB e2-micro: DuckDB is capped at 300 MB and the
import runs in its own process, the crawler only scans text around `@`
signs, and send times are spread across the day.

## Project layout

```
management_app.py      Dashboard server and JSON API
monthly_agent.py       Monthly client report: data collection, email, send
send_log.py            Append-only log of client report sends
bot/                   Outreach sender: Gmail API, schedule, opt-out/bounce scanner
leadfinder/            Overture import, website crawler, lead store, email template
dashboard/             Dashboard pages (HTML/CSS/JS)
data/                  Client list, credentials, databases (gitignored)
config.yaml            Bot volume, send window and safety limits
.env.example           Every setting that holds credentials or personal details
```

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                       # API keys, Gmail, sender identity
cp clients.example.json data/clients.json  # your clients

python3 management_app.py                  # dashboard at http://127.0.0.1:8787
python3 -m leadfinder.run import --states FL
python3 -m leadfinder.run crawl --limit 500
python3 -m bot.run_daily --dry-run         # plan a send without sending
```

Then schedule `bot.run_daily` and `leadfinder.run nightly` with cron (the
Lead Finder settings page can install the nightly job), and run
`management_app.py` as a service.

## Configuration and privacy

Credentials and personal details are never in the code. `.env` holds API
keys, the Gmail address, the ntfy topic for phone alerts, and the sender
identity shown in emails (`SENDER_NAME`, `SENDER_EMAIL`, `SENDER_PHONE`,
`BUSINESS_WEBSITE`, `BUSINESS_POSTAL_ADDRESS`). `data/` holds client data,
the Gmail token and the databases. Both are gitignored.
