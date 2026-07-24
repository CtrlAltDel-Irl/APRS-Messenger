#!/usr/bin/env bash
# Install APRS Messenger desktop launcher + icons for the current user
set -euo pipefail
APP="$(cd "$(dirname "$0")" && pwd)"
ICON_BASE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
PNG="$APP/assets/aprs-messenger.png"

if [[ ! -f "$PNG" ]]; then
  echo "Missing icon: $PNG" >&2
  exit 1
fi
if [[ ! -f "$APP/main.py" ]]; then
  echo "Missing main.py in $APP" >&2
  exit 1
fi

for s in 16 24 32 48 64 128 256; do
  mkdir -p "$ICON_BASE/${s}x${s}/apps"
  src="$APP/assets/aprs-messenger-${s}.png"
  [[ -f "$src" ]] || src="$PNG"
  cp -f "$src" "$ICON_BASE/${s}x${s}/apps/aprs-messenger.png"
done
if [[ -f "$APP/assets/aprs-messenger.svg" ]]; then
  mkdir -p "$ICON_BASE/scalable/apps"
  cp -f "$APP/assets/aprs-messenger.svg" "$ICON_BASE/scalable/apps/aprs-messenger.svg"
fi

mkdir -p "$APP_DIR"
# Absolute Icon path is the most reliable across file managers / DEs
cat > "$APP_DIR/aprs-messenger.desktop" << EOF
[Desktop Entry]
Version=2.0
Type=Application
Name=APRS Messenger
GenericName=APRS Chat
Comment=APRS-IS messaging for licensed amateur radio operators
Exec=python3 $APP/main.py
Path=$APP
Icon=$PNG
Terminal=false
Categories=Network;Chat;
Keywords=APRS;ham;radio;chat;amateur;messaging;
StartupNotify=true
StartupWMClass=aprs-messenger
EOF
cp -f "$APP_DIR/aprs-messenger.desktop" "$APP_DIR/APRS-Messenger.desktop"
cp -f "$APP_DIR/aprs-messenger.desktop" "$APP/aprs-messenger.desktop"
cp -f "$APP_DIR/aprs-messenger.desktop" "$APP/APRS-Messenger.desktop"
chmod 644 "$APP_DIR"/*.desktop
chmod +x "$APP/APRS-Messenger.desktop" "$APP/aprs-messenger.desktop"

if command -v gio >/dev/null 2>&1; then
  gio set "$APP/APRS-Messenger.desktop" metadata::trusted true 2>/dev/null || true
  gio set "$APP/aprs-messenger.desktop" metadata::trusted true 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$ICON_BASE" 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" 2>/dev/null || true
fi

echo "Installed:"
echo "  $APP_DIR/APRS-Messenger.desktop"
echo "  Icon: $PNG"
echo "If the icon still does not show, log out/in or restart your panel/file manager."
