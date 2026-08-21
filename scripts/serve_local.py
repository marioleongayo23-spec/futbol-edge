#!/usr/bin/env python3
"""Servidor local de Fútbol Edge (100% en tu PC, sin GitHub).

Sirve la app compilada (app/dist) y, en /dashboard.json, SIEMPRE el feed más
reciente generado en football/data/dashboard.json. Así la app lee los datos de
tu propio disco, no de internet.

    python scripts/serve_local.py            # http://localhost:8080
    PORT=9000 python scripts/serve_local.py
"""

from __future__ import annotations

import http.server
import os
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "app" / "dist"
FEED = ROOT / "football" / "data" / "dashboard.json"
PORT = int(os.environ.get("PORT", "8080"))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(DIST), **k)

    def _send_feed(self) -> None:
        if not FEED.exists():
            self.send_error(404, "feed no generado todavía (ejecuta el refresco)")
            return
        data = FEED.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/dashboard.json", "/futbol-edge/dashboard.json"):
            self._send_feed()
            return
        # SPA: rutas desconocidas (sin extensión) -> index.html
        if path != "/" and "." not in path.rsplit("/", 1)[-1]:
            self.path = "/index.html"
        super().do_GET()

    def do_HEAD(self):  # noqa: N802
        if self.path.split("?", 1)[0].endswith("dashboard.json"):
            self._send_feed()
            return
        super().do_HEAD()

    def log_message(self, fmt, *args):  # menos ruido
        pass


def main() -> int:
    if not DIST.exists():
        print(f"No existe {DIST}. Compila antes:  cd app && VITE_FEED_URL=/dashboard.json npm run build")
        return 1
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Fútbol Edge en local:  http://localhost:{PORT}")
        print("Ctrl+C para parar.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nParado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
