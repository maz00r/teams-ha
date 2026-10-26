#!/usr/bin/env bash
# Teams w Microsoft Edge z brokerem tożsamości Microsoftu.
# Broker rejestruje urządzenie w Entra ID, więc firmowa reguła dostępu warunkowego
# „tylko zarejestrowane urządzenia" może zostać spełniona zgodnie z jej przeznaczeniem.
#
# W kontenerze nie ma systemd, więc wszystko, co broker normalnie dostaje z sesji
# graficznej, montujemy ręcznie: systemowa i sesyjna szyna D-Bus (broker aktywuje się
# przez D-Bus) oraz odblokowany gnome-keyring (broker trzyma tam tokeny przez libsecret).
set -e

OPT=/data/options.json
opt() { python3 -c "import json;v=json.load(open('$OPT')).get('$1');print('' if v is None else v)" 2>/dev/null || true; }

START_URL="$(opt start_url)"; SCREEN_W="$(opt screen_width)"; SCREEN_H="$(opt screen_height)"; SCALE="$(opt scale)"
case "$START_URL" in "") START_URL="https://teams.microsoft.com/v2/" ;; esac
case "$SCREEN_W" in "") SCREEN_W=840 ;; esac
case "$SCREEN_H" in "") SCREEN_H=1800 ;; esac
case "$SCALE" in "") SCALE=1 ;; esac
WIN_W="$(python3 -c "print(int($SCREEN_W / $SCALE))")"
WIN_H="$(python3 -c "print(int($SCREEN_H / $SCALE))")"
if [ "$WIN_W" -lt 500 ]; then
  echo "[teams] UWAGA: szerokość okna ${WIN_W} < 500 — Edge użyje 500, obraz się utnie."
fi

export START_URL
export NOTIFY_SERVICE="$(opt notify_service)"; export NTFY_TOPIC="$(opt ntfy_topic)"
export NOTIFY_PREVIEW="$(opt notify_preview)"; export QUIET_HOURS="$(opt quiet_hours)"
export EXTERNAL_URL="$(opt external_url)"; export LOG_LEVEL="$(opt log_level)"
export TZ="${TZ:-Europe/Warsaw}"
export CDP_URL="http://127.0.0.1:9222"
# WebKitGTK bez GPU rysuje okno logowania brokera na czarno — te flagi wymuszają
# rendering programowy, inaczej logowanie Microsoft nie pokazuje się i pada w pętlę.
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export LIBGL_ALWAYS_SOFTWARE=1

mkdir -p "$EDGE_PROFILE" /data/keyring
echo "[teams] start: ekran ${SCREEN_W}x${SCREEN_H}, skala ${SCALE} (okno ${WIN_W}x${WIN_H} CSS), url=${START_URL}"

# --- 1) Systemowa szyna D-Bus + broker urządzenia ---
# Plik usługi D-Bus brokera urządzenia ma Exec=/bin/false i oddaje start systemd,
# którego w kontenerze nie ma — więc broker trzeba odpalić ręcznie (z autorestartem).
# Broker użytkownika (sesyjny) ma prawdziwy Exec=, więc aktywuje się sam, gdy Edge go woła.
mkdir -p /run/dbus
rm -f /run/dbus/pid
dbus-daemon --system --fork
sleep 1
( while true; do
    /opt/microsoft/identity-broker/bin/microsoft-identity-device-broker \
      || echo "[teams] broker urządzenia zakończył się — restart za 5s"
    sleep 5
  done ) &
sleep 3

# --- 2) Sesyjna szyna D-Bus (aktywuje brokera użytkownika + Secret Service) ---
eval "$(dbus-launch --sh-syntax)"
export DBUS_SESSION_BUS_ADDRESS DBUS_SESSION_BUS_PID
echo "[teams] D-Bus sesyjny: ${DBUS_SESSION_BUS_ADDRESS}"

# --- 3) gnome-keyring odblokowany bez interaktywnego logowania ---
# Pusty pierwszy pęk kluczy tworzony z pustym hasłem — broker ma gdzie trzymać tokeny.
export XDG_DATA_HOME=/data/keyring
export HOME=/root
mkdir -p "$XDG_DATA_HOME/keyrings"
if [ ! -f "$XDG_DATA_HOME/keyrings/login.keyring" ]; then
  printf 'login\n' > "$XDG_DATA_HOME/keyrings/default" 2>/dev/null || true
fi
eval "$(printf '\n' | gnome-keyring-daemon --unlock --components=secrets,pkcs11 --daemonize 2>/dev/null)" || \
  echo "[teams] UWAGA: gnome-keyring nie wystartował — broker może nie zapisać tokenu."
export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
sleep 1

# --- 4) Stan rejestracji urządzenia (do Dziennika) ---
echo "[teams] --- stan rejestracji (dsreg) ---"
dsreg --status 2>&1 | head -20 || dsreg 2>&1 | head -20 || echo "[teams] dsreg: brak odczytu stanu"
echo "[teams] -----------------------------------"

# --- 5) Wirtualny ekran w pionie ---
Xvfb :1 -screen 0 "${SCREEN_W}x${SCREEN_H}x24" -nolisten tcp &
sleep 2

# --- 6) Microsoft Edge z trwałym profilem (logujesz się raz). Broker daje SSO i rejestrację. ---
( while true; do
    microsoft-edge \
      --no-sandbox --disable-dev-shm-usage \
      --disable-gpu --disable-gpu-compositing \
      --enable-logging=stderr --log-level=3 \
      --user-data-dir="$EDGE_PROFILE" \
      --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
      --remote-allow-origins='*' \
      --force-device-scale-factor="$SCALE" \
      --window-position=0,0 --window-size="${WIN_W},${WIN_H}" \
      --lang=pl --no-first-run --no-default-browser-check \
      --no-service-autorun --disable-sync \
      "$START_URL" 2>&1 | grep -v -E "dbus|Fontconfig|libva|vaapi|vk_renderer|Display.cpp|ANGLE|GPU stall|^$" || true
    echo "[teams] Edge zakończony — restart za 5s"
    rm -f "$EDGE_PROFILE"/Singleton*
    sleep 5
  done ) &
sleep 5

# --- 7) VNC lokalnie + most websocket; na zewnątrz wychodzi tylko panel (Ingress) ---
x11vnc -display :1 -forever -shared -nopw -quiet -localhost -rfbport 5900 &
sleep 1
websockify 127.0.0.1:6080 localhost:5900 >/dev/null 2>&1 &
sleep 1

# --- 8) Panel Ingress (autorestart) ---
( while true; do
    python3 /app/panel.py || echo "[panel] proces zakończony — restart za 5s"
    sleep 5
  done ) &

# --- 9) Notifier na pierwszym planie ---
exec python3 /app/notifier.py
