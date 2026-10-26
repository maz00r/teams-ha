# Teams (przeglądarka na telefon) — dodatek Home Assistant

Microsoft Teams działa w przeglądarce Chromium **na serwerze Home Assistanta**, a Ty
oglądasz go i obsługujesz w panelu HA — z telefonu, bez instalowania aplikacji Teams.
Ekran jest pionowy i wąski, więc Teams układa się jak na telefonie. Dodatek wysyła też
**push o nowych wiadomościach** (nadawca + treść).

Zakres: czat i kanały. Spotkania z dźwiękiem/wideo **nie działają** (obraz idzie przez VNC).

## Instalacja

1. **Ustawienia → Dodatki → Sklep z dodatkami → ⋮ → Repozytoria** → dodaj
   `https://github.com/maz00r/teams-ha`.
2. Zainstaluj **Teams (przeglądarka na telefon)**, ustaw opcje (niżej), **Uruchom**.
3. Otwórz panel **Teams** w menu bocznym i zaloguj się do Microsoft (zaznacz
   „Nie wylogowuj mnie"). Profil przeglądarki jest trwały — logujesz się raz.

## Obsługa w panelu

- **Stuknięcie** w obraz = kliknięcie. **Dwa palce w górę/dół** = przewijanie
  (zapasowo przyciski ▲ ▼).
- **Pisanie**: stuknij pole w Teams (np. okno wiadomości), potem pisz w polu
  *Pisz tutaj…* na dole. **Wyślij** wpisuje tekst i naciska Enter, **✎** tylko wpisuje.
  Polskie znaki i emoji działają.
- Przyciski: 🏠 wraca do Teams (zamyka otwarte linki), ◀ wstecz, ⏎ Enter, ⌫, Esc, Tab, ⟳ odśwież.

## Opcje

| Opcja | Opis |
|---|---|
| `notify_service` | Usługa(i) powiadomień HA, np. `notify.mobile_app_iphone`. Kilka po przecinku. |
| `ntfy_topic` | Temat na [ntfy.sh](https://ntfy.sh) (opcjonalnie, zamiast lub obok HA). |
| `notify_preview` | `true` — w pushu treść wiadomości; `false` — tylko „Nowa wiadomość: nadawca". |
| `quiet_hours` | Cisza, np. `22:00-07:00` — bez pushy w tym czasie. |
| `external_url` | Zewnętrzny adres HA (np. `https://ha.example.com`) — link w pushu ntfy. |
| `screen_width` / `screen_height` / `scale` | Wirtualny ekran. Domyślnie 1000×2160 przy skali 2 = okno 500×1080 px (500 to minimum Chromium). |
| `start_url` | Adres Teams, domyślnie `https://teams.microsoft.com/v2/`. |

## Jak działa

- Xvfb (pionowy ekran) → Chromium w trybie kiosk z trwałym profilem w `/data` →
  x11vnc → websockify → `panel.py` (Ingress, jedyny wystawiony port).
- `notifier.py` przez Chrome DevTools Protocol wstrzykuje do Teams nakładkę na
  `Notification`/`showNotification`/`setAppBadge` — stąd nadawca i treść pusha.
  Zapasowo pilnuje licznika nieprzeczytanych.
- Gdy panel nie jest otwarty na telefonie, Teams dostaje informację, że okno nie ma
  fokusu — inaczej otwarty czat uznawałby nowe wiadomości za przeczytane i nie
  powiadamiał.
- Encja `sensor.teams_unread` (atrybut `logged_in`) — do dashboardu i automatyzacji.
- Gdy Microsoft wyloguje sesję na dłużej niż 3 min, dostaniesz push „Teams wylogowany".

## Bezpieczeństwo

Nic nie jest wystawione poza Ingress (logowanie HA). VNC i DevTools słuchają tylko na
localhost w kontenerze. Hasło wpisujesz sam w oknie logowania Microsoft.
Obraz ma ~800 MB; Chromium z Teams zużywa ok. 1–1,5 GB RAM.
