"""Gmail API client — OAuth2 refresh-token flow, direct HTTP (no google SDK).

Used to send vendor POs from dropship@speedaddicts.com (or whatever is
configured as GMAIL_SEND_AS). Modeled on the Rithum client's auth
pattern: keep a short-lived access token, refresh it on 401.
"""
import base64
import logging
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import requests

import config

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailClient:
    """Thread-safe Gmail sender with automatic token refresh."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        send_as: str | None = None,
    ):
        self.client_id = client_id or config.GMAIL_CLIENT_ID
        self.client_secret = client_secret or config.GMAIL_CLIENT_SECRET
        self.refresh_token = refresh_token or config.GMAIL_REFRESH_TOKEN
        self.send_as = send_as or config.GMAIL_SEND_AS
        self._access_token: str | None = None
        self._lock = threading.Lock()

    def authenticate(self) -> str:
        """Exchange refresh token for a new access token."""
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise RuntimeError(
                "Gmail client not configured — set GMAIL_CLIENT_ID, "
                "GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN",
            )
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        with self._lock:
            self._access_token = token
        logger.info("Gmail: authenticated as %s", self.send_as)
        return token

    def _headers(self) -> dict:
        with self._lock:
            token = self._access_token
        if not token:
            token = self.authenticate()
        return {"Authorization": f"Bearer {token}"}

    def check_health(self) -> dict:
        """Lightweight auth probe — exchanges the refresh token."""
        try:
            self.authenticate()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def build_message(
        self,
        *,
        to: list[str] | str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        cc: list[str] | str | None = None,
        bcc: list[str] | str | None = None,
        reply_to: str | None = None,
        from_addr: str | None = None,
    ) -> EmailMessage:
        """Assemble an RFC-2822 email suitable for Gmail's /send endpoint."""
        msg = EmailMessage()
        msg["From"] = from_addr or self.send_as
        msg["To"] = ", ".join(to) if isinstance(to, list) else to
        if cc:
            msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc
        if bcc:
            msg["Bcc"] = ", ".join(bcc) if isinstance(bcc, list) else bcc
        if reply_to:
            msg["Reply-To"] = reply_to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="speedaddicts.com")
        msg.set_content(body_text)
        if body_html:
            msg.add_alternative(body_html, subtype="html")
        return msg

    def send(self, message: EmailMessage, max_retries: int = 3) -> dict:
        """Send a pre-built RFC-2822 message. Returns Gmail API response."""
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        payload = {"raw": raw}

        for attempt in range(max_retries):
            headers = self._headers()
            resp = requests.post(SEND_URL, headers=headers, json=payload, timeout=60)

            if resp.status_code == 401:
                logger.warning("Gmail: 401 — refreshing token (attempt %d)", attempt + 1)
                self.authenticate()
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "Gmail: %d — retrying in %ds", resp.status_code, wait,
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError(f"Gmail send failed after {max_retries} attempts")
