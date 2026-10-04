"""Lead database (data/leads.db).

Lifecycle of a lead:

  new        imported from Overture, website not checked yet
  ready      published email found and its domain accepts mail; waiting for review
  approved   Jake approved it; the daily bot will send to it
  sent       the bot emailed it (one touch only, never repeated)
  rejected   Jake rejected it
  no_email   site checked, no published email anywhere
  dead       site would not load and there is no email on file
  bad_email  the email's domain can't receive mail
  duplicate  same email or same website as a lead we already have
  skipped    healthy site and skip_healthy_sites is on, or robots.txt said no
  blocked    address is on the outreach bot's block list (opt-out / bounce)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .settings import LEADS_DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    overture_id   TEXT UNIQUE,
    name          TEXT NOT NULL,
    category      TEXT,
    website       TEXT,
    domain        TEXT,
    phone         TEXT,
    email         TEXT,
    email_source  TEXT,
    street        TEXT,
    city          TEXT,
    state         TEXT,
    postcode      TEXT,
    socials       TEXT,
    platform      TEXT,
    issues        TEXT,
    copyright_year INTEGER,
    status        TEXT NOT NULL DEFAULT 'new',
    status_detail TEXT,
    release       TEXT,
    imported_at   TEXT NOT NULL,
    checked_at    TEXT,
    approved_at   TEXT,
    sent_at       TEXT,
    message_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain);
CREATE INDEX IF NOT EXISTS idx_leads_email  ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_state  ON leads(state);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS daily (
    day      TEXT PRIMARY KEY,
    checked  INTEGER NOT NULL DEFAULT 0,
    found    INTEGER NOT NULL DEFAULT 0
);
"""

