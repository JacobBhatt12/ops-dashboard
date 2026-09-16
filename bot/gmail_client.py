"""
Gmail API wrapper: OAuth, sending, and reading replies/bounces.

Scopes:
  gmail.send     - sending
  gmail.readonly - reading bounce notices and replies for the opt-out scanner

The token is stored next to the client secret and refreshed automatically.
First run opens a browser for consent; after that it is unattended.
"""
from __future__ import annotations

import base64
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


class GmailClient:
    def __init__(self, client_secret_path, token_path, sender_address,
                 sender_name="", dry_run=False):
        self.sender_address = sender_address
        self.sender_name = sender_name
        self.dry_run = dry_run
        self._svc = None
        self._client_secret = Path(client_secret_path)
        self._token = Path(token_path)

    # ---------- auth ----------

    @property
    def service(self):
        if self._svc is None:
            self._svc = build("gmail", "v1", credentials=self._creds(),
                              cache_discovery=False)
        return self._svc

    def _creds(self):
        creds = None
        if self._token.exists():
            creds = Credentials.from_authorized_user_file(str(self._token), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self._client_secret.exists():
                    raise FileNotFoundError(
                        f"Missing OAuth client secret at {self._client_secret}. "
                        "See README section 2."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._client_secret), SCOPES)
                creds = flow.run_local_server(port=0)
            self._token.parent.mkdir(parents=True, exist_ok=True)
            self._token.write_text(creds.to_json(), encoding="utf-8")
        return creds

    # ---------- sending ----------

    def send(self, to_address, subject, text_body, html_body, *, retries=3):
        """
        Send one message. Returns (message_id, thread_id).

        In dry-run mode nothing leaves the machine and a fake id is returned.
        """
        if self.dry_run:
            return ("DRYRUN", "DRYRUN")

        msg = MIMEMultipart("alternative")
        msg["To"] = to_address
        msg["From"] = (f"{self.sender_name} <{self.sender_address}>"
                       if self.sender_name else self.sender_address)
        msg["Subject"] = subject
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        last_err = None
        for attempt in range(retries):
            try:
                res = (self.service.users().messages()
                       .send(userId="me", body={"raw": raw}).execute())
                return (res.get("id"), res.get("threadId"))
            except HttpError as e:
                last_err = e
                status = getattr(e.resp, "status", None)
                # 4xx other than rate limiting will not succeed on retry.
                if status and 400 <= status < 500 and status not in (403, 429):
                    raise
                time.sleep(2 ** attempt * 5)
            except Exception as e:
                last_err = e
                time.sleep(2 ** attempt * 5)
        raise RuntimeError(f"send to {to_address} failed after {retries} attempts: {last_err}")

    # ---------- reading ----------

    def search(self, query, max_results=200):
        out, token = [], None
        while True:
            req = (self.service.users().messages()
                   .list(userId="me", q=query, maxResults=min(500, max_results),
                         pageToken=token).execute())
            out.extend(req.get("messages", []))
            token = req.get("nextPageToken")
            if not token or len(out) >= max_results:
                break
        return out[:max_results]

    def get_message(self, mid, fmt="full"):
        return (self.service.users().messages()
                .get(userId="me", id=mid, format=fmt).execute())
