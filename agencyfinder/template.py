"""The email sent to web design and SEO agencies.

The pitch: stop paying for ads and lead apps; we built a system that finds
200+ local businesses a day that need web work, in their area or nationwide.

What changes per agency: the name, their city and state, and whether they're
called web designers or SEO/marketing agencies (from their Google category).
Agencies in our own state don't get the "all the way down in Florida" line,
since it wouldn't be true for them.

Writing rules: short, sounds like a person, no em dashes.
"""
from __future__ import annotations

from bot.message import POSTAL_ADDRESS, SENDER_NAME, SIGNATURE_HTML, SIGNATURE_TEXT
from leadfinder.template import clean_business_name

from .cities import STATE_NAMES

SUBJECT = "Finding clients without paying for ads"
HOME_STATE = "FL"  # where TheraWeb is; agencies here skip the distance line

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


def _reach(city: str, state: str) -> str:
    if city and state:
        return f"It works for {city}, anywhere in {state}, or anywhere in the country."
    if state:
        return f"It works anywhere in {state}, or anywhere in the country."
    if city:
        return f"It works for {city}, or anywhere in the country."
    return "It works in your area, or anywhere in the country."


def render_agency(a) -> tuple[str, str, str]:
    """(subject, text, html) for one agency row or dict."""
    g = a.get if isinstance(a, dict) else (lambda k, d=None: a[k] if k in a.keys() else d)
    name = clean_business_name(g("name"))
    city = (g("city") or "").strip()
    code = (g("state") or "").upper()
    state = STATE_NAMES.get(code, "")
    where = f" in {city}" if city else ""

    greeting = f"Hey {name} team," if name else "Hey there,"
    me = f"My name is {SENDER_NAME}, and I run" if SENDER_NAME else "I run"
    not_competing = ("Since I’m all the way down in Florida, I’m not reaching out to compete "
                     "with you." if code != HOME_STATE else "I’m not reaching out to compete with you.")

    paras = [
        greeting,
        f"{me} TheraWeb Design, a web design agency in Tampa. I found you on Google Maps while "
        f"looking at {_kind(g('category'))}{where}. {not_competing} I think I have something "
        "that could actually help.",
        "Quick question: how much are you spending on ads and lead apps to find new clients? "
        "For a lot of agencies it’s a few hundred a month, which adds up to thousands a year.",
        "I was in the same spot. When I started TheraWeb I was a full-time student with no time "
        "to hunt for leads, so I built a system that does it for me. Every day it pulls 200+ "
        "local businesses that need web work, each with a public email address and a specific "
        "problem on their website you can bring up in your first message. " + _reach(city, state),
        "Would you be open to a quick 15 minute call so I can show you how it works?",
    ]
    text = "\n\n".join(paras + [SIGNATURE_TEXT, FOOTER_TEXT])
    p = '<p style="margin:0 0 14px 0;">{}</p>'
    html = ('<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:22px;color:#222222;">'
            + "".join(p.format(_esc(x)) for x in paras[:-1])
            + '<p style="margin:0 0 20px 0;">' + _esc(paras[-1]) + "</p>"
            + SIGNATURE_HTML + FOOTER_HTML.format(address=_esc(POSTAL_ADDRESS)) + "</div>")
    return SUBJECT, text, html


def self_check() -> None:
    sample = {"name": "ANCHORAGE WEB DESIGN LLC", "category": "Website designer",
              "city": "Anchorage", "state": "AK"}
    subj, text, html = render_agency(sample)
    for body in (text, html):
        assert "—" not in body and "–" not in body, "no em/en dashes in outreach copy"
        assert "unsubscribe" in body.lower(), "CAN-SPAM opt-out missing"
    assert POSTAL_ADDRESS and POSTAL_ADDRESS in text and _esc(POSTAL_ADDRESS) in html, \
        "CAN-SPAM postal address missing: set BUSINESS_POSTAL_ADDRESS in .env"
    assert "Hey Anchorage Web Design team," in text
    assert "anywhere in Alaska" in text and "down in Florida" in text
    assert subj == SUBJECT
    _, fl, _ = render_agency({**sample, "city": "Tampa", "state": "FL"})
    assert "down in Florida" not in fl, "Florida agencies must not get the distance line"
