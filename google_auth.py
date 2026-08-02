"""
Shared Google OAuth2 - used by gcal.py (Calendar) and gmail.py (Gmail).

Hand-rolled OAuth2 "installed app" flow (just `requests` + the standard
library - no google-auth/google-api-python-client dependency), consistent
with the rest of this project's style (see brain.py, todoist.py).

One-time setup:
1. Google Cloud Console -> new project -> enable both the "Google Calendar
   API" and the "Gmail API".
2. APIs & Services -> Credentials -> Create OAuth client ID -> type
   "Desktop app". Copy the Client ID and Client Secret.
3. Put them in `.env` (already git-ignored):
       GOOGLE_CLIENT_ID=...
       GOOGLE_CLIENT_SECRET=...
4. Run `./venv/bin/python3 google_auth.py` once - it opens a browser for
   you to grant access (to both Calendar and Gmail at once), then stores a
   refresh token in `.google_token.json` (also git-ignored). After that,
   animation.py picks it up automatically - gcal.py and gmail.py share the
   same token, so you only ever authenticate once.
"""
import json
import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from todoist import load_env_file  # reuses the same tiny .env loader

TOKEN_FILE = ".google_token.json"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_PORT = 8766
REQUEST_TIMEOUT = 10

# Requested together so a single consent flow covers every Google
# integration in this project - Gmail is read-only on purpose (see gmail.py).
SCOPES = (
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/gmail.readonly"
)


class _OneShotAuthHandler(BaseHTTPRequestHandler):
    """Captures exactly one OAuth redirect (?code=...) and shuts the
    server down right after answering it."""
    received_code = None
    expected_state = None

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        code = query.get("code", [None])[0]
        state_ok = query.get("state", [None])[0] == _OneShotAuthHandler.expected_state

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if code and state_ok:
            _OneShotAuthHandler.received_code = code
            self.wfile.write("<html><body><h3>Autenticado! Pode fechar esta aba.</h3></body></html>".encode("utf-8"))
        else:
            self.wfile.write("<html><body><h3>Falha na autenticacao.</h3></body></html>".encode("utf-8"))

    def log_message(self, format, *args):
        pass  # silence default request logging


class GoogleOAuthClient:
    """Shared OAuth2 credential manager: one refresh token, one set of
    scopes, reused by every Google API client in this project."""

    def __init__(self, client_id=None, client_secret=None):
        load_env_file()
        self.client_id = client_id or os.environ.get("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("GOOGLE_CLIENT_SECRET")
        self._access_token = None
        self._access_token_expires_at = 0
        self._refresh_token = self._load_refresh_token()

    def is_configured(self):
        return bool(self.client_id and self.client_secret)

    def is_authenticated(self):
        return bool(self._refresh_token)

    # ------------------------------------------------------------------
    # One-time interactive setup
    # ------------------------------------------------------------------
    def authenticate_interactive(self):
        """Opens a browser for the user to grant access, captures the
        redirect locally, and stores a refresh token for future runs."""
        if not self.is_configured():
            raise RuntimeError(
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first."
            )

        state = secrets.token_urlsafe(16)
        redirect_uri = f"http://localhost:{REDIRECT_PORT}/"
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",  # forces a refresh token even on repeat auths
            "state": state,
        }
        url = f"{AUTH_URL}?{urlencode(params)}"

        _OneShotAuthHandler.received_code = None
        _OneShotAuthHandler.expected_state = state
        server = HTTPServer(("localhost", REDIRECT_PORT), _OneShotAuthHandler)

        print(f"Abrindo o navegador para voce autorizar o acesso ao Google (Calendar + Gmail)...\n{url}")
        webbrowser.open(url)
        server.handle_request()  # blocks until the one redirect arrives
        server.server_close()

        if not _OneShotAuthHandler.received_code:
            raise RuntimeError("Nao recebi o codigo de autorizacao (autenticacao cancelada ou falhou).")

        response = requests.post(TOKEN_URL, data={
            "code": _OneShotAuthHandler.received_code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        tokens = response.json()

        self._refresh_token = tokens["refresh_token"]
        self._save_refresh_token(self._refresh_token)
        self._access_token = tokens.get("access_token")
        self._access_token_expires_at = _now_ts() + tokens.get("expires_in", 0)
        print("Autenticado com sucesso! Token salvo em", TOKEN_FILE)

    def _load_refresh_token(self):
        if not os.path.exists(TOKEN_FILE):
            return None
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("refresh_token")

    def _save_refresh_token(self, refresh_token):
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump({"refresh_token": refresh_token}, f)

    # ------------------------------------------------------------------
    # Access token management
    # ------------------------------------------------------------------
    def get_access_token(self):
        if self._access_token and _now_ts() < self._access_token_expires_at - 30:
            return self._access_token
        if not self._refresh_token:
            raise RuntimeError(
                "Google isn't authenticated yet - run './venv/bin/python3 google_auth.py' once."
            )
        response = requests.post(TOKEN_URL, data={
            "refresh_token": self._refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        tokens = response.json()
        self._access_token = tokens["access_token"]
        self._access_token_expires_at = _now_ts() + tokens.get("expires_in", 0)
        return self._access_token

    def headers(self):
        return {"Authorization": f"Bearer {self.get_access_token()}"}


def _now_ts():
    import datetime
    return datetime.datetime.now().timestamp()


if __name__ == "__main__":
    GoogleOAuthClient().authenticate_interactive()
