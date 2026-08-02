#!/usr/bin/env bash
# Launcher used by autostart (see configure_autostart.sh): makes sure
# Ollama is running in CPU mode (on this machine the GPU backend crashes,
# see start_ollama.sh) and only then opens the monkey's window.
set -e
cd "$(dirname "$(readlink -f "$0")")"

if ! curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
    nohup ./start_ollama.sh >/tmp/buddy_ollama.log 2>&1 &
    disown
    sleep 2
fi

exec ./venv/bin/python3 animation.py
