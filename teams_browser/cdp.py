#!/usr/bin/env python3
"""Minimalny klient Chrome DevTools Protocol + akcje używane przez panel.

Chromium słucha CDP na 127.0.0.1:9222. Panel otwiera krótkie połączenia (wpisz
tekst, naciśnij klawisz, przewiń), notifier trzyma jedno długie i słucha zdarzeń.
"""

import collections
import json
import os
import time
import urllib.error
import urllib.request

CDP_URL = os.environ.get("CDP_URL") or "http://127.0.0.1:9222"

# Teams v2 mieszka pod kilkoma domenami (stara i nowa „cloud.microsoft").
TEAMS_HOSTS = ("teams.microsoft.com", "teams.cloud.microsoft", "teams.live.com")
LOGIN_HOSTS = ("login.microsoftonline.com", "login.live.com", "login.microsoft.com")

# Klawisze dostępne z panelu: nazwa -> (key, code, windowsVirtualKeyCode, text)
KEYS = {
    "Enter": ("Enter", "Enter", 13, "\r"),
    "Backspace": ("Backspace", "Backspace", 8, ""),
    "Escape": ("Escape", "Escape", 27, ""),
    "Tab": ("Tab", "Tab", 9, ""),
    "ArrowUp": ("ArrowUp", "ArrowUp", 38, ""),
    "ArrowDown": ("ArrowDown", "ArrowDown", 40, ""),
    "PageUp": ("PageUp", "PageUp", 33, ""),
    "PageDown": ("PageDown", "PageDown", 34, ""),
}


def is_teams_url(url):
    return any(h in (url or "") for h in TEAMS_HOSTS)


def is_login_url(url):
    return any(h in (url or "") for h in LOGIN_HOSTS)


def page_targets(cdp_url=None):
    """Karty (type=page) z otwartym gniazdem debuggera; [] gdy Chromium jeszcze nie wstał."""
    try:
        with urllib.request.urlopen(f"{cdp_url or CDP_URL}/json/list", timeout=5) as r:
            targets = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return []
    return [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]


def pick_main(pages):
    """Karta z Teams (albo z logowaniem Microsoft), a w ostateczności pierwsza."""
    for test in (is_teams_url, is_login_url):
        for t in pages:
            if test(t.get("url")):
                return t
    return pages[0] if pages else None


class Cdp:
    def __init__(self, ws_url, timeout=15):
        import websocket  # websocket-client; import tutaj, żeby testy działały bez paczki
        self._websocket = websocket
        self.ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
        self._id = 0
        self.events = collections.deque()

    def call(self, method, **params):
        self._id += 1
        my_id = self._id
        self.ws.send(json.dumps({"id": my_id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == my_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def next_event(self, timeout):
        """Następne zdarzenie CDP albo None po `timeout` sekundach ciszy."""
        if self.events:
            return self.events.popleft()
        self.ws.settimeout(timeout)
        try:
            while True:
                msg = json.loads(self.ws.recv())
                if "method" in msg:
                    return msg
        except self._websocket.WebSocketTimeoutException:
            return None

    def evaluate(self, expression):
        res = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        return (res.get("result") or {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def _with_main(fn):
    pages = page_targets()
    main = pick_main(pages)
    if not main:
        raise RuntimeError("przeglądarka jeszcze nie wystartowała")
    cdp = Cdp(main["webSocketDebuggerUrl"])
    try:
        return fn(cdp, main, pages)
    finally:
        cdp.close()


def insert_text(text):
    """Wpisuje tekst w pole z fokusem — także polskie znaki i emoji (VNC tego nie umie)."""
    return _with_main(lambda cdp, *_: cdp.call("Input.insertText", text=text))


def press_key(name):
    if name not in KEYS:
        raise ValueError(f"nieznany klawisz: {name}")
    key, code, vk, text = KEYS[name]

    def run(cdp, *_):
        base = {"key": key, "code": code, "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk}
        down = dict(base, type="keyDown")
        if text:
            down["text"] = text
            down["unmodifiedText"] = text
        cdp.call("Input.dispatchKeyEvent", **down)
        cdp.call("Input.dispatchKeyEvent", **dict(base, type="keyUp"))
    return _with_main(run)


def scroll(direction, x_frac=0.5, y_frac=0.5):
    """Kółko myszy w punkcie ekranu (ułamki szerokości/wysokości) — zapas dla gestów."""
    def run(cdp, *_):
        size = cdp.evaluate("[innerWidth, innerHeight]") or [400, 800]
        x, y = size[0] * float(x_frac), size[1] * float(y_frac)
        delta = -size[1] * 0.6 if direction == "up" else size[1] * 0.6
        cdp.call("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y,
                 deltaX=0, deltaY=delta)
    return _with_main(run)


def nav(action, start_url):
    """back | reload | home (zamyka zbędne karty i wraca do Teams)."""
    if action == "home":
        pages = page_targets()
        main = pick_main(pages)
        for t in pages:
            if main and t["id"] != main["id"]:
                try:
                    urllib.request.urlopen(f"{CDP_URL}/json/close/{t['id']}", timeout=5).read()
                except (urllib.error.URLError, OSError):
                    pass
        if main:
            urllib.request.urlopen(f"{CDP_URL}/json/activate/{main['id']}", timeout=5).read()
            if not (is_teams_url(main.get("url")) or is_login_url(main.get("url"))):
                _with_main(lambda cdp, *_: cdp.call("Page.navigate", url=start_url))
        return
    if action == "back":
        return _with_main(lambda cdp, *_: cdp.evaluate("history.back()"))
    if action == "reload":
        return _with_main(lambda cdp, *_: cdp.call("Page.reload"))
    raise ValueError(f"nieznana akcja: {action}")


def wait_for_browser(retries=60):
    for _ in range(retries):
        if page_targets():
            return True
        time.sleep(1)
    return False
