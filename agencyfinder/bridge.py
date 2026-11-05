"""Hands approved agencies to the outreach bot (bot/run_daily.py) as
contact-like objects, so they go through the same Gmail sender, schedule,
opt-out/bounce scanner, block list and send history as everything else."""
from __future__ import annotations

from leadfinder.template import clean_business_name

from . import settings as S
from .store import AgencyStore
from .template import render_agency, self_check


class AgencyContact:
    template = "agency"

    def __init__(self, row):
        self.agency = dict(row)
        self.agency_id = row["id"]
        self.email = row["email"].strip().lower()
        self.person_key = self.email          # one agency, one touch
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
        return render_agency(self.agency)


def take_agencies(store, n: int, include_ready: bool = False):
    """Up to n approved (or, with include_ready, ready) agencies safe to email today."""
    if n <= 0 or not S.DB_PATH.is_file():
        return [], None
    self_check()
    st = AgencyStore()
    blocked = store.blocked_emails()
    sent_before = {r[0] for r in store.conn.execute("SELECT DISTINCT email FROM sends")}
    return [AgencyContact(r) for r in st.batch(n, blocked, sent_before, include_ready)], st
