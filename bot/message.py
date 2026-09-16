"""
The message itself.

The body copy, the subject, the link and the signature are fixed and approved.
Only the first name changes. Do not reword, shorten or "improve" anything in
this file without Jake saying so explicitly.

Two rules that have each been broken once in production and cost a batch:
  1. Only "28,000 weekly clicks" is bolded. Nothing else.
  2. The CAN-SPAM footer is mandatory. A cold email without a working opt-out
     and a physical postal address is a legal problem, not a style choice.
"""
from __future__ import annotations

SUBJECT = "Your branded website"

CASE_STUDY_URL = "https://bhatt-linderteam.com/"

# --- signature -------------------------------------------------------------

SIGNATURE_HTML = """<div class="hmail-signature-prefix">--</div>
<div>
  <table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-family:Arial,Helvetica,sans-serif;">
    <tbody>
      <tr>
        <td style="width:2px;background-color:#7FAF57;font-size:0;line-height:0;">&nbsp;</td>
        <td style="padding:0 0 0 16px;vertical-align:middle;">
          <div style="font-size:16px;line-height:20px;font-weight:bold;color:#111111;">Your Name</div>
          <div style="font-size:13px;line-height:18px;color:#444444;padding-top:2px;">Founder &amp; Lead Designer &middot; TheraWeb</div>
          <div style="font-size:13px;line-height:18px;color:#7FAF57;padding-bottom:6px;">Website Design &amp; Digital Branding</div>
          <div style="font-size:13px;line-height:20px;color:#444444;">
            <a href="https://example.com" style="color:#111111;text-decoration:none;font-weight:bold;">example.com</a>
            <span style="color:#cccccc;padding:0 6px;">|</span>
            <a href="tel:+15555550100" style="color:#444444;text-decoration:none;">(555) 555-0100</a>
          </div>
        </td>
      </tr>
    </tbody>
  </table>
</div>"""

SIGNATURE_TEXT = """--

Your Name
Founder & Lead Designer · TheraWeb
Website Design & Digital Branding
example.com ( https://example.com ) | (555) 555-0100 ( tel:+15555550100 )"""

# --- CAN-SPAM footer -------------------------------------------------------
# Required on every commercial message: a working opt-out and a valid physical
# postal address. Rendered below the signature, small and grey.

FOOTER_TEXT = ("You're receiving this because I thought TheraWeb might be a fit "
               "for your business. Reply \"unsubscribe\" and I won't contact you again.\n"
               "[business name] · [postal address]")

FOOTER_HTML = """<div style="font-size:11px;line-height:16px;color:#888888;padding-top:14px;font-family:Arial,Helvetica,sans-serif;">
  You're receiving this because I thought TheraWeb might be a fit for your business.
  Reply "unsubscribe" and I won't contact you again.<br>
  [business name] &middot; [postal address]
</div>"""

# --- body ------------------------------------------------------------------

_BODY_TEXT = """{greeting}

I was wondering if you're looking to develop or modify your branded website. This helps your prospects and clients actually find you on Google. Something professional, built around your expertise and experience, not just a template.

We recently helped Sid Bhatt, CCIM, SIOR and Trace Linder's team at Saunders Real Estate, Florida, boost their site to over 28,000 weekly clicks.

Check it out: {url}

Let me know if you're interested and we can grab a Google Meet call to start on your online presence.

{signature}

{footer}"""

_BODY_HTML = """<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:22px;color:#222222;">
  <p style="margin:0 0 14px 0;">{greeting}</p>
  <p style="margin:0 0 14px 0;">I was wondering if you're looking to develop or modify your branded website. This helps your prospects and clients actually find you on Google. Something professional, built around your expertise and experience, not just a template.</p>
  <p style="margin:0 0 14px 0;">We recently helped Sid Bhatt, CCIM, SIOR and Trace Linder's team at Saunders Real Estate, Florida, boost their site to over <b>28,000 weekly clicks</b>.</p>
  <p style="margin:0 0 14px 0;">Check it out: <a href="{url}" style="color:#7FAF57;">{url}</a></p>
  <p style="margin:0 0 20px 0;">Let me know if you're interested and we can grab a Google Meet call to start on your online presence.</p>
  {signature}
  {footer}
</div>"""


def render(contact) -> tuple[str, str, str]:
    """Return (subject, plain_text_body, html_body) for one contact."""
    greeting = contact.greeting
    text = _BODY_TEXT.format(greeting=greeting, url=CASE_STUDY_URL,
                             signature=SIGNATURE_TEXT, footer=FOOTER_TEXT)
    html = _BODY_HTML.format(greeting=_esc(greeting), url=CASE_STUDY_URL,
                             signature=SIGNATURE_HTML, footer=FOOTER_HTML)
    return SUBJECT, text, html


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def self_check() -> None:
    """Assert the invariants that have broken in production before."""
    class _C:
        greeting = "Hey Dana,"
    _, text, html = render(_C())
    assert html.count("<b>") == 1, "exactly one bolded phrase is allowed"
    assert "<b>28,000 weekly clicks</b>" in html, "the bolded phrase must be the click count"
    assert "free Google Meet" not in text and "free Google Meet" not in html, \
        "'free' was deliberately removed from the sign-off"
    assert "unsubscribe" in text.lower() and "unsubscribe" in html.lower(), \
        "CAN-SPAM opt-out missing"
    assert "[postal address]" in text and "[postal address]" in html, \
        "CAN-SPAM physical address missing"
    assert "Founder &amp; Lead Designer" in html, "signature missing from html"
    assert "Founder & Lead Designer" in text, "signature missing from text"
