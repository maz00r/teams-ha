#!/usr/bin/env bash
# Teams na telefonie — instalacja na VM z Ubuntu Desktop (GNOME, GUI).
#
# PO CO VM, a nie dodatek HA: firmowa reguła dostępu warunkowego Nexi wpuszcza tylko
# urządzenia ZAREJESTROWANE w Entra ID. Mac i Windows rejestrują się same przy
# pierwszym logowaniu. Na Linuksie robi to „microsoft-identity-broker", ale jego okno
# logowania potrzebuje PRAWDZIWEGO pulpitu — w kontenerze gaśnie na czarno. Dlatego
# stawiamy to na realnym Ubuntu Desktop: broker pokaże okno logowania i zarejestruje
# urządzenie jak Mac/Windows, a potem nasz panel wysyła obraz na telefon.
#
# URUCHOM na VM (Ubuntu Desktop 24.04 LTS) jako zwykły użytkownik:
#   chmod +x setup.sh && ./setup.sh
# Skrypt poprosi o hasło (sudo) do instalacji pakietów. NIE uruchamiaj całości przez sudo.
set -euo pipefail

if [ "$(id -u)" = "0" ]; then
  echo "Uruchom jako zwykły użytkownik (skrypt sam użyje sudo tam, gdzie trzeba)." >&2
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
APPDIR="$HOME/.local/share/teams-panel"
UBUNTU_CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"

echo "== 1/5 Repozytoria Microsoftu (broker + Edge) =="
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/ubuntu/$(. /etc/os-release && echo "$VERSION_ID")/prod ${UBUNTU_CODENAME} main" \
  | sudo tee /etc/apt/sources.list.d/microsoft-prod.list >/dev/null
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/edge stable main" \
  | sudo tee /etc/apt/sources.list.d/microsoft-edge.list >/dev/null

echo "== 2/5 Pakiety (Edge, broker, VNC, Python) =="
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  microsoft-edge-stable \
  microsoft-identity-broker microsoft-identity-diagnostics \
  x11vnc novnc websockify \
  python3 python3-websocket \
  fonts-noto-core fonts-noto-color-emoji
# websocket-client bywa pod nazwą python3-websocket; gdyby brakło, spróbuj pip.
python3 -c "import websocket" 2>/dev/null || pip3 install --user --break-system-packages websocket-client || true

echo "== 3/5 Broker urządzenia włączony =="
# Na pulpicie broker działa jako usługa systemd (ma środowisko graficzne i keyring).
sudo systemctl enable --now microsoft-identity-device-broker.service || \
  echo "UWAGA: nie udało się włączyć microsoft-identity-device-broker — sprawdź 'systemctl status'."

echo "== 4/5 Wymuszenie sesji Xorg (x11vnc nie działa z Wayland) =="
# Ubuntu Desktop domyślnie startuje na Wayland; x11vnc wymaga Xorg. Przełączamy GDM na Xorg.
if [ -f /etc/gdm3/custom.conf ]; then
  sudo sed -i 's/^#\?WaylandEnable=.*/WaylandEnable=false/' /etc/gdm3/custom.conf
  grep -q '^WaylandEnable=false' /etc/gdm3/custom.conf || \
    echo "[daemon]"$'\n'"WaylandEnable=false" | sudo tee -a /etc/gdm3/custom.conf >/dev/null
fi
# Autologowanie — żeby po restarcie panel wstał bez klawiatury (odkomentuj user po instalacji).
echo "   (Autologowanie ustaw w Ustawienia → Użytkownicy, albo w /etc/gdm3/custom.conf: AutomaticLoginEnable=true)"

echo "== 5/5 Panel (Edge + noVNC + notifier) jako usługa użytkownika =="
mkdir -p "$APPDIR"
cp "$HERE/panel.py" "$HERE/panel.html" "$HERE/cdp.py" "$HERE/notifier.py" "$HERE/teams-panel.sh" "$APPDIR/"
chmod +x "$APPDIR/teams-panel.sh"

# Konfiguracja push/ekran — edytuj po instalacji: ~/.config/teams-panel.env
CFG="$HOME/.config/teams-panel.env"
if [ ! -f "$CFG" ]; then
  cat > "$CFG" <<'ENV'
# Temat ntfy.sh na push o nowych wiadomościach (zostaw puste, by wyłączyć):
NTFY_TOPIC=
# Treść wiadomości w pushu (true) czy tylko „Nowa wiadomość: nadawca" (false):
NOTIFY_PREVIEW=true
# Cisza nocna, np. 22:00-07:00 (puste = bez ciszy):
QUIET_HOURS=
# Zewnętrzny adres HA do linku w pushu (opcjonalnie):
EXTERNAL_URL=
# Rozdzielczość wirtualnego ekranu panelu i skala (jak w dodatku):
SCREEN_WIDTH=840
SCREEN_HEIGHT=1800
SCALE=1
# Adres startowy:
START_URL=https://teams.microsoft.com/v2/
LOG_LEVEL=info
ENV
  echo "   Utworzono $CFG — ustaw NTFY_TOPIC jeśli chcesz push."
fi

mkdir -p "$HOME/.config/systemd/user"
cp "$HERE/teams-panel.service" "$HOME/.config/systemd/user/teams-panel.service"
systemctl --user daemon-reload || true
# Lingering: usługa użytkownika ma działać też bez zalogowanej sesji graficznej na konsoli.
sudo loginctl enable-linger "$USER" || true

echo
echo "== GOTOWE =="
echo "Dalej RĘCZNIE (jednorazowo):"
echo "  1) Zrestartuj VM i zaloguj się (sesja Xorg)."
echo "  2) W Edge zaloguj się firmowym kontem (to zarejestruje urządzenie przez brokera)."
echo "     Szczegóły i weryfikacja: README.md."
echo "  3) Sprawdź: dsreg --status   → ma pokazać 'Registered/Joined' i 'PRT Present: YES'."
echo "  4) Uruchom panel:  systemctl --user enable --now teams-panel"
echo "     Panel po stronie telefonu: http://<IP-VM>:8099/ (lub przez HA iframe / tunel — README.md)."
