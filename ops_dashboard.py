#!/usr/bin/env python3
"""ops-dashboard: local dashboard for selecting and sending client reports."""

import argparse
import calendar
import concurrent.futures
import json
import mimetypes
import os
import sqlite3
import subprocess
import threading
import time
import webbrowser
from collections import Counter
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import webview
except ImportError:
    webview = None

from monthly_agent import CLIENTS, get_github_status, get_site_issues, list_recipients, run_agent
import bot.status_json as outreach_status_json
from bot.config import Config as OutreachConfig
from send_log import daily_counts as report_daily_counts, sends_on as report_sends_on
import leadfinder.api as leads_api


PROJECT_DIR = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_DIR / "dashboard"
ASSETS_DIR = PROJECT_DIR / "assets"
DATA_DIR = PROJECT_DIR / "data"
SEND_LOCK = threading.Lock()

# ── Customers (static snapshot, editable by replacing the JSON file) ──
CUSTOMERS_PATH = DATA_DIR / "customers.json"


def load_customers():
    if not CUSTOMERS_PATH.is_file():
        return []
    try:
        return json.loads(CUSTOMERS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return []


# ── Web3Forms keys (PIN-gated — never sent to the browser unprompted) ──
WEB3FORMS_KEYS_PATH = DATA_DIR / "web3forms_keys.json"
_web3forms_attempts_lock = threading.Lock()
_web3forms_attempts = []  # timestamps of recent wrong-PIN attempts, for basic throttling
WEB3FORMS_MAX_ATTEMPTS = 5
WEB3FORMS_ATTEMPT_WINDOW = 60  # seconds


def check_web3forms_pin(pin):
    """Very basic local throttle: five wrong guesses a minute, then locked out
    for the rest of the window. This is a soft, local-only gate — not real
    authentication — proportional to a private 127.0.0.1 dashboard."""
    with _web3forms_attempts_lock:
        now = time.time()
        recent = [t for t in _web3forms_attempts if now - t < WEB3FORMS_ATTEMPT_WINDOW]
        _web3forms_attempts[:] = recent
        if len(recent) >= WEB3FORMS_MAX_ATTEMPTS:
            return None  # locked out

        if not WEB3FORMS_KEYS_PATH.is_file():
            return False
        try:
            stored = json.loads(WEB3FORMS_KEYS_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            return False

        if pin != stored.get("pin"):
            _web3forms_attempts.append(now)
            return False
        return stored.get("entries", [])

# ── Cold outreach bot status (read-only — now the same project/venv) ──
OUTREACH_LAUNCHD_LABEL = "com.nimble.emailsender"
OUTREACH_STATUS_CACHE_TTL = 30  # seconds
_outreach_status_lock = threading.Lock()
_outreach_status_cache = {"timestamp": 0.0, "data": None}


def _outreach_cron_state():
    """Fallback for hosts with no launchd (e.g. this dashboard running on a
    Linux server) — the weekday outreach run is scheduled via a plain cron
    entry there instead. Report "loaded" if a matching line is present, so
    the dashboard doesn't falsely warn that nothing is scheduled."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except FileNotFoundError:
        result = None
    if result is not None and result.returncode == 0:
        for line in result.stdout.splitlines():
            line = line.strip()
            if "bot.run_daily" in line and not line.startswith("#"):
                return {
                    "loaded": True,
                    "program_path": "cron entry (bot.run_daily)",
                    "program_exists": True,
                    "last_exit_status": None,
                }
    return {"loaded": False, "program_path": None, "program_exists": False, "last_exit_status": None}


def _outreach_launchd_state():
    """Whether the weekday 8 AM job is loaded, and whether its Program path
    actually exists (catches a stale plist left behind by a moved project).
    launchd/launchctl is macOS-only — on any other OS (e.g. this dashboard
    running on a Linux server, scheduled via cron instead) there is no such
    job to query, so this falls back to checking cron rather than raising."""
    try:
        result = subprocess.run(
            ["launchctl", "list", OUTREACH_LAUNCHD_LABEL],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return _outreach_cron_state()
    if result.returncode != 0:
        return {"loaded": False, "program_path": None, "program_exists": False, "last_exit_status": None}

    program_path = None
    last_exit_status = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith('"Program"'):
            program_path = line.split("=", 1)[1].strip().strip('";')
        elif line.startswith('"LastExitStatus"'):
            try:
                last_exit_status = int(line.split("=", 1)[1].strip().strip(";"))
            except ValueError:
                pass

    return {
        "loaded": True,
        "program_path": program_path,
        "program_exists": bool(program_path) and Path(program_path).is_file(),
        "last_exit_status": last_exit_status,
    }


def get_outreach_status_cached():
    with _outreach_status_lock:
        now = time.time()
        cached = _outreach_status_cache["data"]
        if cached is not None and now - _outreach_status_cache["timestamp"] < OUTREACH_STATUS_CACHE_TTL:
            return cached

        launchd = _outreach_launchd_state()
        try:
            data = outreach_status_json.build_status()
            data["available"] = True
            data["launchd"] = launchd
        except Exception as error:
            data = {"available": False, "error": str(error), "launchd": launchd}

        _outreach_status_cache["data"] = data
        _outreach_status_cache["timestamp"] = now
        return data

# ── Emails sent today / recent send activity ──────────────────────
# Merges two sources at read time: the monthly agent's own append-only log
# (data/send_log.jsonl, written by send_log.record_send) and the outreach
# bot's SQLite `sends` table (data/outreach.db, opened read-only). "Today"
# is the local calendar date, so the panel naturally resets at midnight.
OUTREACH_SUBJECT = "Your branded website"
LEADFINDER_SUBJECT = "quick question about your website"


def _outreach_db():
    path = OutreachConfig.load().path("state_db")
    if not path.is_file():
        return None
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def outreach_sends_on(day):
    try:
        db = _outreach_db()
    except Exception:
        return []
    if db is None:
        return []
    try:
        rows = db.execute(
            "SELECT email, first_name, last_name, company, sent_at, source, template "
            "FROM sends WHERE sent_on = ? ORDER BY sent_at",
            (day.isoformat(),),
        )
        return [
            {
                "sent_at": r["sent_at"],
                "kind": "outreach",
                "to_email": r["email"],
                "to_name": " ".join(p for p in (r["first_name"], r["last_name"]) if p) or r["email"],
                "client": r["company"] or "",
                "subject": LEADFINDER_SUBJECT if r["template"] == "business" else OUTREACH_SUBJECT,
                "status": "sent",
                "source": r["source"],
                "error": None,
            }
            for r in rows
        ]
    finally:
        db.close()


def outreach_daily_counts(days):
    try:
        db = _outreach_db()
    except Exception:
        return {}
    if db is None:
        return {}
    try:
        start = (date.today() - timedelta(days=days - 1)).isoformat()
        return {
            r["sent_on"]: r["n"]
            for r in db.execute(
                "SELECT sent_on, COUNT(*) n FROM sends WHERE sent_on >= ? GROUP BY sent_on",
                (start,),
            )
        }
    finally:
        db.close()


def get_sent_today():
    today = date.today()
    entries = report_sends_on(today) + outreach_sends_on(today)
    entries.sort(key=lambda e: e.get("sent_at", ""), reverse=True)

    sent = [e for e in entries if e.get("status") == "sent"]
    by_client = Counter(
        e["client"] if e["kind"] == "report" and e["client"] else "Cold outreach"
        for e in sent
    )
    return {
        "date": today.isoformat(),
        "sends": entries,
        "counts": {
            "total": len(sent),
            "reports": sum(1 for e in sent if e["kind"] == "report"),
            "outreach": sum(1 for e in sent if e["kind"] == "outreach"),
            "failed": sum(1 for e in entries if e.get("status") == "failed"),
        },
        "by_client": [
            {"label": label, "count": count, "kind": "outreach" if label == "Cold outreach" else "report"}
            for label, count in by_client.most_common()
        ],
    }


def get_send_activity(days=14):
    days = max(2, min(int(days), 90))
    reports = report_daily_counts(days)
    outreach = outreach_daily_counts(days)
    today = date.today()
    series = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        series.append({
            "date": day,
            "reports": reports.get(day, {}).get("sent", 0),
            "failed": reports.get(day, {}).get("failed", 0),
            "outreach": outreach.get(day, 0),
        })
    return {"days": series}


# ── Automatic monthly send (launchd) ─────────────────────────────
SCHEDULE_CONFIG_PATH = PROJECT_DIR / "schedule_config.json"
SCHEDULED_SEND_SCRIPT = PROJECT_DIR / "scheduled_send.sh"
SCHEDULE_LOG_PATH = PROJECT_DIR / "schedule_log.txt"
LAUNCH_AGENT_LABEL = "com.theraweb.monthlyagent"
LAUNCH_AGENT_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def _default_schedule():
    return {"enabled": False, "day": 15, "hour": 10, "minute": 0}


def load_schedule():
    if SCHEDULE_CONFIG_PATH.is_file():
        try:
            data = json.loads(SCHEDULE_CONFIG_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    else:
        data = {}

    schedule = _default_schedule()
    schedule.update({k: data[k] for k in schedule if k in data})
    return schedule


def _next_run_iso(day, hour, minute):
    """The next local datetime this schedule will fire, as an ISO string."""
    now = datetime.now()
    month_cursor = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _ in range(13):
        last_day_of_month = calendar.monthrange(month_cursor.year, month_cursor.month)[1]
        run_day = min(day, last_day_of_month)
        candidate = month_cursor.replace(day=run_day, hour=hour, minute=minute)
        if candidate > now:
            return candidate.isoformat()
        if month_cursor.month == 12:
            month_cursor = month_cursor.replace(year=month_cursor.year + 1, month=1)
        else:
            month_cursor = month_cursor.replace(month=month_cursor.month + 1)
    return None


def _write_launch_agent_plist(day, hour, minute):
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>Label</key>
\t<string>{LAUNCH_AGENT_LABEL}</string>
\t<key>ProgramArguments</key>
\t<array>
\t\t<string>/bin/bash</string>
\t\t<string>{SCHEDULED_SEND_SCRIPT}</string>
\t</array>
\t<key>StartCalendarInterval</key>
\t<dict>
\t\t<key>Day</key>
\t\t<integer>{day}</integer>
\t\t<key>Hour</key>
\t\t<integer>{hour}</integer>
\t\t<key>Minute</key>
\t\t<integer>{minute}</integer>
\t</dict>
\t<key>StandardOutPath</key>
\t<string>{SCHEDULE_LOG_PATH}</string>
\t<key>StandardErrorPath</key>
\t<string>{SCHEDULE_LOG_PATH}</string>
\t<key>RunAtLoad</key>
\t<false/>
</dict>
</plist>
"""
    LAUNCH_AGENT_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT_PLIST_PATH.write_text(plist)


def _launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def apply_schedule(enabled, day, hour, minute):
    """(Re)install or remove the launchd job so it matches the requested schedule."""
    uid = os.getuid()

    # Unload any previously-scheduled job first — launchd does not pick up
    # in-place edits to a plist it already loaded.
    _launchctl("bootout", f"gui/{uid}/{LAUNCH_AGENT_LABEL}")

    if not enabled:
        if LAUNCH_AGENT_PLIST_PATH.is_file():
            LAUNCH_AGENT_PLIST_PATH.unlink()
        return

    _write_launch_agent_plist(day, hour, minute)
    result = _launchctl("bootstrap", f"gui/{uid}", str(LAUNCH_AGENT_PLIST_PATH))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "launchctl failed to schedule the job")


def save_schedule(enabled, day, hour, minute):
    schedule = {"enabled": enabled, "day": day, "hour": hour, "minute": minute}
    apply_schedule(**schedule)
    SCHEDULE_CONFIG_PATH.write_text(json.dumps(schedule, indent=2))
    return schedule


# ── GitHub deployment/Dependabot status (cached — real API calls) ──
GITHUB_STATUS_CACHE_TTL = 300  # seconds
_github_status_lock = threading.Lock()
_github_status_cache = {"timestamp": 0.0, "data": None}


def get_github_status_cached():
    with _github_status_lock:
        now = time.time()
        cached = _github_status_cache["data"]
        if cached is not None and now - _github_status_cache["timestamp"] < GITHUB_STATUS_CACHE_TTL:
            return cached

        data = {client["name"]: get_github_status(client) for client in CLIENTS}
        _github_status_cache["data"] = data
        _github_status_cache["timestamp"] = now
        return data


# ── Site errors: SSL / uptime / PageSpeed ──────────────────────────
# PageSpeed audits are genuinely slow (real Lighthouse runs, ~15-60s each),
# so this never runs automatically on page load — only an explicit
# "Check for errors" click (POST /api/site-issues/check) triggers a live
# run. GET /api/site-issues is instant: it only ever reads whatever is
# already cached, so opening the page never blocks on a live check.
_site_issues_lock = threading.Lock()
_site_issues_cache = {"timestamp": None, "data": None}
SITE_ISSUES_CHECK_LOCK = threading.Lock()


def get_site_issues_snapshot():
    """Instant, non-blocking: whatever was last checked, or nothing yet."""
    with _site_issues_lock:
        ts = _site_issues_cache["timestamp"]
        return {
            "clients": _site_issues_cache["data"] or {},
            "checked_at": datetime.fromtimestamp(ts).isoformat() if ts else None,
        }


def run_site_issues_check():
    """Blocking: run a fresh live check against every client site and cache it."""
    def check(client):
        return client["name"], get_site_issues(client["website"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(len(CLIENTS), 1)) as pool:
        data = dict(pool.map(check, CLIENTS))

    with _site_issues_lock:
        _site_issues_cache["data"] = data
        _site_issues_cache["timestamp"] = time.time()

    return get_site_issues_snapshot()


class ManagementHandler(BaseHTTPRequestHandler):
    server_version = "TheraManagement/1.0"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/recipients":
            self._send_json({"recipients": list_recipients()})
            return

        if path == "/api/schedule":
            schedule = load_schedule()
            next_run = (
                _next_run_iso(schedule["day"], schedule["hour"], schedule["minute"])
                if schedule["enabled"]
                else None
            )
            self._send_json({**schedule, "next_run": next_run})
            return

        if path == "/api/github-status":
            self._send_json({"clients": get_github_status_cached()})
            return

        if path == "/api/site-issues":
            self._send_json(get_site_issues_snapshot())
            return

        if path == "/api/outreach-status":
            self._send_json(get_outreach_status_cached())
            return

        if path == "/api/customers":
            self._send_json({"customers": load_customers()})
            return

        if path.startswith("/api/leads/"):
            self._handle_leads_get(path)
            return

        if path == "/api/sent-today":
            self._send_json(get_sent_today())
            return

        if path == "/api/send-activity":
            query = parse_qs(urlparse(self.path).query)
            try:
                days = int(query.get("days", ["14"])[0])
            except ValueError:
                days = 14
            self._send_json(get_send_activity(days))
            return

        page_routes = {
            "/": "index.html",
            "/outreach": "outreach.html",
            "/errors": "errors.html",
            "/customers": "customers.html",
            "/keys": "keys.html",
            "/leads": "leads.html",
        }
        if path == "/assets/tw-logo.png":
            file_path = ASSETS_DIR / "tw-logo.png"
        elif path in page_routes:
            file_path = STATIC_DIR / page_routes[path]
        else:
            # Anything else is served straight from dashboard/ — but only from
            # inside it (resolve() defeats "../" tricks).
            candidate = (STATIC_DIR / path.lstrip("/")).resolve()
            file_path = candidate if STATIC_DIR.resolve() in candidate.parents else None
        if not file_path or not file_path.is_file():
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        content = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/send":
            self._handle_send()
        elif path == "/api/schedule":
            self._handle_schedule()
        elif path == "/api/web3forms-keys/unlock":
            self._handle_web3forms_unlock()
        elif path == "/api/site-issues/check":
            self._handle_site_issues_check()
        elif path.startswith("/api/leads/"):
            self._handle_leads_post(path)
        else:
            self.send_error(404)

    # ── Lead Finder ──────────────────────────────────────────────
    def _handle_leads_get(self, path):
        query = parse_qs(urlparse(self.path).query)

        def q(name, default=None):
            return query.get(name, [default])[0]

        try:
            if path == "/api/leads/summary":
                self._send_json(leads_api.summary())
            elif path == "/api/leads/list":
                self._send_json(leads_api.list_leads(
                    q("status", "ready"), int(q("limit", "50")), int(q("offset", "0")), q("q")))
            elif path == "/api/leads/preview":
                self._send_json(leads_api.preview(int(q("id", "0"))))
            else:
                self.send_error(404)
        except ValueError as error:
            self._send_json({"error": str(error)}, status=400)
        except Exception as error:
            self._send_json({"error": f"Lead Finder error: {error}"}, status=500)

    def _handle_leads_post(self, path):
        try:
            payload = self._read_json_body()
            if path == "/api/leads/review":
                result = leads_api.review(payload)
            elif path == "/api/leads/settings":
                result = {"settings": leads_api.update_settings(payload)}
            elif path == "/api/leads/job":
                result = leads_api.start_job(payload)
            else:
                self.send_error(404)
                return
            self._send_json(result)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
        except RuntimeError as error:
            self._send_json({"error": str(error)}, status=409)
        except Exception as error:
            self._send_json({"error": f"Lead Finder error: {error}"}, status=500)

    def _handle_site_issues_check(self):
        if not SITE_ISSUES_CHECK_LOCK.acquire(blocking=False):
            self._send_json({"error": "A check is already running"}, status=409)
            return
        try:
            self._send_json(run_site_issues_check())
        except Exception as error:
            self._send_json({"error": f"Check failed: {error}"}, status=500)
        finally:
            SITE_ISSUES_CHECK_LOCK.release()

    def _handle_web3forms_unlock(self):
        try:
            payload = self._read_json_body()
            pin = payload.get("pin")
            if not isinstance(pin, str):
                raise ValueError("Enter the PIN")
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
            return

        result = check_web3forms_pin(pin)
        if result is None:
            self._send_json({"error": "Too many wrong attempts. Wait a minute and try again."}, status=429)
            return
        if result is False:
            self._send_json({"error": "Wrong PIN"}, status=403)
            return
        self._send_json({"entries": result})

    def _read_json_body(self, max_length=65_536):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > max_length:
            raise ValueError("Invalid request size")
        return json.loads(self.rfile.read(length))

    def _handle_send(self):
        try:
            payload = self._read_json_body()
            selected_ids = payload.get("recipient_ids")
            if not isinstance(selected_ids, list) or not selected_ids:
                raise ValueError("Select at least one recipient")

            valid_ids = {recipient["id"] for recipient in list_recipients()}
            if any(not isinstance(item, str) or item not in valid_ids for item in selected_ids):
                raise ValueError("The recipient selection is invalid")
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
            return

        if not SEND_LOCK.acquire(blocking=False):
            self._send_json({"error": "Another email send is already in progress"}, status=409)
            return

        try:
            results = run_agent(selected_recipient_ids=selected_ids)
            self._send_json(results)
        except Exception as error:
            self._send_json({"error": f"Email send failed: {error}"}, status=500)
        finally:
            SEND_LOCK.release()

    def _handle_schedule(self):
        try:
            payload = self._read_json_body()
            enabled = payload.get("enabled")
            day = payload.get("day")
            hour = payload.get("hour")
            minute = payload.get("minute")

            if not isinstance(enabled, bool):
                raise ValueError("enabled must be true or false")
            if not isinstance(day, int) or not (1 <= day <= 28):
                raise ValueError("Day must be between 1 and 28")
            if not isinstance(hour, int) or not (0 <= hour <= 23):
                raise ValueError("Hour must be between 0 and 23")
            if not isinstance(minute, int) or not (0 <= minute <= 59):
                raise ValueError("Minute must be between 0 and 59")
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
            return

        try:
            schedule = save_schedule(enabled, day, hour, minute)
            next_run = _next_run_iso(day, hour, minute) if enabled else None
            self._send_json({**schedule, "next_run": next_run})
        except Exception as error:
            self._send_json({"error": f"Could not update the schedule: {error}"}, status=500)

    def _send_json(self, payload, status=200):
        content = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format_string, *args):
        print(f"[dashboard] {self.address_string()} {format_string % args}")


def main():
    parser = argparse.ArgumentParser(description="Run the ops dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open in the default web browser instead of a native app window",
    )
    parser.add_argument(
        "--remote",
        default=None,
        metavar="URL",
        help=(
            "Don't start a local server at all — just open a native window "
            "(or browser tab, with --browser) pointed at an already-running "
            "dashboard at this URL, e.g. a server reachable over Tailscale."
        ),
    )
    args = parser.parse_args()

    if args.remote:
        dashboard_url = args.remote
        server = None
    else:
        server = ThreadingHTTPServer((args.host, args.port), ManagementHandler)
        dashboard_url = f"http://{args.host}:{args.port}"
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
    print(f"Ops dashboard: {dashboard_url}")

    use_browser = args.browser or webview is None
    if use_browser:
        if webview is None:
            print("pywebview is not installed; falling back to the default web browser.")
        webbrowser.open(dashboard_url)
        print("Press Control-C to stop it.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nDashboard stopped.")
    else:
        webview.create_window(
            "Thera Dashboard",
            dashboard_url,
            width=1200,
            height=850,
            min_size=(900, 650),
        )
        webview.start()

    if server is not None:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
