#!/usr/bin/env python3
"""Notifier: pilnuje Teams w przeglądarce i wysyła push o nowych wiadomościach.

Przez CDP wstrzykuje do Teams nakładkę na `Notification`, `showNotification`
i `navigator.setAppBadge` — dzięki temu wiemy, kto napisał i co (jak w aplikacji),
a licznik nieprzeczytanych służy za zapas, gdy Teams nie pokaże powiadomienia.

Gdy nikt nie patrzy na panel (brak „bicia serca" z telefonu), Teams dostaje sygnał,
że okno straciło fokus — inaczej uznałby otwarty czat za przeczytany i milczał.

Push idzie do usług `notify.*` Home Assistanta i/lub na ntfy.sh. Stan (licznik,
zalogowanie) trafia do /data/status.json (panel) i do `sensor.teams_unread`.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime

import cdp

BINDING = "__haTeamsEvent"
SUPERVISOR = "http://supervisor"
PANEL_URL = os.environ.get("PANEL_URL") or "http://127.0.0.1:8099"
STATUS_PATH = os.environ.get("STATUS_PATH") or "/data/status.json"
POLL_SECONDS = 10
DEDUP_SECONDS = 120
FALLBACK_GRACE = 25          # tyle czekamy na „prawdziwe" powiadomienie, zanim wyślemy licznik
LOGOUT_GRACE = 180           # wylogowanie dłuższe niż to -> push

HOOK_JS = r"""
(() => {
  if (window.__haTeamsHooked) return;
  window.__haTeamsHooked = true;
  const emit = (doc) => { try { window.%(b)s(JSON.stringify(doc)); } catch (e) {} };

  // Nieobecność: gdy nikt nie patrzy na panel, okno udaje brak fokusu.
  window.__haTeamsAway = false;
  const realHasFocus = Document.prototype.hasFocus;
  Document.prototype.hasFocus = function () {
    return window.__haTeamsAway ? false : realHasFocus.call(this);
  };

  const RealN = window.Notification;
  if (RealN) {
    const Hooked = function (title, opts) {
      opts = opts || {};
      emit({ kind: "notify", title: String(title || ""), body: String(opts.body || ""),
             tag: String(opts.tag || "") });
      try { return new RealN(title, opts); }
      catch (e) { const t = new EventTarget(); t.close = () => {}; return t; }
    };
    Object.defineProperty(Hooked, "permission", { get: () => "granted" });
    Hooked.requestPermission = (cb) => { if (cb) cb("granted"); return Promise.resolve("granted"); };
    Hooked.prototype = RealN.prototype;
    window.Notification = Hooked;
  }

  const SWR = window.ServiceWorkerRegistration;
  if (SWR && SWR.prototype.showNotification) {
    const real = SWR.prototype.showNotification;
    SWR.prototype.showNotification = function (title, opts) {
      opts = opts || {};
      emit({ kind: "notify", title: String(title || ""), body: String(opts.body || ""),
             tag: String(opts.tag || "") });
      return real.call(this, title, opts);
    };
  }

  if (navigator.setAppBadge) {
    const realSet = navigator.setAppBadge.bind(navigator);
    navigator.setAppBadge = (n) => { emit({ kind: "badge", n: n == null ? -1 : Number(n) }); return realSet(n).catch(() => {}); };
    const realClear = navigator.clearAppBadge.bind(navigator);
    navigator.clearAppBadge = () => { emit({ kind: "badge", n: 0 }); return realClear().catch(() => {}); };
  }
})();
""" % {"b": BINDING}


LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}


def log(*args, level="info"):
    want = LEVELS.get((os.environ.get("LOG_LEVEL") or "info").lower(), 20)
    if LEVELS.get(level, 20) >= want:
        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"{stamp} [teams]", *args, flush=True)


# ------------------------------------------------------------------ czyste funkcje

TITLE_COUNT = re.compile(r"^\s*\((\d+)\)")


def parse_title_count(title):
    """„(3) Czat | Microsoft Teams" -> 3; brak nawiasu -> 0."""
    m = TITLE_COUNT.match(title or "")
    return int(m.group(1)) if m else 0


def parse_quiet_hours(spec):
    """„22:00-07:00" -> ((22, 0), (7, 0)); pusty/błędny -> None."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", spec or "")
    if not m:
        return None
    a, b, c, d = (int(x) for x in m.groups())
    if a > 23 or c > 23 or b > 59 or d > 59:
        return None
    return (a, b), (c, d)


def in_quiet_hours(spec, now):
    rng = parse_quiet_hours(spec)
    if not rng:
        return False
    start, end = (h * 60 + m for h, m in rng)
    cur = now.hour * 60 + now.minute
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end  # przez północ


def parse_services(spec):
    """„notify.mobile_app_x, mobile_app_y" -> [("notify","mobile_app_x"), ("notify","mobile_app_y")]."""
    out = []
    for part in re.split(r"[,\s]+", spec or ""):
        part = part.strip()
        if not part:
            continue
        domain, _, service = part.partition(".")
        if not service:
            domain, service = "notify", domain
        if re.fullmatch(r"[a-z0-9_]+", domain) and re.fullmatch(r"[a-z0-9_]+", service):
            out.append((domain, service))
    return out


