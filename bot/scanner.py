"""
Reply and bounce scanning.

Runs before every send batch. Two jobs:

  1. Opt-outs. Anyone who replies asking to be left alone is blocked
     immediately and permanently. This is the legal requirement, and doing it
     on a timer rather than by hand is the whole point: a reply that arrives
     Saturday must not get another message Monday morning.

  2. Hard bounces. A 5.x.x permanent failure means the mailbox does not
     exist. Retrying a dead address repeatedly is a reputation cost with zero
     upside, so those addresses are blocked too.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta

_ADDR = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Permanent failures worth blocking on. 4.x.x is transient; leave those alone.
_HARD_BOUNCE = re.compile(
    r"\b5\.[0-9]\.[0-9]\b|550[ -]|551[ -]|553[ -]|554[ -]|"
    r"address not found|user unknown|does not exist|mailbox unavailable|"
    r"recipient address rejected|permanent failure|message blocked",
    re.I,
)


def _body_text(payload) -> str:
    """Flatten a Gmail payload into searchable text."""
    chunks = []

    def walk(p):
        if not p:
            return
        data = (p.get("body") or {}).get("data")
        if data:
            try:
                chunks.append(base64.urlsafe_b64decode(data).decode("utf-8", "replace"))
            except Exception:
                pass
        for part in p.get("parts") or []:
            walk(part)

    walk(payload)
    return "\n".join(chunks)


def _header(msg, name):
    for h in (msg.get("payload", {}).get("headers") or []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def scan(client, store, cfg, *, days_back=14, log=print):
    """Scan recent mail, block opt-outs and hard bounces. Returns a summary."""
    phrases = [p.lower() for p in cfg["safety"]["optout_phrases"]]
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")

    summary = {"scanned": 0, "optouts": 0, "bounces": 0, "new_blocks": []}

    queries = [
        f"in:inbox after:{since}",
        f"from:mailer-daemon after:{since}",
        f"from:postmaster after:{since}",
    ]

    seen_ids = set()
    failures = []
    for q in queries:
        try:
            msgs = client.search(q, max_results=500)
        except Exception as e:
            log(f"  scan query failed ({q}): {e}")
            failures.append(e)
            continue

        for m in msgs:
            mid = m["id"]
            if mid in seen_ids or store.already_scanned(mid):
                continue
            seen_ids.add(mid)

            try:
                full = client.get_message(mid)
            except Exception:
                continue

            summary["scanned"] += 1
            store.mark_scanned(mid)

            sender = _header(full, "From")
            subject = _header(full, "Subject")
            text = _body_text(full.get("payload"))
            blob = f"{subject}\n{text}"

            is_daemon = ("mailer-daemon" in sender.lower()
                         or "postmaster" in sender.lower())

            # --- hard bounce ---
            if is_daemon and _HARD_BOUNCE.search(blob):
                for addr in _extract_failed(blob, client.sender_address):
                    if addr not in store.blocked_emails():
                        store.block(addr, "hard bounce / permanent failure",
                                    "bounce", detail=subject[:300])
                        summary["bounces"] += 1
                        summary["new_blocks"].append((addr, "bounce"))
                        log(f"  blocked (bounce): {addr}")
                continue

            # --- opt-out reply ---
            if not is_daemon:
                low = text.lower()
                # Look only at the top of the reply, so our own footer's
                # "unsubscribe" wording in the quoted original does not
                # trigger a false positive.
                top = low.split("wrote:")[0][:1200]
                if any(p in top for p in phrases):
                    addrs = _ADDR.findall(sender) or _ADDR.findall(blob)
                    for addr in addrs[:1]:
                        a = addr.lower()
                        if a == client.sender_address.lower():
                            continue
                        if a not in store.blocked_emails():
                            store.block(a, "opt-out reply", "optout",
                                        detail=top[:300])
                            summary["optouts"] += 1
                            summary["new_blocks"].append((a, "optout"))
                            log(f"  blocked (opt-out): {a}")

    if failures and len(failures) == len(queries):
        # Could not read the mailbox at all. Surface it so the caller refuses
        # to send rather than treating "saw nothing" as "nothing to see".
        raise RuntimeError(f"all scan queries failed; first error: {failures[0]}")

    return summary


def _extract_failed(blob, own_address):
    """Pull the failed recipient(s) out of a bounce notice."""
    out, own = [], own_address.lower()
    for a in _ADDR.findall(blob):
        a = a.lower().rstrip(".,;:")
        if a == own or "mailer-daemon" in a or "postmaster" in a:
            continue
        # Message-ID style tokens (CAKqLHq...@mail.gmail.com) and Google's
        # own infrastructure addresses are never real recipients.
        if a.endswith(("@mail.gmail.com", "googlemail.com", "google.com")):
            continue
        if len(a.split("@")[0]) > 40:
            continue
        if a not in out:
            out.append(a)
    return out[:2]
