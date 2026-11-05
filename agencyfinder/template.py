"""The email sent to web design and SEO agencies.

The pitch: stop paying for ads and lead apps; we built a system that finds
200+ qualified local leads a day, in their state or nationwide.

What changes per agency: the name, their city and state, and whether they're
called web designers or SEO/marketing agencies (from their Google category).

Writing rules: short, sounds like a person, no em dashes.
"""
from __future__ import annotations

from bot.message import POSTAL_ADDRESS, SIGNATURE_HTML, SIGNATURE_TEXT
from leadfinder.template import clean_business_name

from .cities import STATE_NAMES

SUBJECT = "finding new clients in {city}"
SUBJECT_FALLBACK = "finding new clients"

FOOTER_TEXT = ("You're receiving this because I thought this could help your agency find "
               "new clients. Reply \"unsubscribe\" and I won't contact you again.\n" + POSTAL_ADDRESS)
FOOTER_HTML = ('<div style="font-size:11px;line-height:16px;color:#888888;padding-top:14px;'
               'font-family:Arial,Helvetica,sans-serif;">You\'re receiving this because I thought '
               'this could help your agency find new clients. Reply "unsubscribe" and I won\'t '
               'contact you again.<br>{address}</div>')


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("·", "&middot;"))


def _kind(category: str | None) -> str:
    c = (category or "").lower()
    if any(w in c for w in ("seo", "search engine", "marketing", "advertising")):
        return "SEO and marketing agencies"
    return "web designers"


def render_agency(a) -> tuple[str, str, str]:
    """(subject, text, html) for one agency row or dict."""
    g = a.get if isinstance(a, dict) else (lambda k, d=None: a[k] if k in a.keys() else d)
    name = clean_business_name(g("name"))
    city = (g("city") or "").strip()
    state = STATE_NAMES.get((g("state") or "").upper(), "")
    where = f" in {city}" if city else ""
    region = state or "your state"

    greeting = f"Hey {name} team," if name else "Hey there,"
    who = name or "your agency"
    subject = SUBJECT.format(city=city) if city else SUBJECT_FALLBACK

    paras = [
        greeting,
        f"I came across {who} on Google Maps while looking at {_kind(g('category'))}{where}. "
        "Quick question: are you tired of spending hundreds of dollars a month on ads and lead "
        "apps, and thousands a year, just to find new clients?",
        "I was in the same spot. When I started TheraWeb I was a student with no time to hunt "
        "for leads, so I built a system that finds them for me. It pulls 200+ qualified local "
        "businesses a day, each with a published email and a specific problem with their "
        f"website you can open with, anywhere in {region} or across the whole country.",
        "Would you be open to a quick 15 minute call so I can show you how it works?",
    ]
    text = "\n\n".join(paras + [SIGNATURE_TEXT, FOOTER_TEXT])
    p = '<p style="margin:0 0 14px 0;">{}</p>'
    html = ('<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:22px;color:#222222;">'
            + "".join(p.format(_esc(x)) for x in paras[:-1])
            + '<p style="margin:0 0 20px 0;">' + _esc(paras[-1]) + "</p>"
            + SIGNATURE_HTML + FOOTER_HTML.format(address=_esc(POSTAL_ADDRESS)) + "</div>")
    return subject, text, html


def self_check() -> None:
    sample = {"name": "GROVE BRANDS LLC", "category": "Marketing agency",
              "city": "Tampa", "state": "FL"}
    subj, text, html = render_agency(sample)
    for body in (text, html):
        assert "—" not in body and "–" not in body, "no em/en dashes in outreach copy"
        assert "unsubscribe" in body.lower(), "CAN-SPAM opt-out missing"
    assert POSTAL_ADDRESS and POSTAL_ADDRESS in text and _esc(POSTAL_ADDRESS) in html, \
        "CAN-SPAM postal address missing: set BUSINESS_POSTAL_ADDRESS in .env"
    assert "Hey Grove Brands team," in text and "in Florida" in text
    assert subj == "finding new clients in Tampa"
