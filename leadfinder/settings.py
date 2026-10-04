"""Lead Finder settings, editable from the dashboard.

Kept in data/leadfinder.json rather than config.yaml so the dashboard can
rewrite it without clobbering the comments in config.yaml.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "data" / "leadfinder.json"
LEADS_DB_PATH = ROOT / "data" / "leads.db"
STATUS_PATH = ROOT / "data" / "leadfinder_status.json"
LOG_DIR = ROOT / "logs"

DEFAULTS = {
    # Sending. Off until Jake turns it on from the dashboard.
    "send_enabled": False,
    # How many of the bot's daily slots go to approved business leads.
    # The realtor list fills whatever is left of daily_target.
    "per_day": 100,
    # Where and what to import from Overture.
    "states": ["FL"],
    "categories": ["home_services", "beauty", "fitness", "health", "auto", "pets", "pro_services"],
    "min_confidence": 0.5,
    "release": "auto",
    # Nightly website check.
    "nightly_enabled": False,
    "nightly_limit": 1000,
    "nightly_hour": 1,
    # Skip leads whose site looks modern and healthy (no hook to open with).
    "skip_healthy_sites": False,
    # Pause ALL sending if hard bounces over the last 3 send days exceed this.
    "max_bounce_rate": 0.03,
}


def load() -> dict:
    data = {}
    if SETTINGS_PATH.is_file():
        try:
            data = json.loads(SETTINGS_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    out = dict(DEFAULTS)
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
    """Progress file the dashboard polls while an import or crawl runs."""
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
