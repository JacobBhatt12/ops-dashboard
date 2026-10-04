#!/usr/bin/env python3
"""
Lead Finder command line. The dashboard runs these in the background.

  python3 -m leadfinder.run import --states FL GA      pull businesses from Overture
  python3 -m leadfinder.run crawl --limit 1000         check sites, find emails
  python3 -m leadfinder.run nightly                    top up the send queue (import + crawl)
  python3 -m leadfinder.run status                     print counts
  python3 -m leadfinder.run preview --limit 3          print rendered emails for ready leads
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import logging
import sqlite3
import sys
import threading
from datetime import date, datetime

from . import settings as S
from .crawler import _session, check_site, has_mx
from .overture import FALLBACK_RELEASE, fetch_state, latest_release
from .store import LeadStore
from .template import render_lead, self_check


def _log():
    S.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s  %(message)s",
        handlers=[logging.FileHandler(S.LOG_DIR / f"leadfinder-{date.today().isoformat()}.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)])
    return logging.getLogger("leadfinder")


def outreach_blocked_and_sent() -> tuple[set[str], set[str]]:
    """Emails the outreach bot must never contact again, and everyone it already has."""
    try:
        from bot.config import Config
        path = Config.load().path("state_db")
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        blocked = {r[0] for r in db.execute("SELECT email FROM blocks")}
        sent = {r[0] for r in db.execute("SELECT DISTINCT email FROM sends")}
        db.close()
        return blocked, sent
    except Exception:
        return set(), set()


def cmd_import(args, log):
    cfg = S.load()
    states = [s.upper() for s in (args.states or cfg["states"])]
    groups = args.categories or cfg["categories"]
    release = cfg["release"]
    if release == "auto":
        try:
            release = latest_release()
        except Exception as e:
            log.warning(f"Could not list Overture releases ({e}); using {FALLBACK_RELEASE}")
            release = FALLBACK_RELEASE
    store = LeadStore()
    S.write_status(job="import", running=True, started_at=datetime.now().isoformat(timespec="seconds"),
                   message=f"Importing {', '.join(states)} from Overture {release}", progress=0,
                   total=len(states), error=None)
    total_added = total_dup = 0
    try:
        for i, st in enumerate(states):
            S.write_status(message=f"Downloading {st} from Overture {release} (this takes a few minutes)", progress=i)
            rows = fetch_state(st, groups, release=release,
                               min_confidence=cfg["min_confidence"], log=log.info)
            added, dup = store.insert_many(rows, release)
            total_added += added
            total_dup += dup
            log.info(f"  {st}: {len(rows)} matched, {added} new, {dup} already had")
        done_states = set(json.loads(store.get_meta("imported_states") or "[]")) | set(states)
        store.set_meta("imported_states", json.dumps(sorted(done_states)))
        store.set_meta("last_release", release)
        store.set_meta("last_import", datetime.now().isoformat(timespec="seconds"))
        msg = f"Imported {total_added:,} new businesses ({total_dup:,} duplicates skipped)"
        log.info(msg)
        S.write_status(running=False, progress=len(states), message=msg,
                       finished_at=datetime.now().isoformat(timespec="seconds"))
    except Exception as e:
        log.error(f"Import failed: {e}")
        S.write_status(running=False, error=str(e), message=f"Import failed: {e}",
                       finished_at=datetime.now().isoformat(timespec="seconds"))
        return 1
    finally:
        store.close()
    return 0


def decide(lead, res, blocked, sent_before, store, cfg) -> tuple[str, str | None, str | None, str | None]:
    """Returns (status, detail, email, email_source)."""
    email = res.email or lead["email"]
    source = res.email_source if res.email else lead["email_source"]
    if not email:
        if res.robots_blocked:
            return "skipped", "robots.txt asks bots not to read this site", None, None
        if not res.reachable:
            return "dead", res.error or ", ".join(res.issues) or "unreachable", None, None
        return "no_email", None, None, None
    if email in blocked:
        return "blocked", "on the outreach block list", email, source
    if email in sent_before:
        return "duplicate", "already emailed by the outreach bot", email, source
    if store.email_taken(email, lead["id"]):
        return "duplicate", "same email as another lead", email, source
    if not has_mx(email.split("@")[1]):
        return "bad_email", "email domain doesn't accept mail", email, source
    if cfg.get("skip_healthy_sites") and not res.issues:
        return "skipped", "site looks healthy", email, source
    return "ready", None, email, source


def cmd_crawl(args, log, limit=None):
    cfg = S.load()
    limit = limit or args.limit
    store = LeadStore()
    batch = store.next_to_check(limit, args.states if getattr(args, "states", None) else None)
    blocked, sent_before = outreach_blocked_and_sent()
    S.write_status(job="crawl", running=True, started_at=datetime.now().isoformat(timespec="seconds"),
                   message=f"Checking {len(batch):,} websites", progress=0, total=len(batch), error=None)
    log.info(f"Checking {len(batch)} sites")
    # Load dnspython (used by has_mx in this thread) before the workers start.
    # Imported lazily mid-crawl, its file reads fight 16 network threads for
    # the GIL; on thera-server's slow disk that stalled a crawl for minutes.
    try:
        import dns.resolver  # noqa: F401
    except ImportError:
        pass
    local = threading.local()

    def work(lead):
        if not hasattr(local, "sess"):
            local.sess = _session()
        try:
            return lead, check_site(lead["website"], lead["domain"], sess=local.sess), None
        except Exception as e:  # one bad site never kills the run
            return lead, None, e

    found = done = 0
    try:
        with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for lead, res, err in pool.map(work, batch):
                done += 1
                status = None
                if err is not None or res is None:
                    store.save_check(lead["id"], status="dead", detail=f"checker error: {err}")
                else:
                    status, detail, email, source = decide(lead, res, blocked, sent_before, store, cfg)
                    store.save_check(lead["id"], status=status, detail=detail, email=email,
                                     email_source=source, platform=res.platform,
                                     issues=res.issues, copyright_year=res.copyright_year)
                    if status == "ready":
                        found += 1
                        log.info(f"  + {lead['name'][:40]:<40} {email}  {','.join(res.issues) or '-'}")
                store.bump_daily(checked=1, found=1 if (res is not None and err is None and status == "ready") else 0)
                if done % 10 == 0 or done == len(batch):
                    S.write_status(progress=done, found=found,
                                   message=f"Checked {done:,} of {len(batch):,} sites, {found:,} emails found")
        msg = f"Checked {done:,} sites and found {found:,} new emails"
        log.info(msg)
        S.write_status(running=False, message=msg, found=found,
                       finished_at=datetime.now().isoformat(timespec="seconds"))
    except Exception as e:
        log.error(f"Crawl failed: {e}")
        S.write_status(running=False, error=str(e), message=f"Crawl stopped: {e}",
                       finished_at=datetime.now().isoformat(timespec="seconds"))
        return 1
    finally:
        store.close()
    return 0


def cmd_nightly(args, log):
    """Keep tomorrow's send queue full.

    1. Fewer than nightly_limit businesses left to check: import the next
       state in settings["states"] that hasn't been imported yet.
    2. Crawl in chunks until nightly_target_ready leads are queued to send
       (ready + approved) or nightly_limit sites have been checked.
    """
    cfg = S.load()
    limit, target = int(cfg["nightly_limit"]), int(cfg["nightly_target_ready"])

    def snapshot():
        st = LeadStore()
        try:
            c = st.counts()
            return c["new"], c["ready"] + c["approved"], set(json.loads(st.get_meta("imported_states") or "[]"))
        finally:
            st.close()

    new_left, queued, imported = snapshot()
    log.info(f"Nightly: {queued} queued to send (target {target}), {new_left} businesses left to check")
    if new_left < limit:
        pending = [s for s in cfg["states"] if s.upper() not in imported]
        if pending:
            log.info(f"Nightly: importing {pending[0]}")
            # Separate process: DuckDB holds ~300 MB until exit, which on
            # thera-server starved the crawl that follows.
            import subprocess
            subprocess.run([sys.executable, "-m", "leadfinder.run", "import", "--states", pending[0]],
                           cwd=str(S.ROOT))
            new_left, queued, imported = snapshot()
        elif new_left == 0:
            log.warning("Nightly: every configured state is imported and checked. "
                        "Add states in the Lead Finder settings to keep finding leads.")

    checked = 0
    while queued < target and checked < limit and new_left > 0:
        chunk = min(250, limit - checked)
        if cmd_crawl(args, log, limit=chunk) != 0:
            return 1
        checked += chunk
        new_left, queued, _ = snapshot()
    log.info(f"Nightly done: {queued} queued to send, checked up to {checked} sites, {new_left} left to check")
    return 0


def cmd_status(args, log):
    store = LeadStore()
    for k, v in store.counts().items():
        print(f"{k:>10}: {v:,}")
    store.close()
    return 0


def cmd_preview(args, log):
    store = LeadStore()
    rows, _ = store.list("ready", limit=args.limit)
    for r in rows:
        subj, text, _ = render_lead(r)
        print("-" * 72)
        print(f"TO: {r['email']}   SUBJECT: {subj}")
        print("-" * 72)
        print(text)
    store.close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="TheraWeb Lead Finder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import")
    p.add_argument("--states", nargs="*")
    p.add_argument("--categories", nargs="*")
    p = sub.add_parser("crawl")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--states", nargs="*")
    p = sub.add_parser("nightly")
    p.add_argument("--workers", type=int, default=8)
    sub.add_parser("status")
    p = sub.add_parser("preview")
    p.add_argument("--limit", type=int, default=3)
    args = ap.parse_args(argv)

    self_check()
    log = _log()
    if S.read_status().get("running") and args.cmd in ("import", "crawl", "nightly"):
        log.info("Another Lead Finder job is marked running; continuing anyway (the dashboard prevents overlap).")
    if args.cmd == "import":
        return cmd_import(args, log)
    if args.cmd == "crawl":
        return cmd_crawl(args, log)
    if args.cmd == "nightly":
        args.states = None
        return cmd_nightly(args, log)
    if args.cmd == "status":
        return cmd_status(args, log)
    if args.cmd == "preview":
        return cmd_preview(args, log)


if __name__ == "__main__":
    sys.exit(main())
