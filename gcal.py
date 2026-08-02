"""
Google Calendar integration - event reading, creation, and meeting reminders.

Shares its OAuth2 login with gmail.py - see google_auth.py for the setup
steps and one-time authentication flow.
"""
import datetime
import re

import requests

from google_auth import GoogleOAuthClient

API_BASE = "https://www.googleapis.com/calendar/v3"
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
    def __init__(self, auth=None):
        self.auth = auth or GoogleOAuthClient()

    def is_configured(self):
        return self.auth.is_configured()

    def is_authenticated(self):
        return self.auth.is_authenticated()

    def list_events(self, when="upcoming"):
        """Returns upcoming events for the given bucket
        ("today", "tomorrow", "this_week", "upcoming")."""
        time_min, time_max = _window_for(when)
        response = requests.get(
            f"{API_BASE}/calendars/primary/events",
            headers=self.auth.headers(),
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
            headers=self.auth.headers(), json=payload, timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        event = response.json()
        return {
            "id": event["id"],
            "summary": event.get("summary"),
            "start": (event.get("start") or {}).get("dateTime"),
        }


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
