"""Read-only JSON status snapshot, for external tools (e.g. the management
dashboard) to consume. Never sends anything or modifies state.

Usage: .venv/bin/python3 -m bot.status_json
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from bot.config import Config


def build_status() -> dict:
    cfg = Config.load()
    db = sqlite3.connect(f"file:{cfg.path('state_db')}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row

    today = date.today().isoformat()
    today_row = db.execute(
        "SELECT COUNT(*) n FROM sends WHERE sent_on = ?", (today,)
    ).fetchone()
    sent_today = today_row["n"] if today_row else 0
    daily_target = cfg["volume"]["daily_target"]
    from agencyfinder.settings import load as agency_settings
    agency = agency_settings()
    client_target = max(0, min(150, int(daily_target)))
    agency_target = max(0, min(150, int(agency["per_day"]))) if agency["send_enabled"] else 0
    agency_sent = db.execute("SELECT COUNT(*) FROM sends WHERE sent_on=? AND template='agency'",
                             (today,)).fetchone()[0]
    daily_target = client_target + agency_target

    bounce_counts = {
        r["d"]: r["n"]
        for r in db.execute(
            "SELECT substr(added_at, 1, 10) d, COUNT(*) n "
            "FROM blocks WHERE source = 'bounce' GROUP BY d"
        )
    }
    run_days = [
        {
            "date": r["sent_on"],
            "sent": r["n"],
            "by_bot": r["bot"] or 0,
            "errors": bounce_counts.get(r["sent_on"], 0),
        }
        for r in db.execute(
            "SELECT sent_on, COUNT(*) n, SUM(source='bot') bot "
            "FROM sends GROUP BY sent_on ORDER BY sent_on DESC LIMIT 10"
        )
    ]

    blocks_by_source = [
        {"source": r["source"], "count": r["n"]}
        for r in db.execute("SELECT source, COUNT(*) n FROM blocks GROUP BY source")
    ]

    all_blocks = [
        {"added_at": r["added_at"], "email": r["email"], "reason": r["reason"], "source": r["source"]}
        for r in db.execute(
            "SELECT added_at, email, reason, source FROM blocks ORDER BY added_at DESC"
        )
    ]
    recent_blocks = all_blocks[:8]

    lifetime_sends = db.execute("SELECT COUNT(*) FROM sends").fetchone()[0]
    lifetime_people = db.execute(
        "SELECT COUNT(DISTINCT person_key) FROM sends"
    ).fetchone()[0]
    db.close()

    return {
        "config": {
            "daily_target": daily_target,
            "min_gap_days": cfg["volume"]["min_gap_days"],
            "start_hour": cfg["schedule"]["start_hour"],
            "end_hour": cfg["schedule"]["end_hour"],
            "weekdays_only": cfg["schedule"]["weekdays_only"],
        },
        "today": {
            "date": today,
            "sent": sent_today,
            "target": daily_target,
            "remaining": max(daily_target - sent_today, 0),
        },
        "run_days": run_days,
        "campaigns": {
            "client": {"target": client_target, "sent": sent_today - agency_sent},
            "agency": {"target": agency_target, "sent": agency_sent},
        },
        "blocks_by_source": blocks_by_source,
        "recent_blocks": recent_blocks,
        "blocks": all_blocks,
        "lifetime": {"sends": lifetime_sends, "people": lifetime_people},
    }


if __name__ == "__main__":
    print(json.dumps(build_status()))
