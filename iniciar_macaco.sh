#!/usr/bin/env bash
# Launcher usado pelo autostart (ver configurar_autostart.sh): garante que
# o Ollama esta rodando em modo CPU (nesta maquina o backend GPU trava, ver
# start_ollama.sh) e so entao abre a janela do macaco.
set -e
cd "$(dirname "$(readlink -f "$0")")"

if ! curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
    nohup ./start_ollama.sh >/tmp/buddy_ollama.log 2>&1 &
    disown
    sleep 2
fi

exec ./venv/bin/python3 animation.py
