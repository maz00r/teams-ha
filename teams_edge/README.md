# Teams (Edge + rejestracja urządzenia) — wersja eksperymentalna

Jak `teams_browser`, ale na **Microsoft Edge** z **brokerem tożsamości Microsoftu**
(`microsoft-identity-broker`). Broker potrafi **zarejestrować urządzenie w Entra ID**,
dzięki czemu firmowa reguła dostępu warunkowego „tylko zarejestrowane urządzenia"
(błąd 53003 „Unregistered") może zostać spełniona zgodnie z jej przeznaczeniem — bez
podszywania się pod inny system.

> **To nie jest obejście zabezpieczeń.** Urządzenie realnie rejestruje się w tenantcie
> i staje się widoczne dla działu IT. Jeśli Twoja firma nie zezwala na rejestrację
> Linuksa, logowanie nadal zostanie odrzucone. Warto, by IT o tym wiedziało.

## Czym się różni od `teams_browser`

- Baza **Ubuntu + Microsoft Edge** zamiast Alpine + Chromium (obraz ~1,5 GB, RAM ~1,5–2 GB).
- Wstaje szyna D-Bus (systemowa i sesyjna), odblokowany `gnome-keyring` i **broker
  urządzenia** — bez tego dostęp warunkowy nie przejdzie.
- Panel, pisanie i powiadomienia działają tak samo jak w `teams_browser`.
- Tylko `amd64`.

## Rejestracja i logowanie

1. Otwórz panel **Teams Edge**, zaloguj się na firmowe konto Microsoft.
2. Gdy pojawi się pytanie o zarejestrowanie / „dołączenie" urządzenia do organizacji —
   zaakceptuj rejestrację. (Jeśli chcesz tylko rejestracji, a nie pełnego zarządzania,
   nie zaznaczaj opcji oddającej urządzenie pod zarządzanie, o ile taka się pojawi.)
3. Stan rejestracji widać w **Dzienniku** dodatku (`dsreg --status`) przy każdym starcie.

Pozostałe opcje i obsługa panelu — jak w [../teams_browser/README.md](../teams_browser/README.md).
