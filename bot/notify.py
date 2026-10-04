"""
One-line status ping to your phone after each run, via ntfy.sh (a free
push-notification relay - install the ntfy app and subscribe to the topic
in config.yaml). Carrier email-to-SMS gateways were tried first and proved
unreliable: T-Mobile accepted the mail with no bounce and silently dropped
it, which is a known behavior of carrier gateways filtering unrecognized
senders as spam.

This must never break a run: any failure here is logged and swallowed,
never raised.
"""
from __future__ import annotations

import os
import urllib.request


def notify(cfg, client, text, log=None):
    ncfg = cfg.get("notify", {}) or {}
    if not ncfg.get("enabled"):
        return

    # The topic name is effectively a password (anyone who knows it can read
    # and post), so it lives in .env, not in the committed config.yaml.
    topic = os.environ.get("NTFY_TOPIC") or ncfg.get("ntfy_topic")
    if topic:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{topic}",
                data=text.encode("utf-8"),
                headers={"Title": "Nimble Email Sender"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            if log:
                log(f"  pushed to ntfy.sh/{topic}: {text}")
            return
        except Exception as e:
            if log:
                log(f"  ntfy push failed (non-fatal): {e}")

    # Fallback: carrier email-to-SMS gateway, if configured.
    to = os.environ.get("NOTIFY_SMS_TO") or ncfg.get("to")
    if to:
        try:
            client.send(to, "", text, text)
            if log:
                log(f"  texted {to}: {text}")
        except Exception as e:
            if log:
                log(f"  notify failed (non-fatal): {e}")
