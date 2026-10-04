"""The business outreach email.

Different list, different email: the realtor template in bot/message.py is
approved and fixed, and it stays untouched. This one goes to small-business
owners found by the Lead Finder.

What changes per lead: the business name in the greeting and the closing
question, and ONE opening observation chosen from what the site check
actually found. Every hook below only fires when the crawler saw that exact
thing, so nothing in the email is made up.

Writing rules (Jake's): short, sounds like a person, no em dashes.
"""
from __future__ import annotations

import re

from bot.message import FOOTER_HTML, FOOTER_TEXT, SIGNATURE_HTML, SIGNATURE_TEXT

SUBJECT = "quick question about your website"
SUBJECT_NO_SITE = "quick question about {name}"
SITE_URL = "https://example.com/"

# In priority order: the first issue the lead has wins.
HOOKS = [
    ("site_down", "I went to pull up your website and it wouldn't load for me, so anyone searching for you is probably hitting the same wall."),
    ("parked", "I went to pull up your website and the domain isn't showing your business anymore."),
    ("social_only", "It looks like your {platform} page is doing the job of a website right now, and a lot of people searching Google never make it that far."),
    ("no_website", "I couldn't find a website for you anywhere, and that's usually the first thing people look for before they call."),
    ("no_https", "When I opened it my browser flagged it as \"Not secure,\" which scares off a lot of people before they read anything."),
    ("no_mobile", "It's pretty hard to use on a phone, and that's where most of your customers are going to find you."),
    ("outdated", "The footer still says {year}, so it might be due for a refresh."),
    ("builder", "It looks like it's built on {platform}. That's a fine start, but those sites tend to look like everyone else's and they're tough to rank on Google."),
    ("slow", "It took a while to load when I opened it, and most people give up after a few seconds."),
]
DEFAULT_HOOK = "It's a good start, but I think it could be bringing you a lot more customers than it is right now."
NO_SITE_ISSUES = {"site_down", "parked", "social_only", "no_website"}

_SUFFIX = re.compile(
    r"[,\s]+(l\.?l\.?c\.?|inc\.?|incorporated|corp\.?|corporation|co\.|company|p\.?l\.?l\.?c\.?|"
    r"p\.?a\.?|ltd\.?|llp|pllc)\s*$", re.I)
SMALL_WORDS = {"and", "of", "the", "a", "an", "in", "on", "at", "for", "to", "by", "or", "&"}


def clean_business_name(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    s = re.split(r"\s+[|•·]\s+", s)[0]                 # "Joe's Roofing | Tampa FL"
    head = re.split(r"\s+[-–—]\s+", s)[0]
    if len(head.split()) >= 2:                          # "Joe's Roofing - Tampa" but not "Bob - Lawn Care"
        s = head
    for _ in range(2):
        s = _SUFFIX.sub("", s).strip(" ,.-")
    if not s or len(s) > 45 or not re.search(r"[A-Za-z]", s):
        return None
    if s.isupper() and len(s) > 4:
        words = s.lower().split()
        s = " ".join(w if (i and w in SMALL_WORDS) else w[:1].upper() + w[1:]
                     for i, w in enumerate(words))
    return s


def pick_hook(issues: list[str], platform: str | None, year: int | None) -> tuple[str, str]:
    for key, text in HOOKS:
        if key in issues:
            if key == "outdated" and not year:
                continue
            if key in ("builder", "social_only") and not platform:
                continue
            return key, text.format(platform=platform, year=year)
    return "default", DEFAULT_HOOK


def render_lead(lead) -> tuple[str, str, str]:
    """(subject, text, html) for one lead row or dict."""
    g = lead.get if isinstance(lead, dict) else (lambda k, d=None: lead[k] if k in lead.keys() else d)
    import json
    issues = g("issues") or []
    if isinstance(issues, str):
        try:
            issues = json.loads(issues)
        except json.JSONDecodeError:
            issues = []
    name = clean_business_name(g("name"))
    key, hook = pick_hook(issues, g("platform"), g("copyright_year"))
    no_site = key in NO_SITE_ISSUES

    greeting = f"Hey {name} team," if name else "Hey there,"
    who = name or "your business"
    if no_site:
        opener = f"I came across {who} on Google. {hook}"
        subject = SUBJECT_NO_SITE.format(name=name) if name else SUBJECT
    else:
        opener = f"I came across {who} on Google and checked out your website. {hook}"
        subject = SUBJECT
    pitch = ("I'm Jake, I run TheraWeb, a small web design studio in Tampa. We hand code custom "
             "sites for local businesses, no templates. We recently helped a Florida real estate "
             "team grow their site to over 28,000 weekly clicks.")
    proof = "You can see some of our client sites here:"
    close = f"Would you be open to a quick 15 minute call to see what we could do for {name or 'you'}?"

    text = "\n\n".join([greeting, opener, pitch, f"{proof} {SITE_URL}", close,
                        SIGNATURE_TEXT, FOOTER_TEXT])
    p = '<p style="margin:0 0 14px 0;">{}</p>'
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:22px;color:#222222;">'
        + p.format(_esc(greeting)) + p.format(_esc(opener)) + p.format(_esc(pitch))
        + p.format(f'{_esc(proof)} <a href="{SITE_URL}" style="color:#7FAF57;">example.com</a>')
        + '<p style="margin:0 0 20px 0;">' + _esc(close) + "</p>"
        + SIGNATURE_HTML + FOOTER_HTML + "</div>"
    )
    return subject, text, html


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def self_check() -> None:
    sample = {"name": "SUNSHINE POOL SERVICE LLC", "issues": ["no_mobile", "builder"],
              "platform": "Wix", "copyright_year": 2019}
    subj, text, html = render_lead(sample)
    for body in (text, html):
        assert "—" not in body and "–" not in body, "no em/en dashes in outreach copy"
        assert "unsubscribe" in body.lower(), "CAN-SPAM opt-out missing"
        assert "[postal address]" in body, "CAN-SPAM postal address missing"
    assert "Hey Sunshine Pool Service team," in text
    assert "example.com" in text
