# ops-dashboard

A small web design agency's back office, running unattended on a tiny
always-on Linux server. It sends every client a monthly site-health report
and keeps a steady pipeline of new business: each night it finds local
businesses with a published email, and it emails up to 150 client prospects a day
on a natural-looking schedule. Client outreach is capped at 150/day;
agency outreach has a separate 150/day cap, alternating through the same
Gmail sender when both queues have eligible recipients.

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
3. *Send (weekdays, 10am-10pm):* the outreach bot sends up to 150 client emails through
   the Gmail API at randomized intervals. Each email opens with one real
   observation about that business's site; the rest is a fixed template
   with a signature and a CAN-SPAM opt-out and postal address.

**Safety rails.** Nobody is emailed twice. Before every run the bot scans
the inbox for opt-out replies and bounces and blocks those addresses for
good. All sending pauses if the hard-bounce rate passes 3%. The bot
refuses to send at all if the postal address isn't configured.

**Dashboard.** A web app (vanilla JS + GSAP, no build step) with pages
for client reports, cold outreach (send stats and history), Lead Finder
(counts, review queue, email previews, settings), client site errors
(GitHub deploy status and a site issue checker), customers, and form keys.
It opens in a native window (pywebview) or the browser, and can either run
locally or attach to the copy already running on the server.

## How it runs

```
1:07am daily     leadfinder.run nightly    import if the pool is low, crawl until 300 leads are queued
10:00 weekdays   bot.run_daily             scan replies/bounces, alternate up to 150 client + 150 agency emails
15th, 10:00      monthly_agent.py          client site-health reports
always           ops_dashboard.py          dashboard on port 8787 (systemd service)
```

Everything fits on a 1 GB e2-micro: DuckDB is capped at 300 MB and the
import runs in its own process, the crawler only scans text around `@`
signs, and send times are spread across the day.

## Project layout

```
ops_dashboard.py             Dashboard server and JSON API
Open Ops Dashboard.command   Mac launcher: opens the server's dashboard, or runs it locally
monthly_agent.py             Monthly client report: data collection, email, send
send_log.py                  Append-only log of client report sends
bot/                         Outreach sender: Gmail API, schedule, opt-out/bounce scanner
leadfinder/                  Overture import, website crawler, lead store, email template
dashboard/                   Dashboard pages (HTML/CSS/JS)
data/                        Client list, credentials, databases (gitignored)
config.yaml                  Bot volume, send window and safety limits
.env.example                 Every setting that holds credentials or personal details
```

## Agency outreach

The **Agency Finder** tab (`/agencies`) finds web design and SEO agencies on
Google Maps with the free [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper)
Docker image, and pitches them the Lead Finder.

1. *Search:* each search is "<term> in <city>, <ST>" (terms like "web design
   agency", "SEO company"; a few big cities per state, or the whole country).
   Searches run 8 per container and are never repeated.
2. *Qualify:* only agency-type Google categories; the email comes from the
   profile, or failing that from the Lead Finder's site crawler. Published
   emails only, own domain or a personal mailbox, MX checked, deduped against
   every agency, Lead Finder business, past send and block.
3. *Send:* `bot.run_daily` sends 150 client emails (Lead Finder + realtor list)
   and 150 agency emails a day, alternating one and one. Over 9am-9pm that's
   an email about every 2.4 minutes, each list about every 5. A shortfall in
   one list never raises the other's cap. Both share the opt-out scan, bounce
   pause, block list and send history.

**Where it runs.** The server (1 GB) only sends. Searches run on the Mac:
`launchd` job `com.theraweb.agencysync` runs `python3 -m agencyfinder.sync`
every 10 minutes (and at login or wake). It asks the server how many agencies are
queued, searches 8 at a time until 300 are waiting (`per_day` x `queue_days`: today's
150 plus 150 saved for tomorrow), and pushes
each new ready agency to the server once over `gcloud compute ssh`
(`AGENCY_SERVER_*` in `.env`). The server re-checks every row against its own
send history and blocks on import. Docker Desktop must be running on the Mac.

Agency sending is off until you turn it on in the tab. Data lives in
`data/agencies.db` and `data/agencyfinder.json`. The scraper needs Docker on
the machine that runs it (`DOCKER_BIN` in `.env` if docker isn't on the PATH).

```bash
python3 -m agencyfinder.run scrape --searches 16   # run the next 16 searches
python3 -m agencyfinder.run nightly                # refill if below the queue target
python3 -m agencyfinder.run status
python3 -m agencyfinder.run preview --limit 3
python3 -m bot.nightly                             # both finders, one after the other
python3 -m unittest discover -s tests -v
```

The nightly cron runs `python3 -m bot.nightly` (marker `theraweb-leadfinder`),
which runs each enabled finder in its own process so DuckDB and Chromium
never hold memory at the same time.

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                       # API keys, Gmail, sender identity
cp clients.example.json data/clients.json  # your clients

python3 ops_dashboard.py                   # dashboard at http://127.0.0.1:8787
python3 -m leadfinder.run import --states FL
python3 -m leadfinder.run crawl --limit 500
python3 -m bot.run_daily --dry-run         # plan a send without sending
```

Then schedule `bot.run_daily` and `leadfinder.run nightly` with cron (the
Lead Finder settings page can install the nightly job), and run
`ops_dashboard.py` as a service.

On a Mac, double-click `Open Ops Dashboard.command`. If `DASHBOARD_REMOTE`
in `.env` points at a reachable server (e.g. over Tailscale) it opens that
dashboard with `--remote`; otherwise it starts one locally.

## Configuration and privacy

Credentials and personal details are never in the code. `.env` holds API
keys, the Gmail address, the ntfy topic for phone alerts, and the sender
identity shown in emails (`SENDER_NAME`, `SENDER_EMAIL`, `SENDER_PHONE`,
`BUSINESS_WEBSITE`, `BUSINESS_POSTAL_ADDRESS`). `data/` holds client data,
the Gmail token and the databases. Both are gitignored.
