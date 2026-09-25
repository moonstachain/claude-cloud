"""Stdlib HTTP server: static UI, JSON API, and a server-sent-event stream that
pushes the ledger sequence number the moment anything changes."""
from __future__ import annotations

import ipaddress
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from .api import handle
from .kernel import UI, Kernel
from .policy import Actor, Forbidden, authenticate, load_tokens, principal
from .state import Conflict, Invalid, NotFound

STATIC = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/app.css": ("app.css", "text/css")}
HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
ERRORS = {NotFound: 404, Forbidden: 403, Conflict: 409, Invalid: 422}


def build(kernel: Kernel, host: str = "127.0.0.1", port: int = 8420, tokens: dict[str, Actor] | None = None) -> ThreadingHTTPServer:
    tokens = load_tokens() if tokens is None else tokens
    if not tokens and not _loopback(host):
        raise SystemExit("refusing to listen beyond localhost without YUANLI_TOKENS")
    local = None if tokens else principal()

    class Handler(BaseHTTPRequestHandler):
        server_version = "yuanli"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def _dispatch(self, method: str) -> None:
            url = urlsplit(self.path)
            path, query = unquote(url.path), dict(parse_qsl(url.query))
            if method == "GET" and path in STATIC:
                name, kind = STATIC[path]
                return self._send(200, (UI / name).read_bytes(), f"{kind}; charset=utf-8")
            if path == "/healthz":
                return self._json(200, {"ok": True, "seq": kernel.state.seq})
            supplied = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip() or query.pop("token", None)
            actor = local or authenticate(tokens, supplied)
            if actor is None:
                return self._json(401, {"error": "token required"})
            if path == "/api/stream":
                return self._stream(actor)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 1_000_000:
                    return self._json(413, {"error": "body too large"})
                body = json.loads(self.rfile.read(length)) if length else None
                status, payload = handle(kernel, actor, method, path, query, body, self.headers.get("Idempotency-Key"))
            except json.JSONDecodeError:
                status, payload = 400, {"error": "invalid JSON"}
            except (NotFound, Forbidden, Conflict, Invalid) as exc:
                status, payload = ERRORS[type(exc)], {"error": str(exc).strip("'")}
            except (KeyError, ValueError, TypeError) as exc:
                status, payload = 400, {"error": f"bad request: {exc}"}
            self._json(status, payload)

        def _stream(self, actor: Actor) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen = -1
            try:
                while True:
                    kernel.sync()
                    with kernel.changed:
                        if kernel.state.seq == seen:
                            kernel.changed.wait(timeout=5)
                        current = kernel.state.seq
                    if current != seen:
                        seen = current
                        self.wfile.write(f"event: seq\ndata: {seen}\n\n".encode())
                    else:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def serve(kernel: Kernel, host: str = "127.0.0.1", port: int = 8420, collect_every: int = 60) -> None:
    httpd = build(kernel, host, port)
    if collect_every:
        kernel.run_forever(collect_every)
    print(f"原力OS on http://{host}:{port}  ledger={kernel.ledger.path}  seq={kernel.state.seq}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def _loopback(host: str) -> bool:
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
