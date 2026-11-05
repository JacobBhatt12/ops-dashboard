"""Visit a business's website, find a published email, and note what's wrong
with the site so the email can open with something specific and true.

Rules this follows, deliberately:
  * Only emails that are actually published (mailto links or visible text).
    Never guesses info@domain, never pattern-fills, never enriches.
  * Reads at most 3 pages per site: home, then up to two contact/about pages.
  * Honors robots.txt and identifies itself with a real User-Agent.
  * An email on a third-party domain (a web designer's footer, a
    directory) is ignored unless it's a common personal mailbox provider.
"""
from __future__ import annotations

import html as htmllib
import re
import socket
import time
from datetime import date
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from .overture import is_social

from bot.message import BUSINESS_WEBSITE  # noqa: E402  (also loads .env)

USER_AGENT = f"TheraWebLeadCheck/1.0 (+https://{BUSINESS_WEBSITE})"
TIMEOUT = 12
MAX_BYTES = 1_500_000

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}")
_OBFUSCATED_AT = re.compile(r"[\[\(\{]\s*at\s*[\]\)\}]", re.I)
_MAILTO = re.compile(r"""mailto:([^"'?>\s]+)""", re.I)
_HREF = re.compile(r"""<a\b[^>]*href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_VIEWPORT = re.compile(r"""<meta[^>]+name\s*=\s*["']viewport["']""", re.I)
_COPYRIGHT = re.compile(r"(?:©|&copy;|&#169;|copyright)\s*(?:\d{4}\s*[-–—]\s*)?((?:19|20)\d{2})", re.I)
_TAGS = re.compile(r"<(script|style|noscript)\b.*?</\1>|<[^>]+>", re.I | re.S)

FREEMAIL = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com",
    "me.com", "mac.com", "live.com", "msn.com", "comcast.net", "att.net", "bellsouth.net",
    "sbcglobal.net", "verizon.net", "cox.net", "charter.net", "earthlink.net", "ymail.com",
    "rocketmail.com", "protonmail.com", "proton.me", "mail.com", "frontier.com",
    "embarqmail.com", "optonline.net", "windstream.net", "centurylink.net", "spectrum.net",
    "roadrunner.com", "twc.com", "q.com", "zoho.com", "gmx.com", "yahoo.co", "aim.com",
}
JUNK_DOMAINS = {
    "example.com", "domain.com", "email.com", "yourdomain.com", "mysite.com", "website.com",
    "company.com", "sentry.io", "wixpress.com", "wix.com", "godaddy.com", "squarespace.com",
    "schema.org", "w3.org", "sentry-next.wixpress.com", "latofonts.com", "typekit.com",
    "yoursite.com", "test.com", "address.com", "mail.example", "weebly.com", "editmysite.com",
}
JUNK_LOCAL = re.compile(
    r"^(no-?reply|do-?not-?reply|donotreply|noreply|example|yourname|your\.?name|name|email|"
    r"user|username|test|someone|john\.?doe|jane\.?doe|privacy|legal|abuse|webmaster|"
    r"postmaster|hostmaster|careers|jobs|hr|recruiting|dmca|accessibility|ada|unsubscribe|"
    r"bounce|mailer-daemon|wordpress)$", re.I)
FILE_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ico", "pdf", "mp4", "avif"}
PREFERRED_LOCAL = ("info", "contact", "hello", "office", "admin", "service", "sales",
                   "appointments", "booking", "team", "mail")

PLATFORMS = [
    ("Wix", ("static.wixstatic.com", "wix.com website builder", "_wixcss", "x-wix-")),
    ("Squarespace", ("static1.squarespace.com", "squarespace-cdn.com", "<!-- this is squarespace")),
    ("GoDaddy", ("img1.wsimg.com", "godaddy website builder", "websites.godaddy.com")),
    ("Weebly", ("editmysite.com", "weebly.com")),
    ("Jimdo", ("jimdo",)),
    ("Site123", ("site123",)),
    ("Duda", ("multiscreensite.com", "dudaone", "d-cdn.com/files")),
    ("Webnode", ("webnode",)),
    ("Shopify", ("cdn.shopify.com",)),
    ("WordPress", ("wp-content", "wp-includes")),
]
BUILDERS = {"Wix", "Squarespace", "GoDaddy", "Weebly", "Jimdo", "Site123", "Duda", "Webnode"}
PARKED = ("domain is for sale", "this domain may be for sale", "buy this domain",
          "domain has expired", "parked free", "parkingcrew", "sedoparking",
          "godaddy.com/domainsearch", "this domain is parked", "domain name is available")


class CheckResult:
    def __init__(self):
        self.email: str | None = None
        self.email_source: str | None = None
        self.platform: str | None = None
        self.issues: list[str] = []
        self.copyright_year: int | None = None
        self.reachable = False
        self.robots_blocked = False
        self.error: str | None = None


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT,
                      "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                      "Accept-Language": "en-US,en;q=0.8"})
    return s


def _get(sess, url):
    """GET with a size cap. Returns (response, text, elapsed_seconds) or raises."""
    t0 = time.monotonic()
    r = sess.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True)
    chunks, size = [], 0
    for chunk in r.iter_content(65536, decode_unicode=False):
        chunks.append(chunk)
        size += len(chunk)
        # The timeout is per read, so a server trickling bytes could hold a
        # worker for minutes. Cap the whole download too.
        if size > MAX_BYTES or time.monotonic() - t0 > TIMEOUT + 8:
            break
    r.close()
    raw = b"".join(chunks)
    enc = r.encoding or "utf-8"
    try:
        text = raw.decode(enc, "replace")
    except LookupError:
        text = raw.decode("utf-8", "replace")
    return r, text, time.monotonic() - t0


