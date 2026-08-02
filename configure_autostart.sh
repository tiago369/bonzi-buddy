#!/usr/bin/env bash
# Configures the monkey assistant to open by itself when you log in
# (creates a .desktop in ~/.config/autostart, the standard GNOME/
# freedesktop mechanism for startup apps).
#
# Usage:
#   ./configure_autostart.sh          # enable autostart
#   ./configure_autostart.sh --remove # disable autostart
set -e
PROJECT_FOLDER="$(dirname "$(readlink -f "$0")")"
AUTOSTART_FOLDER="$HOME/.config/autostart"
DESKTOP_FILE="$AUTOSTART_FOLDER/desktop-monkey-assistant.desktop"

if [ "$1" == "--remove" ]; then
    rm -f "$DESKTOP_FILE"
    echo "Autostart removed: $DESKTOP_FILE"
    exit 0
fi

mkdir -p "$AUTOSTART_FOLDER"
chmod +x "$PROJECT_FOLDER/start_monkey.sh" "$PROJECT_FOLDER/start_ollama.sh"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Monkey Assistant
Comment=Desktop monkey assistant (Ollama + animations)
Exec=$PROJECT_FOLDER/start_monkey.sh
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "Autostart configured at: $DESKTOP_FILE"
echo "The monkey will open by itself on next login."
echo "To disable: $0 --remove"
