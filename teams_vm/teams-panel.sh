#!/usr/bin/env bash
# Dzienny panel Teams na VM: Xvfb :1 -> Edge (Teams) -> x11vnc -> websockify -> panel + notifier.
#
# W odróżnieniu od wariantu kontenerowego NIE stawiamy tu D-Bus, keyring ani brokera —
# daje je zalogowana sesja pulpitu (dlatego VM musi mieć AUTOLOGOWANIE do GNOME, żeby
# keyring był odblokowany i broker dostępny). Urządzenie jest już zarejestrowane, więc
# ten Edge dostaje SSO z brokera i Teams wpuszcza.
set -euo pipefail

APPDIR="$HOME/.local/share/teams-panel"
CFG="$HOME/.config/teams-panel.env"
STATE="$HOME/.local/state/teams-panel"
EDGE_PROFILE="$APPDIR/edge-profile"
mkdir -p "$STATE" "$EDGE_PROFILE"

# --- konfiguracja użytkownika ---
[ -f "$CFG" ] && set -a && . "$CFG" && set +a
SCREEN_W="${SCREEN_WIDTH:-840}"; SCREEN_H="${SCREEN_HEIGHT:-1800}"; SCALE="${SCALE:-1}"
START_URL="${START_URL:-https://teams.microsoft.com/v2/}"
WIN_W="$(python3 -c "print(int($SCREEN_W/$SCALE))")"
WIN_H="$(python3 -c "print(int($SCREEN_H/$SCALE))")"

# --- zmienne, których używa nasz kod panelu (te same nazwy co w dodatku) ---
export DISPLAY=:1
export NOVNC_DIR="${NOVNC_DIR:-/usr/share/novnc}"
export CDP_URL="http://127.0.0.1:9222"
export PANEL_URL="http://127.0.0.1:8099"
export STATUS_PATH="$STATE/status.json"
export START_URL
export NOTIFY_SERVICE=""                      # na VM push idzie przez ntfy, nie Supervisor
export NTFY_TOPIC="${NTFY_TOPIC:-}"
export NOTIFY_PREVIEW="${NOTIFY_PREVIEW:-true}"
export QUIET_HOURS="${QUIET_HOURS:-}"
export EXTERNAL_URL="${EXTERNAL_URL:-}"
export LOG_LEVEL="${LOG_LEVEL:-info}"
# WebKit programowo — na wszelki wypadek, gdyby jakiś webview próbował GPU.
export WEBKIT_DISABLE_DMABUF_RENDERER=1 WEBKIT_DISABLE_COMPOSITING_MODE=1 LIBGL_ALWAYS_SOFTWARE=1

cleanup() { kill $(jobs -p) 2>/dev/null || true; }
trap cleanup EXIT

echo "[teams-vm] start: ekran ${SCREEN_W}x${SCREEN_H} skala ${SCALE} (okno ${WIN_W}x${WIN_H}), url=${START_URL}"

# 1) Wirtualny ekran pod sam panel (osobny od pulpitu, żeby telefon widział tylko Teams)
Xvfb :1 -screen 0 "${SCREEN_W}x${SCREEN_H}x24" -nolisten tcp &
sleep 2

# 2) Edge z trwałym profilem + CDP. Broker (z sesji pulpitu) daje mu SSO.
( while true; do
    microsoft-edge \
      --no-sandbox --disable-dev-shm-usage --disable-gpu --disable-gpu-compositing \
      --enable-logging=stderr --log-level=3 \
      --user-data-dir="$EDGE_PROFILE" \
      --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --remote-allow-origins='*' \
      --force-device-scale-factor="$SCALE" \
      --window-position=0,0 --window-size="${WIN_W},${WIN_H}" \
      --kiosk --lang=pl --no-first-run --no-default-browser-check --disable-sync \
      "$START_URL" 2>&1 | grep -v -E "dbus|Fontconfig|libva|vaapi|vk_renderer|Display.cpp|ANGLE|^$" || true
    echo "[teams-vm] Edge zakończony — restart za 5s"; rm -f "$EDGE_PROFILE"/Singleton*; sleep 5
  done ) &
sleep 5

# 3) VNC + most websocket (tylko lokalnie; na zewnątrz wychodzi panel)
x11vnc -display :1 -forever -shared -nopw -quiet -localhost -rfbport 5900 &
sleep 1
websockify 127.0.0.1:6080 localhost:5900 >/dev/null 2>&1 &
sleep 1

# 4) Panel HTTP (obraz + pasek pisania) — na 0.0.0.0:8099, dostępny z telefonu / przez tunel
( while true; do python3 "$APPDIR/panel.py" || echo "[panel] restart za 5s"; sleep 5; done ) &

# 5) Notifier na pierwszym planie
exec python3 "$APPDIR/notifier.py"
