"""
Persistent state: who has been sent what, when, and who must never be
contacted again.

SQLite, single file, no server. Every write is committed immediately so an
interrupted run cannot lose the record of a message that actually went out.
That ordering matters: the send is logged BEFORE the next send is attempted,
so a crash mid-batch can never cause a duplicate on resume.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sends (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL,
    person_key    TEXT NOT NULL,
    first_name    TEXT,
    last_name     TEXT,
    company       TEXT,
    sent_on       TEXT NOT NULL,          -- YYYY-MM-DD local
    sent_at       TEXT NOT NULL,          -- ISO timestamp
    message_id    TEXT,
    thread_id     TEXT,
    template      TEXT NOT NULL DEFAULT 'standard',
    source        TEXT NOT NULL DEFAULT 'bot'
);
CREATE INDEX IF NOT EXISTS idx_sends_email   ON sends(email);
CREATE INDEX IF NOT EXISTS idx_sends_person  ON sends(person_key);
CREATE INDEX IF NOT EXISTS idx_sends_date    ON sends(sent_on);

CREATE TABLE IF NOT EXISTS blocks (
    email      TEXT PRIMARY KEY,
    reason     TEXT NOT NULL,
    source     TEXT NOT NULL,             -- manual | optout | bounce | seed
    added_at   TEXT NOT NULL,
    detail     TEXT
);

CREATE TABLE IF NOT EXISTS person_blocks (
    person_key TEXT PRIMARY KEY,
    reason     TEXT NOT NULL,
    added_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    planned     INTEGER NOT NULL DEFAULT 0,
    sent        INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    dry_run     INTEGER NOT NULL DEFAULT 0,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS scanned (
    message_id TEXT PRIMARY KEY,
    seen_at    TEXT NOT NULL
);
"""


def person_key(first: str | None, last: str | None, email: str) -> str:
    """
    Identity for de-duplication.

    Deliberately NOT the email address. The same human has shown up in this
    list under two different addresses (Ajay Babbar, Days 11 and 16), and
    hammering one person twice because they have two mailboxes is exactly
    the failure mode the gap rule exists to prevent.

    Falls back to the email when there is no usable name.
    """
    f = (first or "").strip().lower()
    l = (last or "").strip().lower()
    if f and l and f != l:
        return f"{f}|{l}"
    if f or l:
        return f"{f or l}|@{email.split('@')[-1].lower()}"
    return email.strip().lower()


class Store:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- sends ----------

    def record_send(self, contact, *, message_id=None, thread_id=None,
                    template="standard", source="bot", when=None):
        when = when or datetime.now()
        self.conn.execute(
            "INSERT INTO sends (email, person_key, first_name, last_name, company,"
            " sent_on, sent_at, message_id, thread_id, template, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (contact.email, contact.person_key, contact.first_raw, contact.last,
             contact.company, when.date().isoformat(), when.isoformat(),
             message_id, thread_id, template, source),
        )
        self.conn.commit()

    def last_sent_map(self) -> dict[str, date]:
        """person_key -> most recent send date."""
        cur = self.conn.execute(
            "SELECT person_key, MAX(sent_on) AS last FROM sends GROUP BY person_key"
        )
        out = {}
        for r in cur:
            try:
                out[r["person_key"]] = date.fromisoformat(r["last"])
            except (TypeError, ValueError):
                continue
        return out

    def touch_counts(self) -> dict[str, int]:
        cur = self.conn.execute(
            "SELECT person_key, COUNT(*) AS n FROM sends GROUP BY person_key"
        )
        return {r["person_key"]: r["n"] for r in cur}

    def sent_on(self, day: date) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM sends WHERE sent_on = ? ORDER BY sent_at", (day.isoformat(),)
        ))

    def count_sent_on(self, day: date, template: str | None = None,
                      exclude_template: str | None = None) -> int:
        """Sends on `day`; optionally only one template, or all but one."""
        q, args = "SELECT COUNT(*) AS n FROM sends WHERE sent_on = ?", [day.isoformat()]
        if template:
            q += " AND template = ?"
            args.append(template)
        if exclude_template:
            q += " AND template <> ?"
            args.append(exclude_template)
        return self.conn.execute(q, args).fetchone()["n"]

    # ---------- blocks ----------

    def block(self, email: str, reason: str, source: str, detail: str | None = None):
        self.conn.execute(
            "INSERT OR REPLACE INTO blocks (email, reason, source, added_at, detail)"
            " VALUES (?,?,?,?,?)",
            (email.strip().lower(), reason, source, datetime.now().isoformat(), detail),
        )
        self.conn.commit()

    def block_person(self, pkey: str, reason: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO person_blocks (person_key, reason, added_at)"
            " VALUES (?,?,?)",
            (pkey, reason, datetime.now().isoformat()),
        )
        self.conn.commit()

    def blocked_emails(self) -> set[str]:
        return {r["email"] for r in self.conn.execute("SELECT email FROM blocks")}

    def blocked_persons(self) -> set[str]:
        return {r["person_key"] for r in self.conn.execute(
            "SELECT person_key FROM person_blocks")}

    def block_rows(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM blocks ORDER BY added_at DESC"))

    # ---------- runs ----------

    def start_run(self, planned: int, dry_run: bool) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (run_date, started_at, planned, dry_run)"
            " VALUES (?,?,?,?)",
            (date.today().isoformat(), datetime.now().isoformat(),
             planned, 1 if dry_run else 0),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, sent: int, failed: int, note: str = ""):
        self.conn.execute(
            "UPDATE runs SET finished_at=?, sent=?, failed=?, note=? WHERE id=?",
            (datetime.now().isoformat(), sent, failed, note, run_id),
        )
        self.conn.commit()

    # ---------- scan bookkeeping ----------

    def already_scanned(self, mid: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM scanned WHERE message_id=?", (mid,)).fetchone() is not None

    def mark_scanned(self, mid: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO scanned (message_id, seen_at) VALUES (?,?)",
            (mid, datetime.now().isoformat()))
        self.conn.commit()

    def close(self):
        self.conn.close()
