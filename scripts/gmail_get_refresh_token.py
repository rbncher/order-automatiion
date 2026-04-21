"""One-shot OAuth helper — capture a Gmail refresh token for the app.

Run this on a machine with a browser (your laptop, not EC2). It will:
  1. Open the Google consent page.
  2. Spin up a tiny local HTTP server to receive the redirect.
  3. Exchange the auth code for a refresh token and print it.

Prerequisites in Google Cloud console (shared Speed Addicts project):
  * Enable the Gmail API.
  * Create an OAuth 2.0 Client ID of type "Desktop app".
  * Copy the Client ID + Client Secret.
  * Under OAuth consent screen > Test users, add dropship@speedaddicts.com
    (if the consent screen is still "Testing").

Usage:
  export GMAIL_CLIENT_ID=xxxxxx.apps.googleusercontent.com
  export GMAIL_CLIENT_SECRET=GOCSPX-xxxxxxxx
  python scripts/gmail_get_refresh_token.py

When the browser opens, sign in as dropship@speedaddicts.com and approve.
The script prints the refresh token when done — paste it into ~/.ascot_env
on EC2 as GMAIL_REFRESH_TOKEN, along with GMAIL_CLIENT_ID / SECRET.
"""
import os
import secrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class _Handler(BaseHTTPRequestHandler):
    """Capture the ?code= from the Google redirect and close the window."""
    server: HTTPServer  # narrow type for self.server

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        self.server.oauth_code = params.get("code", [None])[0]
        self.server.oauth_state = params.get("state", [None])[0]
        self.server.oauth_error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if self.server.oauth_error:
            body = f"<h2>Authorization error: {self.server.oauth_error}</h2>"
        elif self.server.oauth_code:
            body = (
                "<h2>OK — you can close this tab.</h2>"
                "<p>Return to the terminal to see the refresh token.</p>"
            )
        else:
            body = "<h2>No code received.</h2>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *_):
        pass  # silence server logs


def main() -> int:
    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    if not (client_id and client_secret):
        print(
            "ERROR: set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in your shell "
            "before running.",
            file=sys.stderr,
        )
        return 1

    state = secrets.token_urlsafe(16)
    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",          # required for a refresh token
        "prompt": "consent",               # force refresh token issuance
        "state": state,
        "include_granted_scopes": "true",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

    print(f"Opening browser to:\n  {auth_url}\n")
    print("Sign in as dropship@speedaddicts.com and approve.")
    print(f"Waiting for Google to redirect to {REDIRECT_URI} ...\n")

    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _Handler)
    server.oauth_code = None
    server.oauth_state = None
    server.oauth_error = None

    webbrowser.open(auth_url)
    server.handle_request()  # blocks for one request

    if server.oauth_error:
        print(f"Consent denied or error: {server.oauth_error}", file=sys.stderr)
        return 2
    if not server.oauth_code:
        print("No authorization code received.", file=sys.stderr)
        return 3
    if server.oauth_state != state:
        print("State mismatch — possible CSRF; aborting.", file=sys.stderr)
        return 4

    resp = requests.post(
        TOKEN_URL,
        data={
            "code": server.oauth_code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Token exchange failed: {resp.status_code} {resp.text}",
              file=sys.stderr)
        return 5

    tok = resp.json()
    refresh = tok.get("refresh_token")
    if not refresh:
        print(
            "No refresh_token returned. Usually this means the account has "
            "already granted this client before — revoke at "
            "https://myaccount.google.com/permissions and retry.",
            file=sys.stderr,
        )
        return 6

    print("Success.\n")
    print("Add the following to ~/.ascot_env on EC2:\n")
    print(f"GMAIL_CLIENT_ID={client_id}")
    print(f"GMAIL_CLIENT_SECRET={client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={refresh}")
    print("GMAIL_SEND_AS=dropship@speedaddicts.com\n")
    print("Access token (short-lived, for sanity testing):")
    print(tok.get("access_token"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
