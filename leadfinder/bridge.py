"""Glue between the Lead Finder and the outreach bot (bot/run_daily.py).

The bot already owns sending: Gmail auth, the randomized schedule, the
opt-out and bounce scanner, the block list and the send history. Approved
leads are handed to it as contact-like objects so they travel through the
exact same safety rails as the realtor list.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import unquote

from . import settings as S
from .store import LeadStore
from .template import clean_business_name, render_lead
from .template import self_check as template_self_check


_VALID = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,24}$")


def clean_email(raw: str) -> str:
    """Strip junk sites wrap around addresses ("email:%20x@y.com", "http://x@y.com").
    Returns "" when what's left still isn't a plain address."""
    e = unquote(raw or "").strip().lower()
    e = re.sub(r"^(e-?mail|mailto|https?)\s*:\s*(//)?", "", e).strip(" /")
    return e if _VALID.match(e) else ""


class LeadContact:
    template = "business"

    def __init__(self, row):
        self.lead = dict(row)
        self.lead_id = row["id"]
        # Some sites publish "mailto:email:%20name@x.com"; keep only the address.
        self.email = clean_email(row["email"])
        self.person_key = self.email          # one business, one touch
        self.first_raw = None
        self.last = None
        self.company = row["name"]
        self.title = row["category"]
        self.city = row["city"]
        self.state = row["state"]
        self.warnings: list[str] = []
        name = clean_business_name(row["name"])
        self.greeting = f"Hey {name} team," if name else "Hey there,"

    @property
    def domain(self) -> str:
        return self.email.split("@")[-1].lower()

    def render(self):
        return render_lead(self.lead)


def bounce_guard(store, max_rate: float, min_sends: int = 100) -> tuple[bool, str]:
    """Pause sending when hard bounces over the last 3 send days are too high.

    Uses the outreach bot's own tables: `sends` for volume and `blocks`
    (source='bounce') for hard bounces the scanner caught. Returns
    (ok_to_send, explanation).
    """
    days = [r[0] for r in store.conn.execute(
        "SELECT DISTINCT sent_on FROM sends WHERE source='bot' ORDER BY sent_on DESC LIMIT 3")]
    if not days:
        return True, "no send history yet"
    since = min(days)
    sent = store.conn.execute(
        f"SELECT COUNT(*) FROM sends WHERE source='bot' AND sent_on IN ({','.join('?' * len(days))})",
        days).fetchone()[0]
    bounces = store.conn.execute(
        "SELECT COUNT(*) FROM blocks WHERE source='bounce' AND substr(added_at,1,10) >= ?",
        (since,)).fetchone()[0]
    if sent < min_sends:
        return True, f"{bounces} bounces on {sent} sends (too few sends to judge)"
    rate = bounces / sent
    msg = f"{bounces} hard bounces on {sent} sends since {since} ({rate:.1%})"
    return rate <= max_rate, msg


def take_leads(store, n: int, include_ready: bool = False) -> tuple[list[LeadContact], LeadStore | None]:
    """Up to n approved (or, with include_ready, ready) leads that are safe to email today."""
    if n <= 0 or not S.LEADS_DB_PATH.is_file():
        return [], None
    template_self_check()
    ls = LeadStore()
    blocked = store.blocked_emails()
    sent_before = {r[0] for r in store.conn.execute("SELECT DISTINCT email FROM sends")}
    rows = ls.approved_batch(n + 50, blocked, include_ready)
    out = []
    for r in rows:
        if not clean_email(r["email"]):
            ls.conn.execute("UPDATE leads SET status='bad_email', status_detail='not a valid address' WHERE id=?", (r["id"],))
            continue
        if r["email"] in sent_before or clean_email(r["email"]) in sent_before:
            ls.conn.execute("UPDATE leads SET status='duplicate', status_detail='already emailed' WHERE id=?", (r["id"],))
            continue
        out.append(LeadContact(r))
        if len(out) >= n:
            break
    ls.conn.commit()
    return out, ls
