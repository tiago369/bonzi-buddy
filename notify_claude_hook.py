#!/usr/bin/env python3
"""Bridges Claude Code hook events to the buddy desktop monkey.

Configured in ~/.claude/settings.json (via configure_claude_hooks.sh) as the
command for the Notification, Stop, and PermissionRequest hooks. Reads the
hook's JSON payload from stdin and appends one JSON line describing what
happened to a small queue file, which animation.py polls (see
NOTIFY_QUEUE_FILE/_check_claude_notifications there) and announces through
the monkey when idle.

Notification alone does NOT cover "please approve this command" prompts -
those fire PermissionRequest instead (a separate hook event, matcher = tool
name), which carries tool_name/tool_input rather than a ready-made message
string, so _permission_message() builds one.

Deliberately stdlib-only (no requests, no buddy imports) - this runs as a
Claude Code hook command outside buddy's venv, once per event, and must
stay fast and dependency-free.
"""
import json
import os
import sys
import time

QUEUE_FILE = os.path.expanduser("~/.cache/buddy-assistant/claude_notifications.jsonl")
# Every hook invocation is logged here too (event name + top-level payload
# keys only, no values - tool_input can contain file contents) so a future
# "some events aren't coming through" report can be diagnosed by reading
# what Claude Code actually sent, instead of guessing at the hook schema.
DEBUG_LOG = os.path.expanduser("~/.cache/buddy-assistant/hook_debug.jsonl")
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


def _permission_message(payload):
    """PermissionRequest carries tool_name/tool_input, not a plain message -
    build a short human-readable summary of what's being asked."""
    tool_name = payload.get("tool_name") or "uma ferramenta"
    tool_input = payload.get("tool_input") or {}
    detail = (
        tool_input.get("command")
        or tool_input.get("file_path")
        or tool_input.get("url")
        or tool_input.get("pattern")
        or ""
    )
    detail = str(detail).strip()
    if detail:
        if len(detail) > 120:
            detail = detail[:120] + "..."
        return f"{tool_name}: {detail}"
    return f"permissao pra usar {tool_name}"


def _debug_log(payload):
    try:
        os.makedirs(os.path.dirname(DEBUG_LOG), exist_ok=True)
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            entry = {
                "ts": time.time(),
                "event": payload.get("hook_event_name"),
                "keys": sorted(payload.keys()),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}

    _debug_log(payload)

    event = payload.get("hook_event_name", "")
    if event == "Notification":
        message = payload.get("message", "")
    elif event == "Stop":
        message = _last_assistant_text(payload.get("transcript_path", ""))
    elif event == "PermissionRequest":
        message = _permission_message(payload)
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
