from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from yuanli.api import handle
from yuanli.policy import Actor, Forbidden, load_tokens
from yuanli.server import build
from yuanli.state import Conflict


def test_routes_cover_the_loop(kernel, me):
    status, created = handle(kernel, me, "POST", "/api/items", {}, {"domain": "invest", "title": "茅台三年跑赢沪深300", "forecast": 0.55, "due": "2029-09-24"})
    assert status == 201 and created["id"].startswith("invest:")
    item_id = created["id"]
    status, decided = handle(kernel, me, "POST", f"/api/items/{item_id}/decide", {}, {"verdict": "approve", "rev": 1})
    assert decided["status"] == "approved" and decided["rev"] == 2
    with pytest.raises(Conflict):
        handle(kernel, me, "POST", f"/api/items/{item_id}/settle", {}, {"outcome": 1, "rev": 1})
    status, settled = handle(kernel, me, "POST", f"/api/items/{item_id}/settle", {}, {"outcome": 1, "rev": 2})
    assert settled["brier"] == pytest.approx(0.2025)
    assert handle(kernel, me, "GET", "/api/calibration", {}, None)[1]["overall"]["n"] == 1
    assert handle(kernel, me, "GET", "/api/search", {"q": "茅台"}, None)[1][0]["id"] == item_id


def test_idempotency_key_makes_retries_safe(kernel, me):
    body = {"id": "t:1", "domain": "os", "title": "重试安全"}
    handle(kernel, me, "POST", "/api/items", {}, body, key="retry-1")
    handle(kernel, me, "POST", "/api/items", {}, body, key="retry-1")
    assert kernel.ledger.seq == 1


def test_batch_fact_ingest_and_series(kernel):
    ios = Actor("ios", role="agent")
    rows = [{"key": "health.hrv", "value": 40 + n, "at": f"2026-09-0{n + 1}"} for n in range(5)]
    assert handle(kernel, ios, "POST", "/api/facts", {}, rows)[1]["written"] == 5
    assert handle(kernel, ios, "POST", "/api/facts", {}, rows)[1]["written"] == 5  # idempotent: returns existing
    assert kernel.ledger.seq == 5
    points = handle(kernel, ios, "GET", "/api/facts/health.hrv", {}, None)[1]["points"]
    assert points[-1] == ("2026-09-05", 44)
    with pytest.raises(Forbidden):
        handle(kernel, ios, "GET", "/api/events", {}, None)


@pytest.fixture
def server(kernel):
    tokens = load_tokens("p-token:mingge:principal,v-token:guest:viewer:public")
    httpd = build(kernel, "127.0.0.1", 0, tokens)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(url, token=None, body=None):
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    request = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None, headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read() or b"null"), response.headers
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null"), error.headers


def test_http_auth_scope_and_errors(server):
    assert call(f"{server}/api/brief")[0] == 401
    status, _, headers = call(f"{server}/api/items", "p-token", {"id": "t:1", "domain": "health", "title": "私密体检"})
    assert status == 201 and "default-src 'self'" in headers["Content-Security-Policy"]
    assert call(f"{server}/api/items", "v-token", {"id": "t:2", "domain": "health", "title": "x"})[0] == 403
    assert call(f"{server}/api/brief", "v-token")[1]["decide"] == []
    assert call(f"{server}/api/items/t:1/decide", "p-token", {"verdict": "later"})[0] == 422
    assert call(f"{server}/api/items/t:1/decide", "p-token", {"verdict": "approve", "rev": 9})[0] == 409
    assert call(f"{server}/api/items/nope", "p-token")[0] == 404
    assert call(f"{server}/api/brief?token=p-token")[0] == 200
    with urllib.request.urlopen(f"{server}/", timeout=5) as page:
        assert "原力OS" in page.read().decode()


def test_refuses_public_bind_without_tokens(kernel):
    with pytest.raises(SystemExit):
        build(kernel, "0.0.0.0", 0, {})
