"""Agency database (data/agencies.db).

Lifecycle of an agency:

  ready      has a usable email whose domain accepts mail; waiting for review
  approved   approved in the dashboard; the daily bot will send to it
  sent       the bot emailed it (one touch only, never repeated)
  rejected   rejected in the dashboard
  no_email   no usable email on Google or on their site
  bad_email  the email's domain can't receive mail
  duplicate  same email or website as an agency (or lead) we already have
  blocked    address is on the outreach bot's block list (opt-out / bounce)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from . import settings as S

SCHEMA = """
CREATE TABLE IF NOT EXISTS agencies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id      TEXT UNIQUE,
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
    rating        REAL,
    reviews       INTEGER,
    query         TEXT,
    status        TEXT NOT NULL,
    status_detail TEXT,
    found_at      TEXT NOT NULL,
    approved_at   TEXT,
    sent_at       TEXT,
    message_id    TEXT,
    exported_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_ag_status ON agencies(status);
CREATE INDEX IF NOT EXISTS idx_ag_email  ON agencies(email);
CREATE INDEX IF NOT EXISTS idx_ag_domain ON agencies(domain);

CREATE TABLE IF NOT EXISTS searches (
    query    TEXT PRIMARY KEY,
    state    TEXT,
    ran_at   TEXT NOT NULL,
    places   INTEGER NOT NULL DEFAULT 0,
    found    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily (
    day      TEXT PRIMARY KEY,
    searched INTEGER NOT NULL DEFAULT 0,
    found    INTEGER NOT NULL DEFAULT 0
);
"""

STATUSES = ["ready", "approved", "sent", "rejected", "no_email", "bad_email",
            "duplicate", "blocked"]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class AgencyStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or S.DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        # Stats tables from an earlier draft of this module had other
        # columns. They only hold counters, so rebuild them if they differ.
        for table, col in (("daily", "searched"), ("searches", "query")):
            cols = [r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")]
            if cols and col not in cols:
                self.conn.execute(f"DROP TABLE {table}")
        self.conn.executescript(SCHEMA)
        if "exported_at" not in [r[1] for r in self.conn.execute("PRAGMA table_info(agencies)")]:
            self.conn.execute("ALTER TABLE agencies ADD COLUMN exported_at TEXT")
        self.conn.commit()
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    # ---------- searches ----------

    def searched(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT query FROM searches")}

    def record_searches(self, pairs: list[tuple[str, str]], places: int, found: int):
        """Mark a batch of (query, state) searches as done, and add the batch
        totals to today's row. Results can't be tied back to one query."""
        ts = now()
        self.conn.executemany(
            "INSERT OR REPLACE INTO searches (query, state, ran_at, places, found) VALUES (?,?,?,0,0)",
            [(q, st, ts) for q, st in pairs])
        day = datetime.now().date().isoformat()
        self.conn.execute(
            "INSERT INTO daily (day, searched, found) VALUES (?,?,?) "
            "ON CONFLICT(day) DO UPDATE SET searched=searched+excluded.searched, found=found+excluded.found",
            (day, len(pairs), found))
        self.conn.commit()

    # ---------- insert ----------

    def known(self) -> tuple[set[str], set[str], set[str]]:
        ids = {r[0] for r in self.conn.execute("SELECT place_id FROM agencies")}
        emails = {r[0] for r in self.conn.execute("SELECT email FROM agencies WHERE email IS NOT NULL")}
        domains = {r[0] for r in self.conn.execute("SELECT domain FROM agencies WHERE domain IS NOT NULL")}
        return ids, emails, domains

    def insert(self, a: dict) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO agencies (place_id, name, category, website, domain, phone,"
            " email, email_source, street, city, state, rating, reviews, query, status,"
            " status_detail, found_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (a["place_id"], a["name"], a.get("category"), a.get("website"), a.get("domain"),
             a.get("phone"), a.get("email"), a.get("email_source"), a.get("street"),
             a.get("city"), a.get("state"), a.get("rating"), a.get("reviews"), a.get("query"),
             a["status"], a.get("status_detail"), now()))
        self.conn.commit()

    # ---------- Mac -> server hand-off ----------
    # Searches run on the Mac (Docker + Chromium need more memory than the
    # server has); the server only sends. The Mac pushes each ready agency
    # once, and the server re-checks it against its own history on import.

    EXPORT_FIELDS = ("place_id", "name", "category", "website", "domain", "phone", "email",
                     "email_source", "street", "city", "state", "rating", "reviews", "query")

    def unexported(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM agencies WHERE status='ready' AND exported_at IS NULL ORDER BY id")]

    def mark_exported(self, ids: list[int]):
        self.conn.executemany("UPDATE agencies SET exported_at=? WHERE id=?", [(now(), i) for i in ids])
        self.conn.commit()

    def import_rows(self, rows: list[dict], blocked: set[str], sent_before: set[str],
                    lead_domains: set[str]) -> dict:
        ids, emails, domains = self.known()
        out = {"added": 0, "skipped": 0}
        for r in rows:
            a = {k: r.get(k) for k in self.EXPORT_FIELDS}
            e = (a.get("email") or "").lower()
            if (not a["place_id"] or not e or a["place_id"] in ids or e in emails
                    or (a["domain"] and (a["domain"] in domains or a["domain"] in lead_domains))
                    or e in blocked or e in sent_before):
                out["skipped"] += 1
                continue
            a["status"] = "ready"
            self.insert(a)
            ids.add(a["place_id"]); emails.add(e)
            if a["domain"]:
                domains.add(a["domain"])
            out["added"] += 1
        return out

    def queued(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM agencies WHERE status IN ('ready','approved')").fetchone()[0]

    # ---------- review ----------

    def set_status(self, ids: list[int], status: str, only_from: tuple[str, ...]) -> int:
        if not ids:
            return 0
        stamp = ", approved_at=?" if status == "approved" else ""
        q = (f"UPDATE agencies SET status=?{stamp} WHERE id IN ({','.join('?' * len(ids))})"
             f" AND status IN ({','.join('?' * len(only_from))})")
        args = [status] + ([now()] if stamp else []) + list(ids) + list(only_from)
        cur = self.conn.execute(q, args)
        self.conn.commit()
        return cur.rowcount

    def approve_next(self, n: int) -> int:
        ids = [r[0] for r in self.conn.execute(
            "SELECT id FROM agencies WHERE status='ready' ORDER BY found_at, id LIMIT ?", (n,))]
        return self.set_status(ids, "approved", ("ready",))

    # ---------- sending ----------

    def batch(self, n: int, blocked: set[str], sent_before: set[str],
              include_ready: bool) -> list[sqlite3.Row]:
        where = "status IN ('approved','ready')" if include_ready else "status='approved'"
        out = []
        for r in self.conn.execute(
                f"SELECT * FROM agencies WHERE {where}"
                " ORDER BY status='approved' DESC, approved_at, found_at, id"):
            if r["email"] in blocked:
                self.conn.execute("UPDATE agencies SET status='blocked' WHERE id=?", (r["id"],))
                continue
            if r["email"] in sent_before:
                self.conn.execute("UPDATE agencies SET status='duplicate',"
                                  " status_detail='already emailed' WHERE id=?", (r["id"],))
                continue
            out.append(r)
            if len(out) >= n:
                break
        self.conn.commit()
        return out

    def mark_sent(self, agency_id: int, message_id: str | None):
        self.conn.execute("UPDATE agencies SET status='sent', sent_at=?, message_id=? WHERE id=?",
                          (now(), message_id, agency_id))
        self.conn.commit()

    # ---------- reporting ----------

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in STATUSES}
        for r in self.conn.execute("SELECT status, COUNT(*) n FROM agencies GROUP BY status"):
            out[r["status"]] = r["n"]
        out["total"] = sum(out[s] for s in STATUSES)
        out["searches"] = self.conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
        return out

    def counts_by_state(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT state, COUNT(*) total, SUM(status IN ('ready','approved','sent')) with_email"
            " FROM agencies GROUP BY state ORDER BY total DESC")]

    def daily_rows(self, days=14) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM daily ORDER BY day DESC LIMIT ?", (days,))]

    def list(self, status: str, limit=50, offset=0, search: str | None = None):
        where, args = "status=?", [status]
        if search:
            where += " AND (name LIKE ? OR email LIKE ? OR city LIKE ? OR state LIKE ? OR domain LIKE ?)"
            args += [f"%{search}%"] * 5
        total = self.conn.execute(f"SELECT COUNT(*) FROM agencies WHERE {where}", args).fetchone()[0]
        order = {"sent": "sent_at DESC", "approved": "approved_at, id"}.get(status, "found_at DESC, id")
        rows = self.conn.execute(
            f"SELECT * FROM agencies WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [limit, offset])
        return [dict(r) for r in rows], total

    def get(self, agency_id: int):
        return self.conn.execute("SELECT * FROM agencies WHERE id=?", (agency_id,)).fetchone()
