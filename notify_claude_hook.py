#!/usr/bin/env python3
"""Bridges Claude Code hook events to the buddy desktop monkey.

Configured in ~/.claude/settings.json as the command for the Notification
and Stop hooks (see that file). Reads the hook's JSON payload from stdin
and appends one JSON line describing what happened to a small queue file,
which animation.py polls (see NOTIFY_QUEUE_FILE/_check_claude_notifications
there) and announces through the monkey when idle.

Deliberately stdlib-only (no requests, no buddy imports) - this runs as a
Claude Code hook command outside buddy's venv, once per Notification/Stop
event, and must stay fast and dependency-free.
"""
import json
import os
import sys
import time

QUEUE_FILE = os.path.expanduser("~/.cache/buddy-assistant/claude_notifications.jsonl")
MAX_MESSAGE_CHARS = 300


def _last_assistant_text(transcript_path):
    """Stop hooks don't carry the reply text directly, so this scans the
    transcript (JSONL, newest entries last) backwards for the most recent
    assistant message and returns its concatenated text blocks."""
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return ""

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        text_parts = [
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = " ".join(part.strip() for part in text_parts if part.strip())
        if text:
            return text
    return ""


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}

    event = payload.get("hook_event_name", "")
    if event == "Notification":
        message = payload.get("message", "")
    elif event == "Stop":
        message = _last_assistant_text(payload.get("transcript_path", ""))
    else:
        message = ""

    if not message:
        return

    if len(message) > MAX_MESSAGE_CHARS:
        message = message[:MAX_MESSAGE_CHARS] + "..."

    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    entry = {
        "event": event,
        "message": message,
        "cwd": payload.get("cwd", ""),
        "ts": time.time(),
    }
    with open(QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