def base_domain(host: str) -> str:
    host = (host or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "net", "org"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def extract_emails(page_html: str) -> list[tuple[str, str]]:
    """All plausible emails on a page as (email, how_found), mailto first."""
    found: list[tuple[str, str]] = []
    for m in _MAILTO.finditer(page_html):
        found.append((htmllib.unescape(m.group(1)), "mailto"))
    text = htmllib.unescape(page_html)
    if _OBFUSCATED_AT.search(text):
        text = re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", text, flags=re.I)
        text = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", text, flags=re.I)
    # Only scan around each "@": running _EMAIL over a whole 1.5 MB page
    # starves thera-server's quarter of a CPU.
    i = text.find("@")
    while i != -1:
        lo = max(0, i - 64)
        m = _EMAIL.search(text, lo, i + 216)
        while m and m.end() <= i:
            m = _EMAIL.search(text, m.end(), i + 216)
        if m and m.start() <= i:
            found.append((m.group(0), "page"))
        i = text.find("@", i + 1)
    out, seen = [], set()
    for e, how in found:
        e = e.strip().strip(".,;:").lower()
        e = re.sub(r"^(%20|u003e|>)+", "", e)
        e = re.sub(r"^(e-?mail|mailto)\s*:\s*(%20)*", "", e)
        if e in seen or not _plausible(e):
            continue
        seen.add(e)
        out.append((e, how))
    return out


def _plausible(e: str) -> bool:
    if e.count("@") != 1:
        return False
    local, dom = e.split("@")
    if not local or not dom or ".." in e:
        return False
    if dom.rsplit(".", 1)[-1] in FILE_TLDS:
        return False
    if dom in JUNK_DOMAINS or base_domain(dom) in JUNK_DOMAINS:
        return False
    if JUNK_LOCAL.match(local):
        return False
    if re.search(r"[0-9a-f]{16,}", local):  # tracking / sentry ids
        return False
    return True


def pick_email(cands: list[tuple[str, str]], site_domain: str | None) -> tuple[str, str] | None:
    """Best email for the business: on its own domain first, then a personal
    mailbox (gmail etc). Anything on another company's domain is dropped."""
    site_base = base_domain(site_domain) if site_domain else None

    def score(item):
        e, how = item
        local, dom = e.split("@")
        own = site_base is not None and base_domain(dom) == site_base
        s = 0
        if own:
            s += 100
        elif dom in FREEMAIL or base_domain(dom) in FREEMAIL:
            s += 50
        else:
            return -1
        if how == "mailto":
            s += 10
        if local.startswith(PREFERRED_LOCAL):
            s += 5
        if local.startswith(("support", "billing", "accounts", "marketing", "press", "media")):
            s -= 8
        return s

    ranked = sorted(((score(c), c) for c in cands), key=lambda x: -x[0])
    for s, c in ranked:
        if s >= 0:
            return c
    return None


def contact_links(page_html: str, page_url: str, site_domain: str) -> list[str]:
    out = []
    site_base = base_domain(site_domain)
    for href, label in _HREF.findall(page_html):
        label_text = _TAGS.sub(" ", label).lower()
        target = href.lower()
        if not any(k in target or k in label_text for k in ("contact", "about", "reach", "get-in-touch", "location")):
            continue
        absu = urljoin(page_url, href.strip())
        try:
            host = urlparse(absu).hostname or ""
        except ValueError:
            continue
        if base_domain(host) != site_base or absu.startswith(("mailto:", "tel:")):
            continue
        if absu not in out:
            out.append(absu)
    # Contact pages before about pages.
    out.sort(key=lambda u: 0 if "contact" in u.lower() else 1)
    return out[:2]


def detect_platform(page_html: str, headers) -> str | None:
    low = page_html.lower()
    hdr = " ".join(f"{k}:{v}" for k, v in (headers or {}).items()).lower()
    for name, marks in PLATFORMS:
        if any(m in low or m in hdr for m in marks):
            return name
    return None


def copyright_year(page_html: str) -> int | None:
    years = [int(y) for y in _COPYRIGHT.findall(page_html)]
    return max(years) if years else None


def has_mx(domain: str, _cache: dict = {}) -> bool:
    """Does this domain accept mail? MX record, or an A record as the RFC fallback.

    Only a definite "this domain doesn't exist / has no mail host" answer
    returns False. If our own DNS is having trouble we keep the lead.
    """
    domain = domain.lower()
    if domain in FREEMAIL:
        return True
    if domain in _cache:
        return _cache[domain]
    try:
        import dns.resolver  # dnspython
    except ImportError:
        try:
            socket.getaddrinfo(domain, 25)
            ok = True
        except socket.gaierror as e:
            ok = e.errno not in (socket.EAI_NONAME,)
        _cache[domain] = ok
        return ok

    def lookup(rtype):
        try:
            return bool(dns.resolver.resolve(domain, rtype, lifetime=8))
        except dns.resolver.NXDOMAIN:
            return False
        except dns.resolver.NoAnswer:
            return None
        except Exception:
            return "error"

    mx = lookup("MX")
    if mx is True or mx == "error":
        ok = True
    elif mx is False:
        ok = False
    else:
        a = lookup("A")
        ok = a is True or a == "error"
    _cache[domain] = ok
    return ok


def _robots(sess, root: str) -> RobotFileParser | None:
    rp = RobotFileParser()
    try:
        r = sess.get(urljoin(root, "/robots.txt"), timeout=8)
        if r.status_code >= 400:
            return None
        rp.parse(r.text.splitlines())
        return rp
    except requests.RequestException:
        return None


def check_site(website: str | None, domain: str | None, *, sess=None) -> CheckResult:
    res = CheckResult()
    sess = sess or _session()

    if not website or not domain:
        res.issues.append("no_website")
        return res
    if is_social(domain):
        res.issues.append("social_only")
        res.platform = domain.split(".")[-2].capitalize() if "." in domain else None
        return res

    # Fetch the homepage, https first.
    resp = text = None
    elapsed = 0.0
    tried = []
    host = urlparse(website).netloc or domain
    for url in (f"https://{host}/", f"http://{host}/"):
        tried.append(url)
        try:
            resp, text, elapsed = _get(sess, url)
            if resp.status_code < 400:
                break
            resp = None
        except requests.exceptions.SSLError:
            continue
        except requests.RequestException as e:
            res.error = type(e).__name__
            continue
    if resp is None or text is None:
        res.issues.append("site_down")
        res.error = res.error or "no response"
        return res

    res.reachable = True
    final = resp.url
    low = text.lower()

    if any(p in low for p in PARKED):
        res.issues.append("parked")
        res.reachable = False
        res.error = "domain parked"
        return res

    root = f"{urlparse(final).scheme}://{urlparse(final).netloc}/"
    rp = _robots(sess, root)
    if rp is not None and not rp.can_fetch(USER_AGENT, final):
        res.robots_blocked = True
        return res

    # Issues worth opening an email with.
    if urlparse(final).scheme != "https":
        res.issues.append("no_https")
    if not _VIEWPORT.search(text):
        res.issues.append("no_mobile")
    res.platform = detect_platform(text, resp.headers)
    yr = copyright_year(text)
    res.copyright_year = yr
    if yr and yr <= date.today().year - 3:
        res.issues.append("outdated")
    if res.platform in BUILDERS:
        res.issues.append("builder")
    if elapsed > 4.0:
        res.issues.append("slow")

    # Email: homepage, then up to two contact/about pages.
    final_domain = (urlparse(final).hostname or domain)
    cands = extract_emails(text)
    best = pick_email(cands, final_domain)
    if not best:
        pages = contact_links(text, final, final_domain)
        if not pages:
            pages = [urljoin(root, "contact"), urljoin(root, "contact-us")]
        for p in pages[:2]:
            if rp is not None and not rp.can_fetch(USER_AGENT, p):
                continue
            try:
                r2, t2, _ = _get(sess, p)
            except requests.RequestException:
                continue
            if r2.status_code >= 400:
                continue
            best = pick_email(extract_emails(t2), final_domain)
            if best:
                break
    if best:
        res.email, res.email_source = best
    return res
