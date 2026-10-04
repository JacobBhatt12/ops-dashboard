"""Dashboard-facing functions for the Lead Finder tab (used by management_app.py)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from . import settings as S
from .overture import CATEGORY_GROUPS, STATE_BBOX
from .store import LeadStore, row_to_dict
from .template import render_lead

ROOT = S.ROOT
_job_lock = threading.Lock()
_job = {"proc": None}

LAUNCHD_LABEL = "com.theraweb.leadfinder"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _store():
    return LeadStore()


def job_running() -> bool:
    p = _job["proc"]
    return p is not None and p.poll() is None


def summary() -> dict:
    st = _store()
    try:
        status = S.read_status()
        if status.get("running") and not job_running():
            # The dashboard was restarted mid-job, or the nightly run owns it.
            # Trust the file only if it was touched recently.
            try:
                import time
                age = time.time() - S.STATUS_PATH.stat().st_mtime
                if age > 600:
                    status["running"] = False
                    status["message"] = (status.get("message") or "") + " (stopped)"
            except OSError:
                pass
        return {
            "counts": st.counts(),
            "by_state": st.counts_by_state(),
            "daily": st.daily_rows(14),
            "settings": S.load(),
            "job": status,
            "last_release": st.get_meta("last_release"),
            "last_import": st.get_meta("last_import"),
            "categories": [{"key": k, "label": v[0]} for k, v in CATEGORY_GROUPS.items()],
            "states": sorted(STATE_BBOX),
            "nightly_installed": PLIST_PATH.is_file() or _cron_has_job(),
            "daily_target": _daily_target(),
        }
    finally:
        st.close()


def _daily_target() -> int:
    try:
        from bot.config import Config
        return int(Config.load()["volume"]["daily_target"])
    except Exception:
        return 200


def list_leads(status: str, limit: int, offset: int, q: str | None) -> dict:
    st = _store()
    try:
        rows, total = st.list(status, limit=max(1, min(limit, 500)), offset=max(0, offset), search=q or None)
        return {"leads": rows, "total": total}
    finally:
        st.close()


def preview(lead_id: int) -> dict:
    st = _store()
    try:
        r = st.get(lead_id)
        if r is None:
            raise ValueError("Lead not found")
        subject, text, _ = render_lead(row_to_dict(r))
        return {"subject": subject, "text": text, "to": r["email"]}
    finally:
        st.close()


def review(payload: dict) -> dict:
    action = payload.get("action")
    st = _store()
    try:
        if action == "approve_next":
            n = int(payload.get("n", 25))
            if not 1 <= n <= 5000:
                raise ValueError("n must be between 1 and 5000")
            return {"changed": st.approve_next(n)}
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
            raise ValueError("Pick at least one lead")
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
    if "send_enabled" in payload:
        clean["send_enabled"] = bool(payload["send_enabled"])
    if "skip_healthy_sites" in payload:
        clean["skip_healthy_sites"] = bool(payload["skip_healthy_sites"])
    if "per_day" in payload:
        v = int(payload["per_day"])
        if not 0 <= v <= 400:
            raise ValueError("Leads per day must be between 0 and 400")
        clean["per_day"] = v
    if "nightly_limit" in payload:
        v = int(payload["nightly_limit"])
        if not 50 <= v <= 10000:
            raise ValueError("Sites per night must be between 50 and 10,000")
        clean["nightly_limit"] = v
    if "nightly_hour" in payload:
        v = int(payload["nightly_hour"])
        if not 0 <= v <= 23:
            raise ValueError("Hour must be 0 to 23")
        clean["nightly_hour"] = v
    if "states" in payload:
        states = [str(s).upper() for s in payload["states"]]
        if not states or any(s not in STATE_BBOX for s in states):
            raise ValueError("Pick at least one valid state")
        clean["states"] = states
    if "categories" in payload:
        cats = [str(c) for c in payload["categories"]]
        if not cats or any(c not in CATEGORY_GROUPS for c in cats):
            raise ValueError("Pick at least one category")
        clean["categories"] = cats
    new = S.save(clean)
    if "nightly_enabled" in payload:
        enabled = bool(payload["nightly_enabled"])
        apply_nightly(enabled, new["nightly_hour"])
        new = S.save({"nightly_enabled": enabled})
    elif "nightly_hour" in clean and new.get("nightly_enabled"):
        apply_nightly(True, new["nightly_hour"])
    return new


def start_job(payload: dict) -> dict:
    job = payload.get("job")
    with _job_lock:
        if job_running():
            raise RuntimeError("A Lead Finder job is already running")
        py = sys.executable
        if job == "import":
            cfg = S.load()
            args = [py, "-m", "leadfinder.run", "import", "--states", *cfg["states"],
                    "--categories", *cfg["categories"]]
        elif job == "crawl":
            limit = int(payload.get("limit", 500))
            if not 1 <= limit <= 10000:
                raise ValueError("Limit must be between 1 and 10,000")
            args = [py, "-m", "leadfinder.run", "crawl", "--limit", str(limit)]
        else:
            raise ValueError("Unknown job")
        S.write_status(job=job, running=True, message="Starting...", progress=0, total=0, error=None)
        S.LOG_DIR.mkdir(parents=True, exist_ok=True)
        out = open(S.LOG_DIR / "leadfinder-dashboard.log", "a")
        _job["proc"] = subprocess.Popen(args, cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
                                        env={**os.environ, "PYTHONUNBUFFERED": "1"})
        return {"started": job}


# ---------- nightly schedule ----------

def _plist(hour: int) -> str:
    log = S.LOG_DIR / "leadfinder-nightly.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>Label</key><string>{LAUNCHD_LABEL}</string>
\t<key>ProgramArguments</key>
\t<array>
\t\t<string>{sys.executable}</string>
\t\t<string>-m</string>
\t\t<string>leadfinder.run</string>
\t\t<string>nightly</string>
\t</array>
\t<key>WorkingDirectory</key><string>{ROOT}</string>
\t<key>StartCalendarInterval</key>
\t<dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>7</integer></dict>
\t<key>StandardOutPath</key><string>{log}</string>
\t<key>StandardErrorPath</key><string>{log}</string>
\t<key>RunAtLoad</key><false/>
</dict>
</plist>
"""


def _cron_line(hour: int) -> str:
    return f"7 {hour} * * * cd '{ROOT}' && '{sys.executable}' -m leadfinder.run nightly >> '{S.LOG_DIR}/leadfinder-nightly.log' 2>&1 # theraweb-leadfinder"


def _cron_has_job() -> bool:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except FileNotFoundError:
        return False
    return r.returncode == 0 and "theraweb-leadfinder" in r.stdout


def apply_nightly(enabled: bool, hour: int) -> None:
    if sys.platform == "darwin":
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LAUNCHD_LABEL}"], capture_output=True)
        if not enabled:
            if PLIST_PATH.is_file():
                PLIST_PATH.unlink()
            return
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLIST_PATH.write_text(_plist(hour))
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "launchctl could not schedule the nightly check")
        return
    # Linux server: plain crontab.
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError("No launchd or cron on this machine") from e
    lines = [l for l in (r.stdout.splitlines() if r.returncode == 0 else []) if "theraweb-leadfinder" not in l]
    if enabled:
        lines.append(_cron_line(hour))
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