def build_message(event, preview):
    """Tytuł i treść pusha z przechwyconego powiadomienia Teams."""
    who = (event.get("title") or "").strip() or "Teams"
    body = (event.get("body") or "").strip()
    if not preview or not body:
        return "Teams", f"Nowa wiadomość: {who}"
    if len(body) > 300:
        body = body[:297] + "…"
    return who, body


def truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class Deduper:
    """Teams potrafi zgłosić to samo powiadomienie kilka razy (np. dwie zakładki/ramki)."""

    def __init__(self, ttl=DEDUP_SECONDS):
        self.ttl = ttl
        self.seen = {}

    def fresh(self, key, now):
        for k, t in list(self.seen.items()):
            if now - t > self.ttl:
                del self.seen[k]
        if key in self.seen:
            return False
        self.seen[key] = now
        return True


class UnreadTracker:
    """Licznik nieprzeczytanych jako zapas: push, gdy rośnie, a Teams nic nie pokazał."""

    def __init__(self):
        self.count = None
        self.pending_since = None
        self.last_notify = 0.0

    def notified(self, now):
        self.last_notify = now
        self.pending_since = None

    def update(self, count, now):
        """Zwraca liczbę do wysłania w pushu zapasowym albo None."""
        prev, self.count = self.count, count
        if prev is not None and count > prev and now - self.last_notify > FALLBACK_GRACE:
            self.pending_since = self.pending_since or now
        if count == 0:
            self.pending_since = None
        if self.pending_since and now - self.pending_since >= FALLBACK_GRACE:
            self.pending_since = None
            if now - self.last_notify > FALLBACK_GRACE:
                self.last_notify = now
                return count
        return None


# ------------------------------------------------------------------ wysyłka

