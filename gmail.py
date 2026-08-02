"""
Gmail integration - read-only: list, search, and read emails.

Deliberately read-only (no send capability) - the assistant's LLM tool
calls have occasionally been unreliable in testing (see brain.py/gcal.py
history), and sending a real email on the user's behalf carries real-world
risk that a wrong Todoist task or calendar event doesn't. Shares its OAuth2
login with gcal.py - see google_auth.py for setup.
"""
import base64
import datetime
import re

import requests

from google_auth import GoogleOAuthClient

API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
REQUEST_TIMEOUT = 10
# Kept small - the summaries get fed back into the LLM's context for a
# second round-trip, and the local CPU-bound model got slow enough with
# 10 full summaries that it blew past brain.py's request timeout.
MAX_RESULTS = 5
MAX_SNIPPET_CHARS = 150
MAX_BODY_CHARS = 1500

LIST_RECENT_EMAILS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_recent_emails",
        "description": "Lists the user's recent Gmail emails (sender, subject, short preview). Read-only, never sends anything.",
        "parameters": {
            "type": "object",
            "properties": {
                "when": {
                    "type": "string",
                    "enum": ["unread", "today", "recent"],
                    "description": (
                        "'unread' for unread emails, 'today' for emails received "
                        "today, 'recent' for the most recent regardless of read status."
                    ),
                },
            },
            "required": ["when"],
        },
    },
}

SEARCH_EMAILS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_emails",
        "description": (
            "Searches the user's Gmail (sender name, subject keywords, or a Gmail "
            "search operator like 'from:joao' or 'has:attachment'). Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms - a name, keyword, or Gmail search operator.",
                },
            },
            "required": ["query"],
        },
    },
}

READ_EMAIL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_email",
        "description": "Reads the full content of one specific email by its id (from a previous list_recent_emails/search_emails result).",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The email's id, taken from a previous list_recent_emails/search_emails result.",
                },
            },
            "required": ["message_id"],
        },
    },
}


class GmailClient:
    def __init__(self, auth=None):
        self.auth = auth or GoogleOAuthClient()

    def is_configured(self):
        return self.auth.is_configured()

    def is_authenticated(self):
        return self.auth.is_authenticated()

    def list_recent_emails(self, when="unread"):
        """Returns recent emails for the given bucket
        ("unread", "today", "recent")."""
        query = self._query_for_when(when)
        return self._search(query)

    def search_emails(self, query):
        """Searches Gmail with a free-text or operator-based query
        (e.g. 'from:joao', 'invoice', 'has:attachment')."""
        return self._search(query)

    def read_email(self, message_id):
        """Returns the full (truncated) body of one email plus its headers."""
        response = requests.get(
            f"{API_BASE}/messages/{message_id}",
            headers=self.auth.headers(),
            params={"format": "full"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        headers = self._headers_dict(data)
        body = self._extract_body_text(data.get("payload", {}))
        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS] + "..."
        return {
            "id": message_id,
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", "(sem assunto)"),
            "date": headers.get("Date", ""),
            "body": body,
        }

    # ------------------------------------------------------------------
    def _query_for_when(self, when):
        if when == "unread":
            return "is:unread"
        if when == "today":
            today_str = datetime.datetime.now().strftime("%Y/%m/%d")
            return f"after:{today_str}"
        return ""  # "recent" (or anything else): no filter, just most recent

    def _search(self, query):
        params = {"maxResults": MAX_RESULTS}
        if query:
            params["q"] = query
        response = requests.get(
            f"{API_BASE}/messages", headers=self.auth.headers(), params=params, timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        refs = response.json().get("messages", [])
        return [self._fetch_summary(ref["id"]) for ref in refs]

    def _fetch_summary(self, message_id):
        response = requests.get(
            f"{API_BASE}/messages/{message_id}",
            headers=self.auth.headers(),
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        headers = self._headers_dict(data)
        snippet = data.get("snippet", "")
        if len(snippet) > MAX_SNIPPET_CHARS:
            snippet = snippet[:MAX_SNIPPET_CHARS] + "..."
        return {
            "id": message_id,
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", "(sem assunto)"),
            "date": headers.get("Date", ""),
            "snippet": snippet,
        }

    def _headers_dict(self, message_data):
        return {h["name"]: h["value"] for h in message_data.get("payload", {}).get("headers", [])}

    def _extract_body_text(self, payload):
        """Recursively finds the first text/plain part in a (possibly
        nested multipart) Gmail message payload; falls back to text/html
        with tags crudely stripped if no plain-text part exists."""
        def decode(data_b64url):
            try:
                padded = data_b64url + "=" * (-len(data_b64url) % 4)
                return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
            except Exception:
                return ""

        def walk(part):
            mime_type = part.get("mimeType", "")
            body_data = (part.get("body") or {}).get("data")
            if mime_type == "text/plain" and body_data:
                return decode(body_data)
            for sub_part in part.get("parts", []) or []:
                found = walk(sub_part)
                if found:
                    return found
            if mime_type == "text/html" and body_data:
                return re.sub(r"<[^>]+>", " ", decode(body_data))
            return ""

        return walk(payload).strip()
