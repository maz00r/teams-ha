# Changelog

## 0.2.3

- Wymuszenie programowego renderowania WebKitGTK (WEBKIT_DISABLE_DMABUF_RENDERER i spółka),
  bo okno logowania Microsoft potrafi na serwerze bez GPU narysować się na czarno.

## 0.2.2

- Okno logowania Edge ma stały rozmiar ~800 px; przy skali 2 rysowało się jako 1600 px
  i przycisk „Sign in" wypadał poza wirtualny ekran — nie dało się kliknąć. Domyślnie
  ekran 840x1800 przy skali 1, więc panel logowania (i przycisk rejestracji) mieści się
  w całości. Rozdzielczość na czas rejestracji; po zalogowaniu można wrócić do wariantu
  gęstszego.

## 0.2.1

- Rejestracja urządzenia wymaga logowania do SAMEJ przeglądarki Edge (nie tylko do
  karty Teams) — tylko wtedy auth idzie przez brokera i robi Workplace Join.
  Wyłączony tryb kiosk (widać przycisk konta) + wymuszone logowanie do Edge
  (polityka BrowserSignin=2).

## 0.2.0

- Pierwsza wersja wariantu Edge: Ubuntu + Microsoft Edge + microsoft-identity-broker,
  rejestracja urządzenia w Entra ID. Broker urządzenia uruchamiany ręcznie (brak systemd),
  D-Bus i gnome-keyring montowane w run.sh.
