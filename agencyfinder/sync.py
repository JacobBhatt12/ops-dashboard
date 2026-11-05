#!/usr/bin/env python3
"""
Mac side of the Agency Finder: search here, send on the server.

  python3 -m agencyfinder.sync            top up the server's agency queue
  python3 -m agencyfinder.sync --push     only push agencies already found

The server (1 GB) can't run the scraper's browser, so the Mac does the
searching with Docker and pushes each new ready agency to the server once,
over `gcloud compute ssh`. The server re-checks every row against its own
send history and block list on import.

Server details live in .env (gitignored):
  AGENCY_SERVER_GCLOUD   e.g. "my-server --project my-project --zone us-central1-a"
  AGENCY_SERVER_USER     the Linux user that owns the app (default: your ssh user)
  AGENCY_SERVER_DIR      app folder on the server, relative to that user's home
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime

from bot import config as _config  # noqa: F401  (loads .env)

from . import settings as S
from .run import _log, cmd_scrape
from .store import AgencyStore



def _remote(cmd: str, stdin: str | None = None, timeout: int = 300) -> str:
    target = os.environ.get("AGENCY_SERVER_GCLOUD", "").strip()
    if not target:
        raise RuntimeError("Set AGENCY_SERVER_GCLOUD in .env")
    user = os.environ.get("AGENCY_SERVER_USER", "").strip()
    folder = os.environ.get("AGENCY_SERVER_DIR", "thera-app").strip()
    inner = f"cd ~/{folder} && {cmd}"
    remote = f"sudo -iu {shlex.quote(user)} bash -c {shlex.quote(inner)}" if user else inner
    gcloud = os.environ.get("GCLOUD_BIN") or next(
        (p for p in ("/opt/homebrew/bin/gcloud", "/usr/local/bin/gcloud") if os.path.isfile(p)), "gcloud")
    r = subprocess.run([gcloud, "compute", "ssh", *shlex.split(target), "--quiet", "--command", remote],
                       input=stdin, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"server command failed: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout.strip()


def server_queued() -> int:
    return int(_remote("venv/bin/python3 -m agencyfinder.run queued").splitlines()[-1])


def push(log) -> dict:
    st = AgencyStore()
    try:
        rows = st.unexported()
        if not rows:
            log.info("Push: nothing new to send to the server")
            return {"added": 0, "skipped": 0}
        payload = "\n".join(json.dumps({k: r.get(k) for k in AgencyStore.EXPORT_FIELDS}) for r in rows)
        out = _remote("venv/bin/python3 -m agencyfinder.run import -", stdin=payload + "\n")
        res = json.loads(out.splitlines()[-1])
        st.mark_exported([r["id"] for r in rows])
        log.info(f"Push: {len(rows)} sent to server, {res['added']} added, {res['skipped']} "
                 f"already known there; server queue now {res['queued']}")
        return res
    finally:
        st.close()


def wait_for_docker(log, seconds: int = 300) -> bool:
    """Right after login or wake Docker Desktop takes a minute to come up."""
    from .scrape import docker_ready
    deadline = time.time() + seconds
    while True:
        ok, msg = docker_ready()
        if ok:
            return True
        if time.time() > deadline:
            log.warning(f"Sync: {msg}; will try again on the next run")
            return False
        time.sleep(15)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Search on this Mac, push agencies to the server")
    ap.add_argument("--push", action="store_true", help="only push, don't search")
    args = ap.parse_args(argv)
    log = _log()
    cfg = S.load()
    # Keep one day of agency sends waiting on the server, then stop.
    target = int(os.environ.get("AGENCY_QUEUE_TARGET") or cfg["per_day"] or 150)
    S.write_status(sync_at=datetime.now().isoformat(timespec="seconds"))
    try:
        push(log)  # anything left over from last time
        if args.push:
            return 0
        queued = server_queued()
        log.info(f"Sync: server has {queued} agencies queued (target {target})")
        if queued >= target:
            return 0
        if not wait_for_docker(log):
            return 0
        # One batch of 8 searches at a time; push it so the server can start
        # sending right away, then re-check. Bounded so one run can't go forever.
        for _ in range(int(cfg["searches_per_night"]) // 8 or 1):
            cmd_scrape(argparse.Namespace(searches=8), log, searches=8)
            push(log)
            queued = server_queued()
            log.info(f"Sync: server queue now {queued} (target {target})")
            if queued >= target:
                break
        return 0
    except Exception as e:
        log.error(f"Sync failed: {e}")
        S.write_status(sync_error=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
