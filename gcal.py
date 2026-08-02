"""
Google Calendar integration - event reading, creation, and meeting reminders.

Uses a hand-rolled OAuth2 "installed app" flow (just `requests` + the
standard library - no google-auth/google-api-python-client dependency) so
it stays consistent with the rest of this project's style (see brain.py,
todoist.py).

One-time setup:
1. Google Cloud Console -> new project -> enable the "Google Calendar API".
2. APIs & Services -> Credentials -> Create OAuth client ID -> type
   "Desktop app". Copy the Client ID and Client Secret.
3. Put them in `.env` (already git-ignored):
       GOOGLE_CLIENT_ID=...
       GOOGLE_CLIENT_SECRET=...
4. Run `./venv/bin/python3 gcal.py` once - it opens a browser for you to
   grant access, then stores a refresh token in `.google_token.json`
   (also git-ignored). After that, animation.py picks it up automatically.
"""
import datetime
import json
import os
import re
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from todoist import load_env_file  # reuses the same tiny .env loader

TOKEN_FILE = ".google_token.json"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
REDIRECT_PORT = 8766
REQUEST_TIMEOUT = 10

WHEN_WINDOWS_HOURS = {
    "today": None,           # handled specially (midnight to midnight)
    "tomorrow": None,        # handled specially
    "upcoming": 24 * 7,      # next 7 days from now
    "this_week": None,       # handled specially (now to end of week)
}

# Small local model like llama3.2:3b is unreliable at computing an exact
# ISO datetime itself for relative phrases ("amanha as 16h") - it'll often
# just skip the tool call or hallucinate a "done!" reply instead. So,
# mirroring how Todoist's own due_string parser works, create_event takes
# a natural-language phrase and this deterministic parser resolves it,
# instead of asking the model to do the date arithmetic.
_WEEKDAY_NAMES_PT = {
    "segunda": 0, "terca": 1, "terça": 1, "quarta": 2, "quinta": 3,
    "sexta": 4, "sabado": 5, "sábado": 5, "domingo": 6,
}


def _parse_time_of_day(text):
    match = re.search(r"(\d{1,2})\s*[h:]\s*(\d{2})?", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    return hour, minute


def parse_natural_datetime(text):
    """Best-effort parser for simple Portuguese relative date/time phrases
    ("hoje as 15h", "amanha as 10h", a weekday name, or an explicit
    YYYY-MM-DD). Also accepts a full ISO 8601 string as-is."""
    text = (text or "").strip()
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        pass

    text_lower = text.lower()
    now = datetime.datetime.now().astimezone()
    hour, minute = _parse_time_of_day(text_lower) or (now.hour, 0)

    date_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if date_match:
        target_date = datetime.date(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
    elif "amanha" in text_lower or "amanhã" in text_lower:
        target_date = (now + datetime.timedelta(days=1)).date()
    elif "hoje" in text_lower:
        target_date = now.date()
    else:
        target_date = None
        for name, weekday in _WEEKDAY_NAMES_PT.items():
            if name in text_lower:
                days_ahead = (weekday - now.weekday()) % 7 or 7
                target_date = (now + datetime.timedelta(days=days_ahead)).date()
                break
        if target_date is None:
            target_date = now.date()  # last-resort fallback

    return datetime.datetime.combine(target_date, datetime.time(hour, minute)).astimezone()


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


LIST_EVENTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_events",
        "description": "Lists the user's Google Calendar events for a given time range.",
        "parameters": {
            "type": "object",
            "properties": {
                "when": {
                    "type": "string",
                    "enum": ["today", "tomorrow", "this_week", "upcoming"],
                    "description": "Which events to fetch: 'today', 'tomorrow', 'this_week', or 'upcoming' (next 7 days).",
                }
            },
            "required": ["when"],
        },
    },
}

CREATE_EVENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_event",
        "description": "Creates a new Google Calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "The event's title."},
                "start": {
                    "type": "string",
                    "description": (
                        "When the event starts - just pass through whatever the user said "
                        "in natural Portuguese (e.g. 'amanha as 15h', 'sexta as 10h'), or "
                        "an ISO 8601 datetime. Do NOT try to compute an exact date yourself."
                    ),
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Event length in minutes. Defaults to 60 if omitted.",
                },
            },
            "required": ["summary", "start"],
        },
    },
}


class GoogleCalendarClient:
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
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",  # forces a refresh token even on repeat auths
            "state": state,
        }
        url = f"{AUTH_URL}?{urlencode(params)}"

        _OneShotAuthHandler.received_code = None
        _OneShotAuthHandler.expected_state = state
        server = HTTPServer(("localhost", REDIRECT_PORT), _OneShotAuthHandler)

        print(f"Abrindo o navegador para voce autorizar o acesso ao Google Calendar...\n{url}")
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
    def _get_access_token(self):
        if self._access_token and _now_ts() < self._access_token_expires_at - 30:
            return self._access_token
        if not self._refresh_token:
            raise RuntimeError(
                "Google Calendar isn't authenticated yet - run 'python gcal.py' once."
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

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_access_token()}"}

    # ------------------------------------------------------------------
    # Calendar operations
    # ------------------------------------------------------------------
    def list_events(self, when="upcoming"):
        """Returns upcoming events for the given bucket
        ("today", "tomorrow", "this_week", "upcoming")."""
        time_min, time_max = _window_for(when)
        response = requests.get(
            f"{API_BASE}/calendars/primary/events",
            headers=self._headers(),
            params={
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 20,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        events = response.json().get("items", [])
        return [
            {
                "id": event["id"],
                "summary": event.get("summary", "(sem titulo)"),
                "start": (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date"),
            }
            for event in events
        ]

    def create_event(self, summary, start, duration_minutes=60):
        """Creates a new event. `start` accepts natural Portuguese phrases
        ("amanha as 15h") as well as ISO 8601 - parsed deterministically by
        parse_natural_datetime rather than relying on the model to compute
        an exact date. `duration_minutes` defaults to 60."""
        start = parse_natural_datetime(start)
        if start.tzinfo is None:
            start = start.astimezone()  # assume local timezone
        end = start + datetime.timedelta(minutes=duration_minutes)

        payload = {
            "summary": summary,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        response = requests.post(
            f"{API_BASE}/calendars/primary/events",
            headers=self._headers(), json=payload, timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        event = response.json()
        return {
            "id": event["id"],
            "summary": event.get("summary"),
            "start": (event.get("start") or {}).get("dateTime"),
        }


def _now_ts():
    return datetime.datetime.now().timestamp()


def _window_for(when):
    now = datetime.datetime.now().astimezone()
    if when == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=1)
    elif when == "tomorrow":
        start = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=1)
    elif when == "this_week":
        start = now
        days_left_in_week = 6 - now.weekday()  # Monday=0 ... Sunday=6
        end = (now + datetime.timedelta(days=days_left_in_week)).replace(hour=23, minute=59, second=59)
    else:  # "upcoming"
        start = now
        end = now + datetime.timedelta(hours=WHEN_WINDOWS_HOURS["upcoming"])
    return start, end


if __name__ == "__main__":
    GoogleCalendarClient().authenticate_interactive()
