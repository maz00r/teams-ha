# Changelog

## 0.2.1

- Rejestracja urządzenia wymaga logowania do SAMEJ przeglądarki Edge (nie tylko do
  karty Teams) — tylko wtedy auth idzie przez brokera i robi Workplace Join.
  Wyłączony tryb kiosk (widać przycisk konta) + wymuszone logowanie do Edge
  (polityka BrowserSignin=2).

## 0.2.0

- Pierwsza wersja wariantu Edge: Ubuntu + Microsoft Edge + microsoft-identity-broker,
  rejestracja urządzenia w Entra ID. Broker urządzenia uruchamiany ręcznie (brak systemd),
  D-Bus i gnome-keyring montowane w run.sh.
