#!/usr/bin/env bash
# Configures Claude Code's Notification/Stop hooks (in ~/.claude/settings.json,
# global - applies to every Claude Code session on this machine, not just this
# repo) to run notify_claude_hook.py, so the monkey can announce when Claude
# needs a permission decision, is waiting idle, or finishes a reply. See the
# "Claude Code notifications" section in README.md.
#
# Usage:
#   ./configure_claude_hooks.sh          # add the hooks (safe to re-run)
#   ./configure_claude_hooks.sh --remove # remove them
set -e
PROJECT_FOLDER="$(dirname "$(readlink -f "$0")")"
NOTIFY_SCRIPT="$PROJECT_FOLDER/notify_claude_hook.py"
SETTINGS_FILE="$HOME/.claude/settings.json"
MODE="install"
[ "$1" == "--remove" ] && MODE="remove"

mkdir -p "$(dirname "$SETTINGS_FILE")"

python3 - "$SETTINGS_FILE" "$NOTIFY_SCRIPT" "$MODE" <<'PYEOF'
import json
import os
import sys

settings_file, notify_script, mode = sys.argv[1:4]
command = f"python3 {notify_script}"

if os.path.exists(settings_file):
    with open(settings_file, "r", encoding="utf-8") as f:
        content = f.read().strip()
    settings = json.loads(content) if content else {}
else:
    settings = {}


def is_our_hook(hook_group):
    return any(
        h.get("type") == "command" and h.get("command") == command
        for h in hook_group.get("hooks", [])
    )


changed = False
hooks = settings.setdefault("hooks", {})

for event in ("Notification", "Stop"):
    entries = hooks.setdefault(event, [])
    if mode == "remove":
        before = len(entries)
        entries[:] = [group for group in entries if not is_our_hook(group)]
        if len(entries) != before:
            changed = True
        if not entries:
            del hooks[event]
    else:
        if not any(is_our_hook(group) for group in entries):
            entries.append({
                "hooks": [{
                    "type": "command",
                    "command": command,
                    "timeout": 10,
                    "async": True,
                }]
            })
            changed = True

if not hooks:
    settings.pop("hooks", None)

if changed:
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    verb = "Removed" if mode == "remove" else "Configured"
    print(f"{verb} Claude Code Notification/Stop hooks in {settings_file}")
else:
    verb = "already absent from" if mode == "remove" else "already configured in"
    print(f"Claude Code hooks {verb} {settings_file} - nothing to do.")
PYEOF

if [ "$MODE" == "install" ]; then
    echo "Restart any running Claude Code sessions (or run /hooks) for it to take effect."
    echo "To remove: $0 --remove"
else
    echo "Restart any running Claude Code sessions (or run /hooks) for the removal to take effect."
fi
