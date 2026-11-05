"""Dashboard-facing functions for the Agencies tab (used by ops_dashboard.py)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from . import settings as S
from .cities import CITIES, STATE_NAMES, all_queries
from .scrape import docker_ready
from .store import AgencyStore
from .template import render_agency

ROOT = S.ROOT
_job_lock = threading.Lock()
_job = {"proc": None}



def job_running() -> bool:
    p = _job["proc"]
    return p is not None and p.poll() is None


def _send_split() -> dict:
    out = {"client_per_day": 150, "start_hour": 9, "end_hour": 21,
           "sent_today": {"client": 0, "agency": 0}, "recent_sends": []}
    try:
        import sqlite3
        from datetime import date
        from bot.config import Config
        cfg = Config.load()
        out.update(client_per_day=int(cfg["volume"]["daily_target"]),
                   start_hour=int(cfg["schedule"]["start_hour"]),
                   end_hour=int(cfg["schedule"]["end_hour"]))
        db = sqlite3.connect(f"file:{cfg.path('state_db')}?mode=ro", uri=True)
        today = date.today().isoformat()
        for tpl, n in db.execute("SELECT template='agency', COUNT(*) FROM sends WHERE sent_on=? GROUP BY 1", (today,)):
            out["sent_today"]["agency" if tpl else "client"] = n
        out["recent_sends"] = [
            {"at": r[0], "email": r[1], "company": r[2], "stream": "agency" if r[3] == "agency" else "client"}
            for r in db.execute("SELECT sent_at, email, company, template FROM sends"
                                " WHERE sent_on=? ORDER BY id DESC LIMIT 12", (today,))]
        db.close()
    except Exception:
        pass
    return out


def summary() -> dict:
    st = AgencyStore()
    try:
        status = S.read_status()
        if status.get("running") and not job_running():
            try:
                if time.time() - S.STATUS_PATH.stat().st_mtime > 1800:
                    status["running"] = False
                    status["message"] = (status.get("message") or "") + " (stopped)"
            except OSError:
                pass
        cfg = S.load()
        done = st.searched()
        all_q = all_queries(cfg["states"], cfg["search_terms"])
        ok, docker_msg = docker_ready()
        return {
            "counts": st.counts(),
            "by_state": st.counts_by_state(),
            "daily": st.daily_rows(14),
            "settings": cfg,
            "job": status,
            "searches_total": len(all_q),
            "searches_left": sum(1 for q, _ in all_q if q not in done),
            "states": [{"code": c, "name": STATE_NAMES[c]} for c in sorted(CITIES)],
            "docker": {"ok": ok, "message": docker_msg},
            "nightly_installed": _nightly_installed(),
            **_send_split(),
        }
    finally:
        st.close()


def list_leads(status: str, limit, offset, q: str | None) -> dict:
    limit, offset = int(limit), int(offset)
    st = AgencyStore()
    try:
        rows, total = st.list(status, limit=max(1, min(limit, 500)), offset=max(0, offset),
                              search=q or None)
        return {"agencies": rows, "total": total}
    finally:
        st.close()


def preview(agency_id) -> dict:
    st = AgencyStore()
    try:
        r = st.get(int(agency_id or 0))
        if r is None:
            raise ValueError("Agency not found")
        subject, text, _ = render_agency(dict(r))
        return {"subject": subject, "text": text, "to": r["email"]}
    finally:
        st.close()


def review(payload: dict) -> dict:
    action = payload.get("action")
    st = AgencyStore()
    try:
        if action == "approve_next":
            n = int(payload.get("n", 150))
            if not 1 <= n <= 5000:
                raise ValueError("n must be between 1 and 5000")
            return {"changed": st.approve_next(n)}
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
            raise ValueError("Pick at least one agency")
        if action == "approve":
            n = st.set_status(ids, "approved", ("ready", "rejected"))
        elif action == "reject":
            n = st.set_status(ids, "rejected", ("ready", "approved"))
        elif action == "unapprove":
            n = st.set_status(ids, "ready", ("approved", "rejected"))
        else:
            raise ValueError("Unknown action")
        return {"changed": n}
    finally:
        st.close()


def update_settings(payload: dict) -> dict:
    clean = {}
    for key in ("send_enabled", "auto_approve"):
        if key in payload:
            clean[key] = bool(payload[key])
    for key, lo, hi, label in (("per_day", 0, 150, "Agencies per day"),
                               ("depth", 1, 20, "Scroll depth"),
                               ("concurrency", 1, 8, "Browsers"),
                               ("searches_per_night", 1, 500, "Searches per night")):
        if key in payload:
            v = int(payload[key])
            if not lo <= v <= hi:
                raise ValueError(f"{label} must be between {lo} and {hi}")
            clean[key] = v
    if "states" in payload:
        states = [str(s).upper() for s in payload["states"]]
        if any(s not in CITIES for s in states):
            raise ValueError("Unknown state")
        clean["states"] = states  # empty = whole country
    if "search_terms" in payload:
        terms = [str(t).strip() for t in payload["search_terms"] if str(t).strip()]
        if not terms or any(len(t) > 60 for t in terms):
            raise ValueError("Add at least one search term (60 characters max)")
        clean["search_terms"] = terms
    new = S.save(clean)
    if "nightly_enabled" in payload and bool(payload["nightly_enabled"]) != bool(new.get("nightly_enabled")):
        apply_nightly(bool(payload["nightly_enabled"]))
        new = S.load()
    return new


def start_job(payload: dict) -> dict:
    with _job_lock:
        if job_running():
            raise RuntimeError("An agency search is already running")
        if payload.get("job") != "scrape":
            raise ValueError("Unknown job")
        n = int(payload.get("searches", 16))
        if not 1 <= n <= 500:
            raise ValueError("Searches must be between 1 and 500")
        ok, msg = docker_ready()
        if not ok:
            raise RuntimeError(msg)
        S.write_status(job="scrape", running=True, message="Starting...", progress=0, total=n,
                       found=0, error=None)
        S.LOG_DIR.mkdir(parents=True, exist_ok=True)
        out = open(S.LOG_DIR / "agencyfinder-dashboard.log", "a")
        _job["proc"] = subprocess.Popen(
            [sys.executable, "-m", "agencyfinder.run", "scrape", "--searches", str(n)],
            cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"})
        return {"started": "scrape"}


# ---------- nightly schedule ----------
# One job (bot.nightly) refills both the client and the agency queues, one
# after the other, so the small server never runs DuckDB and Chromium at once.
# It's installed through the Lead Finder's scheduler at the Lead Finder hour.

def _nightly_installed() -> bool:
    import leadfinder.api as leads_api
    return leads_api.PLIST_PATH.is_file() or leads_api._cron_has_job()


def apply_nightly(enabled: bool) -> None:
    import leadfinder.api as leads_api
    from leadfinder import settings as LS
    lf = LS.load()
    S.save({"nightly_enabled": enabled})
    leads_api.apply_nightly(bool(lf.get("nightly_enabled")) or enabled, int(lf.get("nightly_hour", 1)))
