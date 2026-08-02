#!/usr/bin/env bash
# Configura o assistente macaco pra abrir sozinho quando voce faz login
# (cria um .desktop em ~/.config/autostart, o mecanismo padrao do GNOME/
# freedesktop pra apps de inicializacao).
#
# Uso:
#   ./configurar_autostart.sh            # ativa o autostart
#   ./configurar_autostart.sh --remover  # desativa o autostart
set -e
PASTA_PROJETO="$(dirname "$(readlink -f "$0")")"
PASTA_AUTOSTART="$HOME/.config/autostart"
ARQUIVO_DESKTOP="$PASTA_AUTOSTART/desktop-monkey-assistant.desktop"

if [ "$1" == "--remover" ]; then
    rm -f "$ARQUIVO_DESKTOP"
    echo "Autostart removido: $ARQUIVO_DESKTOP"
    exit 0
fi

mkdir -p "$PASTA_AUTOSTART"
chmod +x "$PASTA_PROJETO/iniciar_macaco.sh" "$PASTA_PROJETO/start_ollama.sh"

cat > "$ARQUIVO_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Assistente Macaco
Comment=Macaco assistente de mesa (Ollama + animacoes)
Exec=$PASTA_PROJETO/iniciar_macaco.sh
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "Autostart configurado em: $ARQUIVO_DESKTOP"
echo "O macaco vai abrir sozinho no proximo login."
echo "Pra desativar: $0 --remover"
