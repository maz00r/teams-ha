# Changelog

## 0.1.2

- Fałszywy alarm „Teams wylogowany": przekierowanie do logowania tuż po starcie
  było brane za utratę sesji. Sesja liczy się dopiero po minucie w Teams.

## 0.1.1

- Pusty `external_url` blokował zapis konfiguracji — pole jest teraz zwykłym tekstem.

## 0.1.0

- Pierwsza wersja: Teams w Chromium na pionowym ekranie, panel mobilny (noVNC +
  pasek pisania przez CDP z polskimi znakami), push o nowych wiadomościach
  (notify HA / ntfy), `sensor.teams_unread`, alert o wylogowaniu.
