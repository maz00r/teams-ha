#!/usr/bin/env python3
"""Panel dodatku (Home Assistant Ingress) — Teams na ekranie telefonu.

Ingress udostępnia dokładnie JEDEN port, więc ten serwer stoi na 8099 i rozdziela ruch:
  * `/`             -> mobilna strona panelu (obraz + pasek pisania),
  * `/api/*`        -> akcje w przeglądarce przez CDP (wpisz, klawisz, przewiń, nawigacja),
  * `/websockify`   -> tunel bajt-w-bajt do websockify (obraz z Chromium),
  * reszta          -> pliki statyczne noVNC z dysku (core/rfb.js i spółka).
"""

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import cdp

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL_PORT = int(os.environ.get("PANEL_PORT") or 8099)
WEBSOCKIFY_PORT = int(os.environ.get("WEBSOCKIFY_PORT") or 6080)
NOVNC_DIR = os.environ.get("NOVNC_DIR") or "/usr/share/novnc"
PANEL_HTML = os.path.join(HERE, "panel.html")
START_URL = os.environ.get("START_URL") or "https://teams.microsoft.com/v2/"
STATUS_PATH = os.environ.get("STATUS_PATH") or "/data/status.json"
MAX_TEXT = 4000
# Panel otwarty na telefonie co 20 s daje znać, że ktoś patrzy. Notifier na tej
# podstawie mówi Teams „okno w tle" — wtedy otwarty czat nie jest uznawany za przeczytany.
VIEWER_TTL = 45
_last_heartbeat = 0.0

MIME = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".map": "application/json",
}


def log(*args):
    print("[panel]", *args, flush=True)


def safe_static_path(path):
    """Ścieżka pliku noVNC albo None. Normalizacja ucina każdą próbę wyjścia poza katalog."""
    target = os.path.realpath(os.path.join(NOVNC_DIR, unquote(path).lstrip("/")))
    root = os.path.realpath(NOVNC_DIR)
    if target != root and not target.startswith(root + os.sep):
        return None
    return target if os.path.isfile(target) else None


def read_status():
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def viewer_active(now=None):
    return ((now or time.time()) - _last_heartbeat) < VIEWER_TTL


def run_action(path, body):
    """Wykonuje akcję z panelu. Zwraca (kod HTTP, odpowiedź JSON)."""
    global _last_heartbeat
    if path == "/api/heartbeat":
        _last_heartbeat = 0.0 if body.get("leaving") else time.time()
        return 200, {"ok": True}
    if path == "/api/type":
        text = body.get("text")
        if not isinstance(text, str) or not text:
            return 400, {"ok": False, "error": "pusty tekst"}
        if len(text) > MAX_TEXT:
            return 400, {"ok": False, "error": "za długi tekst"}
        cdp.insert_text(text)
        if body.get("enter"):
            cdp.press_key("Enter")
        return 200, {"ok": True}
    if path == "/api/key":
        name = body.get("key")
        if name not in cdp.KEYS:
            return 400, {"ok": False, "error": "nieznany klawisz"}
        cdp.press_key(name)
        return 200, {"ok": True}
    if path == "/api/scroll":
        direction = body.get("dir")
        if direction not in ("up", "down"):
            return 400, {"ok": False, "error": "kierunek: up|down"}
        cdp.scroll(direction)
        return 200, {"ok": True}
    if path == "/api/nav":
        action = body.get("action")
        if action not in ("back", "reload", "home"):
            return 400, {"ok": False, "error": "akcja: back|reload|home"}
        cdp.nav(action, START_URL)
        return 200, {"ok": True}
    return 404, {"ok": False, "error": "nieznany endpoint"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "teams-panel"

    def log_message(self, fmt, *args):  # cisza — Dziennik dodatku ma być czytelny
        pass

    def _send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload, ensure_ascii=False),
                   "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        try:
            doc = json.loads(self.rfile.read(min(length, 64 * 1024)) or b"{}")
        except (ValueError, OSError):
            return {}
        return doc if isinstance(doc, dict) else {}

    def do_GET(self):
        path = urlparse(self.path).path
        if (self.headers.get("Upgrade") or "").lower() == "websocket":
            return self.tunnel_websocket()
        if path in ("/", "/index.html"):
            return self.serve_panel()
        if path == "/api/status":
            return self._json(read_status())
        if path == "/api/viewer":
            return self._json({"active": viewer_active()})
        return self.serve_static(path)

    do_HEAD = do_GET

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            code, payload = run_action(path, self._body())
        except Exception as e:  # noqa: BLE001 - błąd przeglądarki nie może wywrócić panelu
            log(f"! {path}: {e!r}")
            code, payload = 502, {"ok": False, "error": str(e)}
        self._json(payload, code)

    def serve_panel(self):
        try:
            with open(PANEL_HTML, "rb") as f:
                page = f.read()
        except OSError as e:
            return self._send(500, f"Brak panel.html: {e}", "text/plain; charset=utf-8")
        self._send(200, page, "text/html; charset=utf-8", {"Cache-Control": "no-store"})

    def serve_static(self, path):
        """Pliki noVNC z dysku (core/*, vendor/*)."""
        target = safe_static_path(path)
        if not target:
            return self._send(404, "Nie znaleziono", "text/plain; charset=utf-8")
        try:
            with open(target, "rb") as f:
                data = f.read()
        except OSError:
            return self._send(404, "Nie znaleziono", "text/plain; charset=utf-8")
        ctype = MIME.get(os.path.splitext(target)[1].lower(), "application/octet-stream")
        self._send(200, data, ctype)

    def tunnel_websocket(self):
        """Przepuszcza uścisk dłoni i ramki do websockify — Ingress ma tylko jeden port.

        Po uścisku dłoni to już zwykły strumień bajtów w obie strony, więc nie
        interpretujemy ramek: dwa wątki przepychają dane, aż któraś strona zamknie.
        """
        try:
            upstream = socket.create_connection(("127.0.0.1", WEBSOCKIFY_PORT), timeout=10)
        except OSError as e:
            return self._send(502, f"noVNC jeszcze nie wystartował ({e})",
                              "text/plain; charset=utf-8")
        self.close_connection = True
        try:
            head = [self.raw_requestline.rstrip(b"\r\n")]
            head += [f"{k}: {v}".encode("latin-1", "replace") for k, v in self.headers.items()]
            upstream.sendall(b"\r\n".join(head) + b"\r\n\r\n")
            upstream.settimeout(None)
            self.connection.settimeout(None)
            pump = threading.Thread(target=self._upstream_to_client, args=(upstream,), daemon=True)
            pump.start()
            while True:
                data = self.rfile.read1(65536)
                if not data:
                    break
                upstream.sendall(data)
        except OSError:
            pass
        finally:
            try:
                upstream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            upstream.close()

    def _upstream_to_client(self, upstream):
        try:
            while True:
                data = upstream.recv(65536)
                if not data:
                    break
                self.wfile.write(data)
                self.wfile.flush()
        except OSError:
            pass
        finally:
            try:
                self.connection.shutdown(socket.SHUT_RD)
            except OSError:
                pass


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PANEL_PORT), Handler)
    server.daemon_threads = True
    log(f"panel na porcie {PANEL_PORT} (noVNC: {NOVNC_DIR}, websockify: {WEBSOCKIFY_PORT})")
    server.serve_forever()


if __name__ == "__main__":
    main()
