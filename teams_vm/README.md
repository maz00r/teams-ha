# Teams na telefonie — przez zaufaną VM Ubuntu Desktop

Ten wariant omija problem, który zablokował dodatek HA: firmowa reguła dostępu
warunkowego Nexi wpuszcza do Teams **tylko urządzenia zarejestrowane w Entra ID**
(błąd `53003`, „Device state: Unregistered"). Mac i Windows rejestrują się same.
Linux potrafi to zrobić przez `microsoft-identity-broker`, ale **okno logowania
brokera wymaga prawdziwego pulpitu** — w kontenerze HA gaśnie na czarno.

Rozwiązanie: mała **VM z Ubuntu Desktop (GUI)** na tym samym hoście co Twój HAOS.
Broker ma tam okno logowania i zarejestruje urządzenie jak Mac/Windows, a nasz panel
(Edge + noVNC + push) wysyła Teams na telefon — dokładnie jak w dodatku.

> **Uczciwie o niepewnym:** nie mam dostępu do Twojego hipernadzorcy ani nie przejdę
> za Ciebie logowania, więc kroki 1–3 robisz Ty. Nie przetestowałem tych skryptów na
> żywej VM. Zostają też dwie niewiadome tenantu Nexi: czy pozwala zarejestrować
> (dołączyć) urządzenie z Linuksem i czy robi to bez zgód IT (Ty twierdzisz, że tak,
> skoro Mac/Windows działają). To zweryfikujemy dopiero na VM.

---

## 1. Utwórz VM (na hoście, gdzie działa HAOS)

- System: **Ubuntu Desktop 24.04 LTS** (z GNOME; wersja „Desktop", nie „Server").
- Zasoby: 2 vCPU, **4 GB RAM**, 25 GB dysku.
- Ustaw **autostart VM z hostem** i **wyłącz usypianie** (w VM: Ustawienia → Zasilanie →
  „Zawieszanie przy bezczynności" = Nigdy; wygaszacz ekranu = nigdy).
- Zalecane **autologowanie** użytkownika (Ustawienia → Użytkownicy → Automatyczne
  logowanie). Dzięki temu po restarcie keyring jest odblokowany, a panel wstaje sam.

## 2. Zainstaluj (skrypt)

Skopiuj cały katalog `teams_vm/` na VM (np. przez `scp`, Samba albo `git clone`
repozytorium `maz00r/teams-ha`), potem:

```bash
cd teams_vm
chmod +x setup.sh teams-panel.sh
./setup.sh          # poprosi o hasło (sudo); NIE uruchamiaj przez sudo
```

Skrypt instaluje Microsoft Edge, `microsoft-identity-broker`, noVNC i Pythona,
przełącza GDM na **Xorg** (x11vnc nie działa z Wayland) i instaluje panel jako usługę
użytkownika. **Zrestartuj VM** po instalacji (wejdzie sesja Xorg).

## 3. Zarejestruj urządzenie (jednorazowo, w pulpicie VM)

1. W VM otwórz **Microsoft Edge** i zaloguj się **firmowym kontem** (to samo, co na
   telefonie). Przejdź pełne logowanie (hasło, MFA). Jeśli pojawi się pytanie o
   zarejestrowanie / dołączenie urządzenia do organizacji — **zaakceptuj**.
2. Sprawdź stan:

   ```bash
   dsreg --status
   ```

   Ma pokazać `Device Registration Status : Registered` (lub Joined) i
   `PRT Present : YES`. Jeśli tak — otwórz `https://teams.microsoft.com/` w Edge:
   powinno wejść **bez błędu 53003**.

> Jeśli `dsreg` dalej pokazuje „Not Registered" albo logowanie wraca z 53003:
> najpewniej tenant Nexi nie pozwala dołączać urządzeń z Linuksem (ustawienie
> „Users may join devices"). Wtedy zostaje kontyngencja ze starszym brokerem
> (rejestracja zamiast join) na Ubuntu 22.04 — napisz, sprawdzimy. Diagnostyka:
> `journalctl --user -u microsoft-identity-broker` oraz pakiet
> `microsoft-identity-diagnostics`.

## 4. Włącz panel

```bash
# opcjonalnie: ustaw push na telefon (ntfy.sh)
nano ~/.config/teams-panel.env      # wpisz NTFY_TOPIC=twoj-temat

systemctl --user enable --now teams-panel
systemctl --user status teams-panel --no-pager
```

Panel działa na porcie **8099** VM. Pierwsze wejście: otwórz `http://<IP-VM>:8099/`
na telefonie i w panelu zaloguj się do Teams (konto jak wyżej) — teraz, gdy urządzenie
jest zarejestrowane, Teams wpuści. Obsługa panelu (pisanie z polskimi znakami,
przewijanie dwoma palcami, przyciski) jak w [../teams_browser/README.md](../teams_browser/README.md).

## 5. Dostęp z telefonu spoza domu

Dwie drogi (wybierz jedną):

- **Panel iframe w HA** — w `configuration.yaml` Home Assistanta dodaj:

  ```yaml
  panel_iframe:
    teams:
      title: "Teams"
      icon: mdi:microsoft-teams
      url: "https://twoj-adres-vm-przez-tunel/"   # URL panelu VM wystawiony tunelem
  ```

  Wtedy „Teams" pojawia się w menu bocznym aplikacji HA, jak teraz.
- **Tunel bez HA** — wystaw `http://<IP-VM>:8099/` przez Twój Cloudflared albo
  Tailscale i wejdź bezpośrednio z telefonu.

> Panel nie ma własnego logowania (jak Ingress w HA), więc **nie wystawiaj portu 8099
> wprost do internetu**. Zawsze przez HA (uwierzytelnianie HA) albo Tailscale
> (prywatna sieć) / Cloudflare Access.

## Push o nowych wiadomościach

Na VM push idzie przez **ntfy.sh** (ustaw `NTFY_TOPIC` w `~/.config/teams-panel.env`).
Notifier przez CDP przechwytuje powiadomienia Teams (nadawca + treść) i wysyła je na
ten temat; na telefonie subskrybujesz temat w aplikacji ntfy. Powiadomienia do usług
`notify.*` Home Assistanta można dołożyć później (webhookiem HA) — napisz, jeśli
chcesz je zamiast/obok ntfy.

## Co z dodatkami na HA

Dodatki `teams_browser` (Chromium) i `teams_edge` (kontener) **nie przejdą** reguły
Nexi, więc zostały zatrzymane i mają wyłączony autostart. Kod panelu żyje dalej —
to z niego korzysta ta VM.
