"""Append-only log of every Website Care report email the monthly agent sends.

One JSON object per line in ``data/send_log.jsonl`` (gitignored with the rest
of ``data/``). Written by ``monthly_agent.run_agent`` for both dashboard sends
and the unattended launchd send, so the dashboard's "Sent today" panel sees
every email regardless of how it went out. Cold-outreach sends are NOT logged
here — the bot keeps its own record in ``data/outreach.db`` and the dashboard
merges the two at read time.

Logging must never break a send, so ``record_send`` swallows filesystem
errors and just prints a warning.
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "data" / "send_log.jsonl"
_LOCK = threading.Lock()


def record_send(*, kind, to_email, to_name, client, subject, status, error=None, when=None):
    """Append one send (or failed attempt) to the log and return the entry."""
    when = when or datetime.now()
    entry = {
        "sent_at": when.isoformat(timespec="seconds"),
        "sent_on": when.date().isoformat(),
        "kind": kind,                    # "report"
        "to_email": to_email,
        "to_name": to_name,
        "client": client,
        "subject": subject,
        "status": status,                # "sent" | "failed"
        "error": (error or "")[:300] or None,
    }
    try:
        with _LOCK:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        print(f"    ⚠️  Could not write send log: {exc}")
    return entry


def _iter_entries():
    if not LOG_PATH.is_file():
        return
    with LOG_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def sends_on(day: date) -> list[dict]:
    """Every logged entry for one local calendar day, oldest first."""
    key = day.isoformat()
    return [entry for entry in _iter_entries() if entry.get("sent_on") == key]


def daily_counts(days: int = 14) -> dict[str, dict]:
    """``{"YYYY-MM-DD": {"sent": n, "failed": n}}`` for the last ``days`` days."""
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    counts: dict[str, dict] = {}
    for entry in _iter_entries():
        day = entry.get("sent_on", "")
        if day < start:
            continue
        bucket = counts.setdefault(day, {"sent": 0, "failed": 0})
        bucket["failed" if entry.get("status") == "failed" else "sent"] += 1
    return counts
