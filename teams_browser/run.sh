#!/usr/bin/env sh
# Teams na telefonie: Xvfb -> Chromium (Teams) -> VNC -> websockify -> panel (Ingress),
# a na pierwszym planie notifier, który przez CDP łapie nowe wiadomości i wysyła push.
set -e

OPT=/data/options.json
opt() { python3 -c "import json;v=json.load(open('$OPT')).get('$1');print('' if v is None else v)" 2>/dev/null || true; }

START_URL="$(opt start_url)"
SCREEN_W="$(opt screen_width)"
SCREEN_H="$(opt screen_height)"
SCALE="$(opt scale)"
case "$START_URL" in "") START_URL="https://teams.microsoft.com/v2/" ;; esac
case "$SCREEN_W" in "") SCREEN_W=1000 ;; esac
case "$SCREEN_H" in "") SCREEN_H=2160 ;; esac
case "$SCALE" in "") SCALE=2 ;; esac
# --window-size jest w pikselach CSS (DIP), ekran Xvfb w fizycznych — dzielimy przez skalę.
WIN_W="$(python3 -c "print(int($SCREEN_W / $SCALE))")"
WIN_H="$(python3 -c "print(int($SCREEN_H / $SCALE))")"
# Chromium nie zrobi okna węższego niż 500 px CSS — węższe ustawienie ucięłoby obraz.
if [ "$WIN_W" -lt 500 ]; then
  echo "[teams] UWAGA: screen_width/scale = ${WIN_W} < 500 — Chromium i tak użyje 500, część obrazu zniknie. Zwiększ screen_width albo zmniejsz scale."
fi

export START_URL
export NOTIFY_SERVICE="$(opt notify_service)"
export NTFY_TOPIC="$(opt ntfy_topic)"
export NOTIFY_PREVIEW="$(opt notify_preview)"
export QUIET_HOURS="$(opt quiet_hours)"
export EXTERNAL_URL="$(opt external_url)"
export LOG_LEVEL="$(opt log_level)"
export TZ="${TZ:-Europe/Warsaw}"

mkdir -p "$CHROME_PROFILE"
# Po twardym restarcie kontenera zostaje blokada profilu i Chromium odmawia startu.
rm -f "$CHROME_PROFILE"/Singleton*
echo "[teams] start: ekran ${SCREEN_W}x${SCREEN_H}, skala ${SCALE} (okno ${WIN_W}x${WIN_H} CSS), url=${START_URL}"

# 1) Wirtualny ekran w pionie — jak telefon.
Xvfb :1 -screen 0 "${SCREEN_W}x${SCREEN_H}x24" -nolisten tcp &
sleep 2

# 2) Chromium z TRWAŁYM profilem (/data przeżywa restarty, więc logujesz się raz).
#    Desktopowy User-Agent celowo: z mobilnym Teams pokazuje tylko „pobierz aplikację".
#    Wąskie okno (500 px CSS — minimum Chromium) + skala 2 sprawiają, że Teams układa się w jedną kolumnę, a obraz jest ostry.
#    CDP słucha tylko na localhost — korzystają z niego panel i notifier.
( while true; do
    chromium-browser \
      --no-sandbox --disable-dev-shm-usage \
      --disable-gpu --disable-gpu-compositing \
      --enable-logging=stderr --log-level=3 \
      --user-data-dir="$CHROME_PROFILE" \
      --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
      --remote-allow-origins='*' \
      --force-device-scale-factor="$SCALE" \
      --window-position=0,0 --window-size="${WIN_W},${WIN_H}" \
      --kiosk --lang=pl --accept-lang=pl-PL,pl,en \
      --no-first-run --no-default-browser-check \
      --disable-features=Translate,MediaRouter \
      --autoplay-policy=user-gesture-required \
      "$START_URL" 2>&1 | grep -v -E "dbus|Fontconfig|libva|vaapi|vk_renderer|Display.cpp|ANGLE|^$" || true
    echo "[teams] Chromium zakończony — restart za 5s"
    rm -f "$CHROME_PROFILE"/Singleton*
    sleep 5
  done ) &
sleep 4

# 3) VNC tylko lokalnie — na zewnątrz wychodzi wyłącznie panel przez Ingress.
x11vnc -display :1 -forever -shared -nopw -quiet -localhost -rfbport 5900 &
sleep 1

# 4) websockify jako most websocket->VNC na porcie lokalnym; panel.py go tuneluje.
websockify 127.0.0.1:6080 localhost:5900 >/dev/null 2>&1 &
sleep 1

# 5) Panel Ingress (z autorestartem — to jedyne okno na dodatek).
( while true; do
    python3 /app/panel.py || echo "[panel] proces zakończony — restart za 5s"
    sleep 5
  done ) &

# 6) Notifier na pierwszym planie (jego wyjście kończy kontener i Supervisor go podniesie).
exec python3 /app/notifier.py
