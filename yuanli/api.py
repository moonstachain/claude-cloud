"""HTTP routes as one pure function: (kernel, actor, method, path, query, body) -> (status, payload).

No framework, so it is trivially testable and can be mounted under anything.
"""
from __future__ import annotations

import re
import secrets
from typing import Any, Callable

from .domain import fact
from .kernel import Kernel
from .policy import Actor, Forbidden
from .state import NotFound

Handler = Callable[..., tuple[int, Any]]
ROUTES: list[tuple[str, re.Pattern[str], Handler]] = []


def route(method: str, pattern: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        ROUTES.append((method, re.compile(f"^{pattern}$"), handler))
        return handler

    return register


def handle(kernel: Kernel, actor: Actor, method: str, path: str, query: dict[str, str], body: Any, key: str | None = None) -> tuple[int, Any]:
    for verb, pattern, handler in ROUTES:
        match = pattern.match(path)
        if verb == method and match:
            return handler(kernel, actor, query, body if body is not None else {}, key, *match.groups())
    raise NotFound(path)


def _principal(actor: Actor) -> None:
    if actor.role != "principal":
        raise Forbidden("principal only")


# ----------------------------------------------------------------------- reads
@route("GET", "/api/brief")
def brief(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None) -> tuple[int, Any]:
    return 200, kernel.brief(actor)


@route("GET", "/api/items")
def items(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None) -> tuple[int, Any]:
    return 200, kernel.items(actor, status=query.get("status"), domain=query.get("domain"))


@route("GET", "/api/items/(.+)")
def item(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None, item_id: str) -> tuple[int, Any]:
    return 200, kernel.item(actor, item_id)


@route("GET", "/api/domains/([\\w-]+)")
def domain_view(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None, domain: str) -> tuple[int, Any]:
    return 200, kernel.domain_view(actor, domain)


@route("GET", "/api/facts/(.+)")
def facts(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None, fact_key: str) -> tuple[int, Any]:
    return 200, kernel.facts(actor, fact_key)


@route("GET", "/api/calibration")
def calibration(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None) -> tuple[int, Any]:
    return 200, kernel.calibration(actor)


@route("GET", "/api/canon")
def canon(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None) -> tuple[int, Any]:
    return 200, kernel.canon(actor)


@route("GET", "/api/search")
def search(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None) -> tuple[int, Any]:
    return 200, kernel.search(actor, query.get("q", ""))


@route("GET", "/api/ask")
def ask(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None) -> tuple[int, Any]:
    return 200, kernel.ask(actor, query.get("q", ""))


@route("GET", "/api/events")
def events(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None) -> tuple[int, Any]:
    _principal(actor)
    return 200, kernel.events(after=int(query.get("after", 0)), limit=min(int(query.get("limit", 200)), 5000))


# ---------------------------------------------------------------------- writes
@route("POST", "/api/items")
def propose(kernel: Kernel, actor: Actor, query: dict, body: dict, key: str | None) -> tuple[int, Any]:
    data = {**body, "id": body.get("id") or f"{body.get('domain', 'os')}:{secrets.token_hex(4)}"}
    kernel.emit(actor, "item.proposed", data, key)
    return 201, kernel.item(actor, data["id"])


def _item_event(kind: str) -> Handler:
    def write(kernel: Kernel, actor: Actor, query: dict, body: dict, key: str | None, item_id: str) -> tuple[int, Any]:
        kernel.emit(actor, kind, {**body, "id": item_id}, key)
        return 200, kernel.item(actor, item_id)

    return write


route("POST", "/api/items/(.+)/decide")(_item_event("item.decided"))
route("POST", "/api/items/(.+)/settle")(_item_event("item.settled"))
route("POST", "/api/items/(.+)/note")(_item_event("item.noted"))


@route("POST", "/api/facts")
def observe(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None) -> tuple[int, Any]:
    rows = body if isinstance(body, list) else [body]
    written = kernel.emit_many(actor, [fact(row["key"], row.get("value"), row.get("at"), **{k: v for k, v in row.items() if k not in {"key", "value", "at"}}) for row in rows])
    return 201, {"written": len(written), "seq": kernel.state.seq}


@route("POST", "/api/canon")
def canon_propose(kernel: Kernel, actor: Actor, query: dict, body: dict, key: str | None) -> tuple[int, Any]:
    data = {**body, "id": body.get("id") or f"{body.get('domain', 'os')}:canon:{secrets.token_hex(4)}"}
    kernel.emit(actor, "canon.proposed", data, key)
    return 201, kernel.state.canon[data["id"]].json()


@route("POST", "/api/canon/(.+)/rule")
def canon_rule(kernel: Kernel, actor: Actor, query: dict, body: dict, key: str | None, canon_id: str) -> tuple[int, Any]:
    kernel.emit(actor, "canon.ruled", {**body, "id": canon_id}, key)
    return 200, kernel.state.canon[canon_id].json()


@route("POST", "/api/collect")
def collect(kernel: Kernel, actor: Actor, query: dict, body: Any, key: str | None) -> tuple[int, Any]:
    _principal(actor)
    return 200, kernel.collect()
