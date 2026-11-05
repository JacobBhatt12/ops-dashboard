"""Agency Finder settings, editable from the dashboard (data/agencyfinder.json)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "data" / "agencyfinder.json"
DB_PATH = ROOT / "data" / "agencies.db"
STATUS_PATH = ROOT / "data" / "agencyfinder_status.json"
WORK_DIR = ROOT / "data" / "agencyfinder"
LOG_DIR = ROOT / "logs"

DEFAULT_TERMS = [
    "web design agency",
    "web designer",
    "website developer",
    "SEO agency",
    "SEO company",
    "digital marketing agency",
]

DEFAULTS = {
    # Off until Jake previews the email and turns it on.
    "send_enabled": False,
    # Agency emails per day. Sent alternating with the client stream.
    "per_day": 150,
    # Send "ready" agencies without a manual approve click.
    "auto_approve": False,
    # Empty list = the whole country.
    "states": [],
    "search_terms": DEFAULT_TERMS,
    # Google Maps scroll depth per search (more = more results, slower).
    "depth": 3,
    # Browser concurrency inside the scraper container.
    "concurrency": 2,
    # Nightly scrape.
    # Runs inside the shared nightly job (bot.nightly) at the Lead Finder hour.
    "nightly_enabled": False,
    "searches_per_night": 40,
    # The nightly run stops once this many agencies are queued to send.
    "nightly_target_ready": 300,
}


def load() -> dict:
    data = {}
    if SETTINGS_PATH.is_file():
        try:
            data = json.loads(SETTINGS_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    out = json.loads(json.dumps(DEFAULTS))
    out.update({k: v for k, v in data.items() if k in DEFAULTS})
    return out


def save(changes: dict) -> dict:
    current = load()
    for k, v in changes.items():
        if k in DEFAULTS:
            current[k] = v
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(current, indent=2))
    return current


def write_status(**fields) -> None:
    try:
        cur = json.loads(STATUS_PATH.read_text()) if STATUS_PATH.is_file() else {}
    except (OSError, json.JSONDecodeError):
        cur = {}
    cur.update(fields)
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur))
    tmp.replace(STATUS_PATH)


def read_status() -> dict:
    try:
        return json.loads(STATUS_PATH.read_text()) if STATUS_PATH.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}
