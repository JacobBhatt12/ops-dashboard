#!/usr/bin/env python3
"""
Daily entry point.

  python3 -m bot.run_daily --dry-run      plan and print, send nothing
  python3 -m bot.run_daily --preview 10   show the first 10 rendered greetings
  python3 -m bot.run_daily                send for real
  python3 -m bot.run_daily --now          send immediately, ignore the window
  python3 -m bot.run_daily --limit 25     override today's volume

Safe to interrupt. Every send is written to the database before the next one
is attempted, so re-running the same day resumes rather than duplicating.
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from datetime import date, datetime
from pathlib import Path

from .config import Config, ROOT
from .contacts import load_contacts
from .gmail_client import GmailClient
from .message import render, self_check
from .notify import notify
from .scanner import scan
from .selector import Selection, _spread_domains, adjacency_report, plan_schedule, select_batch
from .store import Store

try:  # Lead Finder is optional; the realtor bot runs fine without it.
    from leadfinder import settings as lead_settings
    from leadfinder.bridge import bounce_guard, take_leads
except Exception:  # pragma: no cover
    lead_settings = None


def setup_logging(cfg, dry_run):
    log_dir = cfg.path("log_dir")
    log_dir.mkdir(parents=True, exist_ok=True)
    fname = log_dir / f"{date.today().isoformat()}{'-dryrun' if dry_run else ''}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        handlers=[logging.FileHandler(fname, encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("outreach")


def load_manual_blocklist(store, path, log):
    """
    data/blocklist.txt - one email per line, # for comments.

    This is Jake's file. Anything he puts here is never contacted again.
    Re-read on every run so an edit takes effect on the next batch.
    """
    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "# Nimble Email Sender - manual do-not-send list\n"
            "# One email address per line. Lines starting with # are ignored.\n"
            "# Anything listed here is permanently excluded from every batch.\n",
            encoding="utf-8")
        return 0

    existing = store.blocked_emails()
    added = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip().lower()
        if not line or "@" not in line:
            continue
        if line not in existing:
            store.block(line, "manual blocklist", "manual")
            added += 1
            log.info(f"  blocked (manual): {line}")
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(description="Nimble Email Sender - daily outreach run")
    ap.add_argument("--dry-run", action="store_true",
                    help="select and plan, but send nothing")
    ap.add_argument("--preview", type=int, metavar="N",
                    help="print the first N rendered messages and exit")
    ap.add_argument("--limit", type=int, help="override daily_target")
    ap.add_argument("--now", action="store_true",
                    help="ignore the schedule window; send back to back at the floor gap")
    ap.add_argument("--no-scan", action="store_true",
                    help="skip the bounce/opt-out scan (not recommended)")
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)

    cfg = Config.load(args.config)
    log = setup_logging(cfg, args.dry_run)

    self_check()

    if args.limit:
        cfg["volume"]["daily_target"] = args.limit

    today = date.today()
    if cfg["schedule"].get("weekdays_only", True) and today.weekday() >= 5 \
            and not (args.dry_run or args.preview):
        log.info(f"{today} is a weekend and weekdays_only is set. Nothing to do.")
        return 0

    store = Store(cfg.path("state_db"))
    rng = random.Random()

    log.info("=" * 72)
    log.info(f"Nimble Email Sender run - {datetime.now():%Y-%m-%d %H:%M:%S}"
             f"{'  [DRY RUN]' if args.dry_run else ''}")
    log.info("=" * 72)

    # 1. Blocks
    n = load_manual_blocklist(store, cfg.path("manual_blocklist"), log)
    if n:
        log.info(f"Manual blocklist: {n} new entries")

    if not (os.environ.get("SENDER_EMAIL") or cfg["sender"]["address"]):
        log.error("No sender address. Set SENDER_EMAIL in .env.")
        store.close()
        return 1

    client = GmailClient(
        cfg.path("oauth_client_secret"), cfg.path("oauth_token"),
        os.environ.get("SENDER_EMAIL") or cfg["sender"]["address"],
        os.environ.get("SENDER_NAME") or cfg["sender"].get("display_name", ""),
        dry_run=args.dry_run,
    )

    # 2. Scan for opt-outs and bounces BEFORE selecting, so anyone who asked
    #    to be left alone is excluded from this batch and not the next one.
    if cfg["safety"].get("scan_before_send", True) and not args.no_scan \
            and not args.preview:
        log.info("Scanning replies and bounces...")
        try:
            s = scan(client, store, cfg, log=log.info)
            log.info(f"  scanned {s['scanned']} new messages: "
                     f"{s['optouts']} opt-outs, {s['bounces']} bounces blocked")
        except Exception as e:
            log.warning(f"  scan failed: {e}")
            if not args.dry_run:
                log.error("Refusing to send without a successful opt-out scan. "
                          "Re-run, or pass --no-scan to override deliberately.")
                notify(cfg, client, "Nimble Email Sender: run FAILED (opt-out scan "
                       "error, nothing sent). Check logs/.", log=log.info)
                store.close()
                return 2

    # 3. Load contacts (skipped when Lead Finder is the only source)
    lf = lead_settings.load() if lead_settings else {}
    use_contacts = bool(lf.get("contact_list_enabled", True))
    xlsx = cfg.path("contacts_xlsx")
    contacts = []
    if not use_contacts:
        log.info("Contact list is off (Lead Finder only)")
    elif not xlsx.exists():
        log.error(f"Contact list not found: {xlsx}")
        if not args.dry_run and not args.preview:
            notify(cfg, client, "Nimble Email Sender: run FAILED (contact list "
                   "missing, nothing sent). Check logs/.", log=log.info)
        store.close()
        return 1
    else:
        contacts = load_contacts(xlsx, cfg["paths"]["contacts_sheet"])
        log.info(f"Loaded {len(contacts)} contacts from {xlsx.name}")

        warned = [c for c in contacts if c.warnings]
        if warned:
            log.info(f"  {len(warned)} rows carry data-quality warnings "
                     f"(see --preview for detail)")

    # 3b. Bounce guard: if too many hard bounces came back lately, stop
    #     everything before it costs the domain its reputation.
    if lead_settings and not args.preview:
        ok, why = bounce_guard(store, float(lf.get("max_bounce_rate", 0.03)))
        log.info(f"Bounce check: {why}")
        if not ok and not args.dry_run:
            log.error("Bounce rate over the limit. Pausing ALL sends today. "
                      "Clean the list or raise max_bounce_rate in data/leadfinder.json.")
            notify(cfg, client, f"Nimble Email Sender: PAUSED, bounce rate too high ({why}). "
                   "Nothing sent.", log=log.info)
            store.close()
            return 3

    # 4. Select
    already = store.count_sent_on(today)
    if already:
        log.info(f"{already} already sent today; topping up to the daily target")
        cfg["volume"]["daily_target"] = max(
            0, int(cfg["volume"]["daily_target"]) - already)

    # 4a. Approved Lead Finder businesses take their share of today's slots
    #     first; the realtor list fills the rest. With the contact list off,
    #     Lead Finder gets the whole daily target.
    lead_batch, lead_store = [], None
    target = int(cfg["volume"]["daily_target"])
    if lf.get("send_enabled"):
        want = min(int(lf.get("per_day", 0)), target) if use_contacts else target
        lead_batch, lead_store = take_leads(store, want, bool(lf.get("auto_approve")))
        log.info(f"Lead Finder: {len(lead_batch)} businesses in today's batch (up to {want})")
        cfg["volume"]["daily_target"] = target - len(lead_batch)

    if use_contacts:
        sel = select_batch(contacts, store, cfg, today=today, rng=rng)
    else:
        sel = Selection([], {"shortfall": target - len(lead_batch)} if len(lead_batch) < target else {})
    if lead_batch:
        sel.batch = _spread_domains(lead_batch + sel.batch, rng)
        sel.stats["lead_finder"] = len(lead_batch)
    log.info(f"Selected {len(sel)} ({len(lead_batch)} Lead Finder + {len(sel) - len(lead_batch)} contact list)")
    for k in sorted(sel.stats):
        log.info(f"    {k}: {sel.stats[k]}")
    log.info(f"    adjacent same-domain pairs: {adjacency_report(sel.batch)}")

    if sel.stats.get("shortfall"):
        log.warning(f"  SHORTFALL: {sel.stats['shortfall']} under target. "
                    "The eligible pool is smaller than the daily volume.")

    if not sel.batch:
        log.info("Nothing eligible. Done.")
        if not args.dry_run and not args.preview:
            notify(cfg, client, "Nimble Email Sender: ran today, 0 sent "
                   "(nothing eligible).", log=log.info)
        store.close()
        return 0

    # 5. Preview mode
    if args.preview:
        for c in sel.batch[: args.preview]:
            subj, text, _ = c.render() if getattr(c, "template", "") == "business" else render(c)
            print("\n" + "-" * 72)
            print(f"TO:      {c.email}")
            print(f"NAME:    {c.first_raw!r} {c.last!r}  ->  {c.greeting!r}")
            print(f"COMPANY: {c.company}  |  TITLE: {c.title}")
            if c.warnings:
                print(f"WARN:    {'; '.join(c.warnings)}")
            print("-" * 72)
            print(text)
        store.close()
        return 0

    # 6. Schedule
    if args.now:
        floor = int(cfg["schedule"].get("min_gap_seconds", 45))
        times = None
        log.info(f"--now: sending back to back at the {floor}s floor gap")
    else:
        times = plan_schedule(len(sel.batch), cfg, rng=rng)
        span = (times[-1] - times[0]).total_seconds() / 3600
        log.info(f"Scheduled across {span:.1f}h: "
                 f"{times[0]:%H:%M} to {times[-1]:%H:%M}")

    if args.dry_run:
        log.info("DRY RUN - no messages sent. First 10 of the plan:")
        for i, c in enumerate(sel.batch[:10]):
            when = times[i].strftime("%H:%M:%S") if times else "asap"
            log.info(f"    {when}  {c.greeting:<18} {c.email}")
        store.close()
        return 0

    # 7. Send
    run_id = store.start_run(len(sel.batch), args.dry_run)
    sent = failed = 0
    api_ceiling = int(cfg["safety"]["daily_api_ceiling"])

    try:
        for i, c in enumerate(sel.batch):
            if store.count_sent_on(today) >= api_ceiling:
                log.warning(f"Daily API ceiling ({api_ceiling}) reached. Stopping.")
                break

            if times and not args.now:
                wait = (times[i] - datetime.now()).total_seconds()
                if wait > 0:
                    time.sleep(wait)
            elif i:
                time.sleep(max(1, int(cfg["schedule"].get("min_gap_seconds", 45))))

            is_lead = getattr(c, "template", "") == "business"
            subj, text, html = c.render() if is_lead else render(c)
            try:
                mid, tid = client.send(c.email, subj, text, html)
                # Recorded immediately: a crash after this point can never
                # produce a duplicate on resume.
                store.record_send(c, message_id=mid, thread_id=tid,
                                  template="business" if is_lead else "standard")
                if is_lead and lead_store is not None:
                    lead_store.mark_sent(c.lead_id, mid)
                sent += 1
                log.info(f"[{i+1}/{len(sel.batch)}] sent  {c.greeting:<18} {c.email}")
            except Exception as e:
                failed += 1
                log.error(f"[{i+1}/{len(sel.batch)}] FAIL  {c.email}: {e}")
    except Exception as e:
        log.error(f"Run crashed mid-batch after {sent} sent, {failed} failed: {e}")
        store.finish_run(run_id, sent, failed)
        notify(cfg, client, f"Nimble Email Sender: CRASHED mid-run ({sent} sent "
               f"before it died). Check logs/.", log=log.info)
        store.close()
        return 1

    store.finish_run(run_id, sent, failed)
    log.info("-" * 72)
    log.info(f"Done. {sent} sent, {failed} failed.")
    log.info(f"Lifetime blocks on file: {len(store.blocked_emails())}")
    summary = (f"Nimble Email Sender: {sent} sent" +
               (f", {failed} failed" if failed else "") +
               (f", {sel.stats['shortfall']} short of target" if sel.stats.get("shortfall") else "") +
               ".")
    notify(cfg, client, summary, log=log.info)
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
