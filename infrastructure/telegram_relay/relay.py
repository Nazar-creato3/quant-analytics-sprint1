"""Minimal Telegram Bot API relay when Docker bridge cannot reach api.telegram.org."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = ("0.0.0.0", 18787)
TG_HOST, TG_IP = "api.telegram.org", "149.154.167.220"

_real_gai = socket.getaddrinfo


def _patched_gai(host, port, *a, **k):
    if host == TG_HOST:
        return _real_gai(TG_IP, port, *a, **k)
    return _real_gai(host, port, *a, **k)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: ANN002
        return

    def do_GET(self):  # noqa: N802
        self._proxy()

    def do_POST(self):  # noqa: N802
        self._proxy()

    def _proxy(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        req = urllib.request.Request(
            f"https://{TG_HOST}{self.path}", data=body, method=self.command
        )
        req.add_header("Host", TG_HOST)
        for k, v in self.headers.items():
            if k.lower() in {"host", "content-length", "connection"}:
                continue
            req.add_header(k, v)
        socket.getaddrinfo = _patched_gai
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = resp.read()
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() == "transfer-encoding":
                        continue
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            msg = json.dumps({"ok": False, "error_code": 502, "description": str(exc)}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(msg)
        finally:
            socket.getaddrinfo = _real_gai


if __name__ == "__main__":
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