def _http(url, payload=None, token=None, timeout=10, method=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


class Pusher:
    def __init__(self):
        self.token = os.environ.get("SUPERVISOR_TOKEN") or ""
        self.services = parse_services(os.environ.get("NOTIFY_SERVICE"))
        self.ntfy = (os.environ.get("NTFY_TOPIC") or "").strip()
        self.preview = truthy(os.environ.get("NOTIFY_PREVIEW", "true"))
        self.quiet = os.environ.get("QUIET_HOURS") or ""
        self.external = (os.environ.get("EXTERNAL_URL") or "").rstrip("/")
        self.panel_path = "/"
        self._last_sensor = None
        if self.token:
            try:
                info = _http(f"{SUPERVISOR}/addons/self/info", token=self.token).get("data") or {}
                if info.get("slug"):
                    self.panel_path = "/" + info["slug"]
            except (urllib.error.URLError, OSError, ValueError) as e:
                log(f"! nie znam adresu panelu ({e!r}) — kliknięcie otworzy HA", level="warn")
        if not self.services and not self.ntfy:
            log("Brak notify_service i ntfy_topic — powiadomienia push wyłączone.")

    def send(self, title, message, tag="teams"):
        if in_quiet_hours(self.quiet, datetime.now()):
            log(f"cisza nocna — pomijam: {title}", level="debug")
            return
        for domain, service in self.services:
            payload = {"title": title, "message": message, "data": {
                "url": self.panel_path, "clickAction": self.panel_path,
                "tag": tag, "group": "teams", "channel": "Teams",
            }}
            try:
                _http(f"{SUPERVISOR}/core/api/services/{domain}/{service}", payload, self.token)
            except (urllib.error.URLError, OSError, ValueError) as e:
                log(f"! {domain}.{service}: {e!r}", level="warn")
        if self.ntfy:
            doc = {"topic": self.ntfy, "title": title, "message": message, "tags": ["speech_balloon"]}
            if self.external:
                doc["click"] = self.external + self.panel_path
            try:
                _http("https://ntfy.sh", doc)
            except (urllib.error.URLError, OSError, ValueError) as e:
                log(f"! ntfy: {e!r}", level="warn")

    def sensor(self, unread, logged_in):
        state = (unread, logged_in)
        if not self.token or state == self._last_sensor:
            return
        payload = {"state": unread, "attributes": {
            "friendly_name": "Teams — nieprzeczytane", "icon": "mdi:microsoft-teams",
            "state_class": "measurement", "logged_in": logged_in,
        }}
        try:
            _http(f"{SUPERVISOR}/core/api/states/sensor.teams_unread", payload, self.token)
            self._last_sensor = state
        except (urllib.error.URLError, OSError, ValueError) as e:
            log(f"! sensor: {e!r}", level="debug")


# ------------------------------------------------------------------ pętla

def read_status():
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_status(doc):
    tmp = STATUS_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        os.replace(tmp, STATUS_PATH)
    except OSError:
        pass


def viewer_active():
    try:
        with urllib.request.urlopen(f"{PANEL_URL}/api/viewer", timeout=3) as r:
            return bool(json.loads(r.read()).get("active"))
    except (urllib.error.URLError, OSError, ValueError):
        return False


class Watcher:
    def __init__(self, pusher):
        self.pusher = pusher
        self.dedup = Deduper()
        self.unread = UnreadTracker()
        self.badge = None
        prev = read_status()
        self.was_logged_in = bool(prev.get("was_logged_in"))
        self.logged_out_since = None
        self.logout_pushed = False
        self.away = None

    def attach(self, conn):
        conn.call("Runtime.enable")
        conn.call("Page.enable")
        conn.call("Runtime.addBinding", name=BINDING)
        conn.call("Page.addScriptToEvaluateOnNewDocument", source=HOOK_JS)
        for origin in ("https://teams.microsoft.com", "https://teams.cloud.microsoft"):
            try:
                conn.call("Browser.grantPermissions", origin=origin, permissions=["notifications"])
            except RuntimeError as e:
                log(f"uprawnienie powiadomień dla {origin}: {e}", level="debug")
        conn.evaluate(HOOK_JS)
        self.away = None

    def on_event(self, msg, now):
        if msg.get("method") != "Runtime.bindingCalled":
            return
        params = msg.get("params") or {}
        if params.get("name") != BINDING:
            return
        try:
            event = json.loads(params.get("payload") or "{}")
        except ValueError:
            return
        if event.get("kind") == "badge":
            self.badge = max(0, int(event.get("n") or 0))
            log(f"plakietka: {self.badge}", level="debug")
        elif event.get("kind") == "notify":
            key = event.get("tag") or f"{event.get('title')}|{event.get('body')}"
            if not self.dedup.fresh(key, now):
                return
            self.unread.notified(now)
            title, message = build_message(event, self.pusher.preview)
            log(f"powiadomienie: {event.get('title')!r}")
            self.pusher.send(title, message)

    def tick(self, conn, now):
        state = conn.evaluate("[document.title, location.href]") or ["", ""]
        title, url = state[0] or "", state[1] or ""
        logged_in = not cdp.is_login_url(url)
        count = self.badge if self.badge is not None else parse_title_count(title)

        # nieobecność -> Teams nie uzna otwartego czatu za przeczytany
        away = not viewer_active()
        if away != self.away:
            self.away = away
            conn.evaluate(f"window.__haTeamsAway = {'true' if away else 'false'};"
                          f"window.dispatchEvent(new Event('{'blur' if away else 'focus'}'))")
            log("nikt nie patrzy — tryb tła" if away else "panel otwarty", level="debug")

        if logged_in:
            self.was_logged_in = True
            self.logged_out_since = None
            self.logout_pushed = False
            fallback = self.unread.update(count, now)
            if fallback:
                self.pusher.send("Teams", f"Nieprzeczytane: {fallback}")
        else:
            self.logged_out_since = self.logged_out_since or now
            if (self.was_logged_in and not self.logout_pushed
                    and now - self.logged_out_since > LOGOUT_GRACE):
                self.logout_pushed = True
                self.pusher.send("Teams wylogowany", "Otwórz panel Teams w HA i zaloguj się ponownie.",
                                 tag="teams-login")

        write_status({"unread": count, "logged_in": logged_in, "was_logged_in": self.was_logged_in,
                      "away": away, "updated": int(now)})
        self.pusher.sensor(count, logged_in)


def run():
    pusher = Pusher()
    watcher = Watcher(pusher)
    log("czekam na przeglądarkę…")
    while True:
        if not cdp.wait_for_browser():
            continue
        main = cdp.pick_main(cdp.page_targets())
        if not main:
            continue
        try:
            conn = cdp.Cdp(main["webSocketDebuggerUrl"])
        except Exception as e:  # noqa: BLE001
            log(f"! CDP: {e!r} — ponawiam", level="warn")
            time.sleep(5)
            continue
        log(f"podłączony do karty: {main.get('url', '')[:80]}")
        try:
            watcher.attach(conn)
            next_tick = 0.0
            while True:
                now = time.time()
                if now >= next_tick:
                    watcher.tick(conn, now)
                    next_tick = now + POLL_SECONDS
                msg = conn.next_event(timeout=max(0.5, next_tick - time.time()))
                if msg:
                    watcher.on_event(msg, time.time())
                    if msg.get("method") == "Inspector.detached":
                        break
        except Exception as e:  # noqa: BLE001 - karta zamknięta, Chromium restartuje itp.
            log(f"połączenie z kartą zerwane ({e!r}) — podłączam ponownie", level="debug")
        finally:
            conn.close()
        time.sleep(3)


if __name__ == "__main__":
    run()