STATUSES = ["new", "ready", "approved", "sent", "rejected", "no_email", "dead",
            "bad_email", "duplicate", "skipped", "blocked"]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class LeadStore:
    def __init__(self, path: str | Path = LEADS_DB_PATH, readonly: bool = False):
        self.path = Path(path)
        if readonly:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
            self.conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    # ---------- meta ----------

    def get_meta(self, key, default=None):
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_meta(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, str(value)))
        self.conn.commit()

    # ---------- import ----------

    def insert_many(self, rows: list[dict], release: str) -> tuple[int, int]:
        """Insert imported places. Returns (added, skipped_as_duplicates).

        Dedup on Overture id, and on website domain: a franchise with 40
        locations sharing one site is one lead, not 40.
        """
        known_domains = {r[0] for r in self.conn.execute(
            "SELECT domain FROM leads WHERE domain IS NOT NULL")}
        known_emails = {r[0] for r in self.conn.execute(
            "SELECT email FROM leads WHERE email IS NOT NULL")}
        added = dup = 0
        ts = now()
        for r in rows:
            dom = r.get("domain")
            em = r.get("email")
            if (dom and dom in known_domains) or (em and em in known_emails):
                dup += 1
                continue
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO leads (overture_id, name, category, website, domain,"
                " phone, email, email_source, street, city, state, postcode, socials,"
                " release, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["overture_id"], r["name"], r.get("category"), r.get("website"), dom,
                 r.get("phone"), em, "overture" if em else None, r.get("street"),
                 r.get("city"), r.get("state"), r.get("postcode"),
                 json.dumps(r.get("socials") or []), release, ts))
            if cur.rowcount:
                added += 1
                if dom:
                    known_domains.add(dom)
                if em:
                    known_emails.add(em)
            else:
                dup += 1
        self.conn.commit()
        return added, dup

    # ---------- crawl ----------

    def next_to_check(self, limit: int, states: list[str] | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM leads WHERE status='new'"
        args: list = []
        if states:
            q += f" AND state IN ({','.join('?' * len(states))})"
            args += states
        # Random order so one night isn't all one city or one category.
        q += " ORDER BY random() LIMIT ?"
        args.append(limit)
        return list(self.conn.execute(q, args))

    def email_taken(self, email: str, exclude_id: int) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM leads WHERE email=? AND id<>? AND status NOT IN ('new','no_email','dead')",
            (email, exclude_id)).fetchone() is not None

    def save_check(self, lead_id: int, *, status: str, detail: str | None = None,
                   email: str | None = None, email_source: str | None = None,
                   platform: str | None = None, issues: list[str] | None = None,
                   copyright_year: int | None = None):
        self.conn.execute(
            "UPDATE leads SET status=?, status_detail=?, email=COALESCE(?, email),"
            " email_source=COALESCE(?, email_source), platform=?, issues=?,"
            " copyright_year=?, checked_at=? WHERE id=?",
            (status, detail, email, email_source, platform, json.dumps(issues or []),
             copyright_year, now(), lead_id))
        self.conn.commit()

    def bump_daily(self, checked=0, found=0):
        day = datetime.now().date().isoformat()
        self.conn.execute(
            "INSERT INTO daily (day, checked, found) VALUES (?,?,?) "
            "ON CONFLICT(day) DO UPDATE SET checked=checked+excluded.checked, found=found+excluded.found",
            (day, checked, found))
        self.conn.commit()

    # ---------- review ----------

    def set_status(self, ids: list[int], status: str, only_from: tuple[str, ...]) -> int:
        if not ids:
            return 0
        stamp_col = "approved_at" if status == "approved" else None
        q = f"UPDATE leads SET status=?{', approved_at=?' if stamp_col else ''} WHERE id IN ({','.join('?' * len(ids))})"
        q += f" AND status IN ({','.join('?' * len(only_from))})"
        args: list = [status] + ([now()] if stamp_col else []) + list(ids) + list(only_from)
        cur = self.conn.execute(q, args)
        self.conn.commit()
        return cur.rowcount

    def approve_next(self, n: int) -> int:
        ids = [r[0] for r in self.conn.execute(
            "SELECT id FROM leads WHERE status='ready' ORDER BY checked_at LIMIT ?", (n,))]
        return self.set_status(ids, "approved", ("ready",))

    # ---------- sending ----------

    def approved_batch(self, n: int, blocked_emails: set[str],
                       include_ready: bool = False) -> list[sqlite3.Row]:
        # include_ready = auto-approve: hand-approved leads first, then the
        # oldest ready ones.
        where = "status IN ('approved','ready')" if include_ready else "status='approved'"
        out = []
        for r in self.conn.execute(
                f"SELECT * FROM leads WHERE {where}"
                " ORDER BY status='approved' DESC, approved_at, checked_at, id"):
            if r["email"] in blocked_emails:
                self.conn.execute("UPDATE leads SET status='blocked' WHERE id=?", (r["id"],))
                continue
            out.append(r)
            if len(out) >= n:
                break
        self.conn.commit()
        return out

    def mark_sent(self, lead_id: int, message_id: str | None):
        self.conn.execute(
            "UPDATE leads SET status='sent', sent_at=?, message_id=? WHERE id=?",
            (now(), message_id, lead_id))
        self.conn.commit()

    # ---------- reporting ----------

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in STATUSES}
        for r in self.conn.execute("SELECT status, COUNT(*) n FROM leads GROUP BY status"):
            out[r["status"]] = r["n"]
        out["total"] = sum(out[s] for s in STATUSES)
        return out

    def counts_by_state(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT state, COUNT(*) total, SUM(status='new') unchecked,"
            " SUM(status IN ('ready','approved','sent')) with_email"
            " FROM leads GROUP BY state ORDER BY total DESC")]

    def daily_rows(self, days=14) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM daily ORDER BY day DESC LIMIT ?", (days,))]

    def list(self, status: str, limit=100, offset=0, search: str | None = None) -> tuple[list[dict], int]:
        where = "status=?"
        args: list = [status]
        if search:
            where += " AND (name LIKE ? OR email LIKE ? OR city LIKE ? OR category LIKE ? OR domain LIKE ?)"
            like = f"%{search}%"
            args += [like] * 5
        total = self.conn.execute(f"SELECT COUNT(*) FROM leads WHERE {where}", args).fetchone()[0]
        order = {"sent": "sent_at DESC", "approved": "approved_at, id",
                 "new": "id"}.get(status, "checked_at DESC")
        rows = self.conn.execute(
            f"SELECT * FROM leads WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [limit, offset])
        return [row_to_dict(r) for r in rows], total

    def get(self, lead_id: int):
        return self.conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()


def row_to_dict(r) -> dict:
    d = dict(r)
    for k in ("issues", "socials"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except (TypeError, json.JSONDecodeError):
            d[k] = []
    return d
