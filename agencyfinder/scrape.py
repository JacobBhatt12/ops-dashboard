"""Find agencies on Google Maps with the free gosom/google-maps-scraper image.

  docker run gosom/google-maps-scraper -input queries.txt -json -email ...

The scraper opens each Google Business Profile in the results, and with
-email also visits the agency's website for a published address. Results
without one get a second try with the Lead Finder's own site crawler, which
reads the homepage and up to two contact pages. Nothing is guessed: only
published emails, on the agency's own domain or a personal mailbox.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from leadfinder.crawler import _plausible, _session, base_domain, check_site, has_mx, pick_email

from . import settings as S
from .cities import NAME_TO_CODE, STATE_NAMES

IMAGE = os.environ.get("AGENCY_SCRAPER_IMAGE", "gosom/google-maps-scraper")

# Google Maps categories that mean "this business builds sites or does SEO".
AGENCY_WORDS = ("website", "web design", "web develop", "seo", "search engine",
                "marketing", "advertising", "internet", "graphic design", "branding",
                "digital", "software", "design agency", "media")


def docker_bin() -> str | None:
    """docker isn't on launchd/cron's PATH on a Mac, so check the usual spots."""
    cands = [os.environ.get("DOCKER_BIN"), shutil.which("docker"),
             str(Path.home() / ".docker" / "bin" / "docker"),
             "/usr/local/bin/docker", "/opt/homebrew/bin/docker", "/usr/bin/docker"]
    for c in cands:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def docker_ready() -> tuple[bool, str]:
    d = docker_bin()
    if not d:
        return False, ("Docker isn't on this machine, so searches run on the Mac "
                       "(agencyfinder.sync, whenever the Mac is on) and new agencies are pushed here.")
    try:
        r = subprocess.run([d, "image", "inspect", IMAGE], capture_output=True, text=True,
                           timeout=30, env=_env(d))
    except Exception as e:
        return False, f"Docker isn't responding ({e})"
    if r.returncode != 0:
        if "daemon" in (r.stderr or "").lower():
            return False, "Docker is installed but not running. Open Docker Desktop."
        return True, f"{IMAGE} will be downloaded on the first run"
    return True, "Docker and the Google Maps scraper are ready"


def _env(d: str) -> dict:
    # The credential helper (docker-credential-desktop) lives next to docker.
    return {**os.environ, "PATH": f"{Path(d).parent}:{os.environ.get('PATH', '/usr/bin:/bin')}"}


def run_scraper(queries: list[str], *, tag: str, depth: int, concurrency: int,
                log=print, timeout_s: int = 3600) -> list[dict]:
    """Run one container over `queries`. Returns the raw place dicts."""
    d = docker_bin()
    if not d:
        raise RuntimeError("Docker isn't installed on this machine")
    S.WORK_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(S.WORK_DIR, 0o777)  # the container may write as another user
    qfile = S.WORK_DIR / f"q-{tag}.txt"
    rfile = S.WORK_DIR / f"r-{tag}.json"
    qfile.write_text("\n".join(queries) + "\n")
    if rfile.exists():
        rfile.unlink()
    cmd = [d, "run", "--rm", "-v", f"{S.WORK_DIR}:/work", IMAGE,
           "-input", f"/work/{qfile.name}", "-results", f"/work/{rfile.name}",
           "-json", "-email", "-depth", str(depth), "-c", str(concurrency),
           "-exit-on-inactivity", "3m"]
    log(f"  scraping {len(queries)} searches")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=_env(d))
        if r.returncode != 0:
            log(f"  scraper exited {r.returncode}: {(r.stderr or r.stdout)[-400:]}")
    except subprocess.TimeoutExpired:
        log("  scraper timed out; keeping whatever it wrote")
    places = []
    if rfile.exists():
        for line in rfile.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    places.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    for f in (qfile, rfile):
        try:
            f.unlink()
        except OSError:
            pass
    return places


def is_agency(p: dict) -> bool:
    cats = " ".join([p.get("category") or ""] + list(p.get("categories") or [])).lower()
    return any(w in cats for w in AGENCY_WORDS)


def state_code(p: dict) -> str | None:
    ca = p.get("complete_address") or {}
    st = (ca.get("state") or "").strip()
    if st.upper() in STATE_NAMES:
        return st.upper()
    if st.lower() in NAME_TO_CODE:
        return NAME_TO_CODE[st.lower()]
    m = re.search(r",\s*([A-Z]{2})\s+\d{5}", p.get("address") or "")
    return m.group(1) if m and m.group(1) in STATE_NAMES else None


def clean_site(url: str | None) -> tuple[str | None, str | None]:
    if not url:
        return None, None
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    try:
        pu = urlparse(u)
    except ValueError:
        return None, None
    host = (pu.hostname or "").lower()
    if not host or "google." in host:
        return None, None
    return f"{pu.scheme}://{pu.netloc}/", base_domain(host)


def qualify(places: list[dict], store, blocked: set[str], sent_before: set[str],
            lead_domains: set[str], log=print) -> int:
    """Clean, dedupe and save scraped places. Returns how many came out 'ready'."""
    ids, emails, domains = store.known()
    pending = []
    for p in places:
        pid = p.get("place_id") or p.get("cid")
        name = (p.get("title") or "").strip()
        if not pid or not name or pid in ids:
            continue
        if (p.get("complete_address") or {}).get("country") not in (None, "", "US"):
            continue
        if not is_agency(p):
            continue
        website, domain = clean_site(p.get("web_site"))
        if domain and domain in domains:
            continue
        ids.add(pid)
        if domain:
            domains.add(domain)
        ca = p.get("complete_address") or {}
        cands = [(str(e).strip().lower(), "google") for e in (p.get("emails") or [])]
        cands = [c for c in cands if _plausible(c[0])]
        best = pick_email(cands, domain) if cands else None
        pending.append({
            "place_id": pid, "name": name, "category": p.get("category"),
            "website": website, "domain": domain, "phone": p.get("phone"),
            "street": ca.get("street"), "city": ca.get("city"), "state": state_code(p),
            "rating": p.get("review_rating"), "reviews": p.get("review_count"),
            "email": best[0] if best else None, "email_source": "google" if best else None,
        })

    # Second try for agencies whose profile had no usable email.
    need = [a for a in pending if not a["email"] and a["website"]]
    if need:
        log(f"  checking {len(need)} agency sites for a published email")

        def work(a):
            try:
                res = check_site(a["website"], a["domain"], sess=_session())
                return a, res.email
            except Exception:
                return a, None

        with cf.ThreadPoolExecutor(max_workers=6) as pool:
            for a, email in pool.map(work, need):
                if email:
                    a["email"], a["email_source"] = email, "website"

    ready = 0
    for a in pending:
        e = a["email"]
        if not e:
            a["status"] = "no_email"
        elif e in blocked:
            a["status"], a["status_detail"] = "blocked", "on the outreach block list"
        elif e in sent_before or e in emails:
            a["status"], a["status_detail"] = "duplicate", "already emailed or on file"
        elif a["domain"] and a["domain"] in lead_domains:
            a["status"], a["status_detail"] = "duplicate", "already a Lead Finder business"
        elif not has_mx(e.split("@")[1]):
            a["status"], a["status_detail"] = "bad_email", "email domain doesn't accept mail"
        else:
            a["status"] = "ready"
            ready += 1
            log(f"  + {a['name'][:40]:<40} {e}  {a['city'] or ''}, {a['state'] or ''}")
        if e:
            emails.add(e)
        store.insert(a)
    return ready
