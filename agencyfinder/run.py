#!/usr/bin/env python3
"""
Agency Finder command line. The dashboard runs these in the background.

  python3 -m agencyfinder.run scrape --searches 20    run the next 20 Google Maps searches
  python3 -m agencyfinder.run nightly                 top up the agency send queue
  python3 -m agencyfinder.run status                  print counts
  python3 -m agencyfinder.run preview --limit 3       print rendered emails for ready agencies
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import date, datetime

from . import settings as S
from .cities import all_queries
from .scrape import qualify, run_scraper
from .store import AgencyStore
from .template import render_agency, self_check

CHUNK = 8  # searches per scraper container, so progress saves as it goes


def _log():
    S.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s  %(message)s",
        handlers=[logging.FileHandler(S.LOG_DIR / f"agencyfinder-{date.today().isoformat()}.log",
                                      encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)])
    return logging.getLogger("agencyfinder")


def _outreach_sets() -> tuple[set[str], set[str]]:
    try:
        from bot.config import Config
        db = sqlite3.connect(f"file:{Config.load().path('state_db')}?mode=ro", uri=True)
        blocked = {r[0] for r in db.execute("SELECT email FROM blocks")}
        sent = {r[0] for r in db.execute("SELECT DISTINCT email FROM sends")}
        db.close()
        return blocked, sent
    except Exception:
        return set(), set()


def _lead_domains() -> set[str]:
    try:
        from leadfinder.settings import LEADS_DB_PATH
        db = sqlite3.connect(f"file:{LEADS_DB_PATH}?mode=ro", uri=True)
        out = {r[0] for r in db.execute("SELECT domain FROM leads WHERE domain IS NOT NULL")}
        db.close()
        return out
    except Exception:
        return set()


def pending_queries(store, cfg) -> list[tuple[str, str]]:
    done = store.searched()
    return [q for q in all_queries(cfg["states"], cfg["search_terms"]) if q[0] not in done]


def cmd_scrape(args, log, searches=None, stop_at_ready=None) -> int:
    cfg = S.load()
    n = searches or args.searches
    store = AgencyStore()
    todo = pending_queries(store, cfg)[:n]
    if not todo:
        msg = "Every search for the chosen states is done. Add states or search terms."
        log.info(msg)
        S.write_status(job="scrape", running=False, message=msg, error=None)
        store.close()
        return 0
    blocked, sent = _outreach_sets()
    lead_domains = _lead_domains()
    S.write_status(job="scrape", running=True, started_at=datetime.now().isoformat(timespec="seconds"),
                   message=f"Searching Google Maps ({len(todo)} searches)", progress=0,
                   total=len(todo), found=0, error=None)
    found = done = 0
    try:
        for i in range(0, len(todo), CHUNK):
            chunk = todo[i:i + CHUNK]
            places = run_scraper([q for q, _ in chunk], tag=f"{datetime.now():%H%M%S}-{i}",
                                 depth=int(cfg["depth"]), concurrency=int(cfg["concurrency"]),
                                 log=log.info)
            got = qualify(places, store, blocked, sent, lead_domains, log=log.info)
            store.record_searches(chunk, len(places), got)
            found += got
            done += len(chunk)
            log.info(f"  {done}/{len(todo)} searches: {len(places)} profiles, {got} new agencies with email")
            S.write_status(progress=done, found=found,
                           message=f"Ran {done} of {len(todo)} searches, {found} agencies with email found")
            if stop_at_ready is not None:
                c = store.counts()
                if c["ready"] + c["approved"] >= stop_at_ready:
                    log.info("  send queue is full; stopping early")
                    break
        msg = f"Ran {done} searches and found {found} agencies with an email"
        log.info(msg)
        S.write_status(running=False, message=msg, found=found,
                       finished_at=datetime.now().isoformat(timespec="seconds"))
    except Exception as e:
        log.error(f"Scrape failed: {e}")
        S.write_status(running=False, error=str(e), message=f"Scrape stopped: {e}",
                       finished_at=datetime.now().isoformat(timespec="seconds"))
        return 1
    finally:
        store.close()
    return 0


def cmd_nightly(args, log) -> int:
    cfg = S.load()
    st = AgencyStore()
    c = st.counts()
    st.close()
    queued, target = c["ready"] + c["approved"], int(cfg["nightly_target_ready"])
    log.info(f"Nightly: {queued} agencies queued (target {target})")
    if queued >= target:
        return 0
    return cmd_scrape(args, log, searches=int(cfg["searches_per_night"]), stop_at_ready=target)


def cmd_status(args, log) -> int:
    st = AgencyStore()
    for k, v in st.counts().items():
        print(f"{k:>10}: {v:,}")
    print(f"   pending: {len(pending_queries(st, S.load())):,} searches left")
    st.close()
    return 0


def cmd_preview(args, log) -> int:
    st = AgencyStore()
    rows, _ = st.list("ready", limit=args.limit)
    for r in rows:
        subj, text, _ = render_agency(r)
        print("-" * 72)
        print(f"TO: {r['email']}   SUBJECT: {subj}")
        print("-" * 72)
        print(text)
    st.close()
    return 0


def cmd_import(args, log) -> int:
    """Server side: read JSON lines (from the Mac) on stdin or a file."""
    src = sys.stdin if args.file == "-" else open(args.file)
    rows = [json.loads(l) for l in src if l.strip().startswith("{")]
    blocked, sent = _outreach_sets()
    st = AgencyStore()
    res = st.import_rows(rows, blocked, sent, _lead_domains())
    print(json.dumps({**res, "queued": st.queued()}))
    st.close()
    return 0


def cmd_queued(args, log) -> int:
    st = AgencyStore()
    print(st.queued())
    st.close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="TheraWeb Agency Finder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scrape")
    p.add_argument("--searches", type=int, default=16)
    sub.add_parser("nightly")
    sub.add_parser("status")
    p = sub.add_parser("preview")
    p.add_argument("--limit", type=int, default=3)
    p = sub.add_parser("import")
    p.add_argument("file", nargs="?", default="-")
    sub.add_parser("queued")
    args = ap.parse_args(argv)

    if args.cmd in ("import", "queued"):  # machine-readable output, no log noise
        return {"import": cmd_import, "queued": cmd_queued}[args.cmd](args, None)
    self_check()
    log = _log()
    return {"scrape": cmd_scrape, "nightly": cmd_nightly, "status": cmd_status,
            "preview": cmd_preview}[args.cmd](args, log)


if __name__ == "__main__":
    sys.exit(main())
