"""The fold: ledger events -> in-memory state. O(1) per event, O(1) lookups.

The whole domain vocabulary is seven event types:

    fact.observed    agent|principal   a measured value (point-in-time: event ts = known-at)
    item.proposed    agent|principal   something that needs a human call
    item.decided     principal         approve | reject | defer
    item.noted       agent|principal   progress, execution result, extra evidence
    item.settled     principal         the outcome; closes the item, feeds calibration
    canon.proposed   agent|principal   a candidate principle learned from reality
    canon.ruled      principal         admit | reject | retire

`validate()` is strict and runs once, at write time. `apply()` trusts the
ledger and is tolerant, so replaying history never fails.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from .ledger import Event

SCOPES = ("public", "team", "private")
VERDICTS = {"approve": "approved", "reject": "rejected", "defer": "deferred"}
CANON_VERDICTS = {"admit": "canon", "reject": "rejected", "retire": "retired"}
CLOSED = frozenset({"rejected", "done"})
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Invalid(ValueError):
    pass


class Conflict(RuntimeError):
    pass


class NotFound(KeyError):
    pass


@dataclass(slots=True)
class Item:
    id: str
    domain: str
    title: str
    why: str = ""
    recommend: str = ""
    priority: int = 2
    scope: str = "private"
    evidence: list[str] = field(default_factory=list)
    due: str | None = None
    action: str | None = None
    measure: dict[str, Any] | None = None
    manual: bool = False
    forecast: float | None = None
    forecast_by: str | None = None
    status: str = "open"
    until: str | None = None
    note: str = ""
    outcome: float | None = None
    created: str = ""
    updated: str = ""
    rev: int = 0
    trail: list[Event] = field(default_factory=list)

    @property
    def brier(self) -> float | None:
        if self.forecast is None or self.outcome is None:
            return None
        return round((self.forecast - self.outcome) ** 2, 4)

    def json(self, trail: bool = False) -> dict[str, Any]:
        body = {name: getattr(self, name) for name in self.__slots__ if name != "trail"}
        body["brier"] = self.brier
        if trail:
            body["trail"] = [event.json() for event in self.trail]
        return body


@dataclass(slots=True)
class Canon:
    id: str
    statement: str
    domain: str
    evidence: list[str] = field(default_factory=list)
    scope: str = "private"
    status: str = "candidate"
    note: str = ""
    created: str = ""
    updated: str = ""

    def json(self) -> dict[str, Any]:
        return asdict(self)


class State:
    def __init__(self) -> None:
        self.seq = 0
        self.items: dict[str, Item] = {}
        self.canon: dict[str, Canon] = {}
        self.facts: dict[str, dict[str, Any]] = {}
        self.fact_scope: dict[str, str] = {}
        self.labels: dict[str, str] = {}
        self._sorted: dict[str, list[tuple[str, Any]]] = {}

    # ---------------------------------------------------------------- queries
    def series(self, key: str) -> list[tuple[str, Any]]:
        cached = self._sorted.get(key)
        if cached is None:
            cached = sorted(self.facts.get(key, {}).items())
            self._sorted[key] = cached
        return cached

    def latest(self, key: str) -> tuple[str, Any] | None:
        points = self.series(key)
        return points[-1] if points else None

    def keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.facts if key.startswith(prefix))

    # ------------------------------------------------------------- validation
    def validate(self, kind: str, data: dict[str, Any], today: str) -> dict[str, Any]:
        """Return the normalised payload that will be written, or raise."""
        check = _VALIDATORS.get(kind)
        if check is None:
            raise Invalid(f"unknown event type: {kind}")
        return check(self, dict(data), today)

    def _item(self, data: dict[str, Any]) -> Item:
        item = self.items.get(_text(data, "id", required=True))
        if item is None:
            raise NotFound(data["id"])
        if item.status in CLOSED:
            raise Conflict(f"{item.id} is already {item.status}")
        if data.get("rev") is not None and int(data["rev"]) != item.rev:
            raise Conflict(f"{item.id} changed (rev {item.rev}, you saw {data['rev']})")
        return item

    def _v_fact(self, data: dict[str, Any], today: str) -> dict[str, Any]:
        key = _text(data, "key", required=True)
        if "." not in key:
            raise Invalid("fact key must start with its domain, e.g. health.hrv")
        value = data.get("value")
        if isinstance(value, bool):
            data["value"] = int(value)
        elif not isinstance(value, (int, float, str)):
            raise Invalid("fact value must be a number or text")
        data["scope"] = _scope(data)
        return {k: v for k, v in data.items() if v is not None}

    def _v_proposed(self, data: dict[str, Any], today: str) -> dict[str, Any]:
        item_id = _text(data, "id", required=True)
        _text(data, "title", required=True, limit=300)
        _text(data, "domain", required=True)
        existing = self.items.get(item_id)
        if existing and existing.status in CLOSED:
            raise Conflict(f"{item_id} is already {existing.status}")
        data["priority"] = _priority(data.get("priority", 2))
        data["scope"] = _scope(data)
        data["evidence"] = [str(ref) for ref in data.get("evidence") or []]
        _day(data, "due")
        _probability(data, "forecast")
        measure = data.get("measure")
        if measure is not None:
            if not isinstance(measure, dict) or not _text(measure, "key"):
                raise Invalid("measure needs a fact key")
            if not isinstance(measure.get("target", 0), (int, float)) or measure.get("good", "up") not in {"up", "down"}:
                raise Invalid("measure target must be a number and good must be up or down")
        return {k: v for k, v in data.items() if v not in (None, "", [])}

    def _v_decided(self, data: dict[str, Any], today: str) -> dict[str, Any]:
        self._item(data)
        verdict = data.get("verdict")
        if verdict not in VERDICTS:
            raise Invalid("verdict must be approve, reject or defer")
        _probability(data, "forecast")
        if verdict == "defer":
            data["until"] = _day(data, "until") or (date.fromisoformat(today) + timedelta(days=7)).isoformat()
        return {k: v for k, v in data.items() if v not in (None, "")}

    def _v_settled(self, data: dict[str, Any], today: str) -> dict[str, Any]:
        self._item(data)
        if isinstance(data.get("outcome"), bool):
            data["outcome"] = float(data["outcome"])
        _probability(data, "outcome")
        return {k: v for k, v in data.items() if v not in (None, "")} | {"outcome": data.get("outcome")}

    def _v_noted(self, data: dict[str, Any], today: str) -> dict[str, Any]:
        if _text(data, "id", required=True) not in self.items:
            raise NotFound(data["id"])
        if not (data.get("note") or data.get("evidence")):
            raise Invalid("a note needs text or evidence")
        return {k: v for k, v in data.items() if v not in (None, "", [])}

    def _v_canon_proposed(self, data: dict[str, Any], today: str) -> dict[str, Any]:
        canon_id = _text(data, "id", required=True)
        _text(data, "statement", required=True, limit=1000)
        _text(data, "domain", required=True)
        existing = self.canon.get(canon_id)
        if existing and existing.status != "candidate":
            raise Conflict(f"{canon_id} is already {existing.status}")
        data["scope"] = _scope(data)
        return {k: v for k, v in data.items() if v not in (None, "", [])}

    def _v_canon_ruled(self, data: dict[str, Any], today: str) -> dict[str, Any]:
        canon = self.canon.get(_text(data, "id", required=True))
        if canon is None:
            raise NotFound(data["id"])
        verdict = data.get("verdict")
        allowed = {"candidate": {"admit", "reject"}, "canon": {"retire"}}.get(canon.status, set())
        if verdict not in allowed:
            raise Conflict(f"cannot {verdict} a {canon.status} principle")
        return {k: v for k, v in data.items() if v not in (None, "")}

    # ------------------------------------------------------------------ fold
    def apply(self, event: Event) -> None:
        self.seq = event.seq
        handler = _APPLIERS.get(event.type)
        if handler:
            handler(self, event, event.data)

    def _a_fact(self, event: Event, data: dict[str, Any]) -> None:
        key = data["key"]
        self.facts.setdefault(key, {})[data.get("at") or event.ts] = data["value"]
        self.fact_scope[key] = data.get("scope", "private")
        if data.get("label"):
            self.labels[key] = data["label"]
        self._sorted.pop(key, None)

    def _a_proposed(self, event: Event, data: dict[str, Any]) -> None:
        item = self.items.get(data["id"])
        if item is None:
            item = self.items[data["id"]] = Item(id=data["id"], domain=data["domain"], title=data["title"], created=event.ts)
        for name in ("domain", "title", "why", "recommend", "priority", "scope", "evidence", "due", "action", "measure", "manual"):
            if name in data:
                setattr(item, name, data[name])
        if "forecast" in data:
            item.forecast, item.forecast_by = data["forecast"], event.actor
        self._touch(item, event)

    def _a_decided(self, event: Event, data: dict[str, Any]) -> None:
        item = self.items.get(data["id"])
        if item is None:
            return
        item.status = VERDICTS[data["verdict"]]
        item.until = data.get("until")
        item.note = data.get("note", item.note)
        if "forecast" in data:
            item.forecast, item.forecast_by = data["forecast"], event.actor
        self._touch(item, event)

    def _a_noted(self, event: Event, data: dict[str, Any]) -> None:
        item = self.items.get(data["id"])
        if item is None:
            return
        item.evidence = list(dict.fromkeys([*item.evidence, *data.get("evidence", [])]))
        self._touch(item, event)

    def _a_settled(self, event: Event, data: dict[str, Any]) -> None:
        item = self.items.get(data["id"])
        if item is None:
            return
        item.status, item.outcome = "done", data.get("outcome")
        item.note = data.get("note", item.note)
        item.evidence = list(dict.fromkeys([*item.evidence, *data.get("evidence", [])]))
        self._touch(item, event)

    def _a_canon_proposed(self, event: Event, data: dict[str, Any]) -> None:
        canon = self.canon.get(data["id"])
        if canon is None:
            canon = self.canon[data["id"]] = Canon(id=data["id"], statement=data["statement"], domain=data["domain"], created=event.ts)
        canon.statement, canon.domain = data["statement"], data["domain"]
        canon.evidence = list(dict.fromkeys([*canon.evidence, *data.get("evidence", [])]))
        canon.scope, canon.updated = data.get("scope", canon.scope), event.ts

    def _a_canon_ruled(self, event: Event, data: dict[str, Any]) -> None:
        canon = self.canon.get(data["id"])
        if canon is not None:
            canon.status, canon.note, canon.updated = CANON_VERDICTS[data["verdict"]], data.get("note", ""), event.ts

    @staticmethod
    def _touch(item: Item, event: Event) -> None:
        item.rev += 1
        item.updated = event.ts
        item.trail.append(event)


_VALIDATORS = {
    "fact.observed": State._v_fact,
    "item.proposed": State._v_proposed,
    "item.decided": State._v_decided,
    "item.noted": State._v_noted,
    "item.settled": State._v_settled,
    "canon.proposed": State._v_canon_proposed,
    "canon.ruled": State._v_canon_ruled,
}
_APPLIERS = {
    "fact.observed": State._a_fact,
    "item.proposed": State._a_proposed,
    "item.decided": State._a_decided,
    "item.noted": State._a_noted,
    "item.settled": State._a_settled,
    "canon.proposed": State._a_canon_proposed,
    "canon.ruled": State._a_canon_ruled,
}


def _text(data: dict[str, Any], name: str, required: bool = False, limit: int = 4000) -> str:
    value = data.get(name)
    if value is None or value == "":
        if required:
            raise Invalid(f"{name} is required")
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise Invalid(f"{name} must be text of at most {limit} characters")
    return value


def _scope(data: dict[str, Any]) -> str:
    scope = data.get("scope") or "private"
    if scope not in SCOPES:
        raise Invalid(f"scope must be one of {', '.join(SCOPES)}")
    return scope


def _priority(value: Any) -> int:
    if isinstance(value, str) and re.fullmatch(r"[Pp][0-3]", value):
        return int(value[1])
    if isinstance(value, int) and 0 <= value <= 3:
        return value
    raise Invalid("priority must be 0-3 or P0-P3")


def _day(data: dict[str, Any], name: str) -> str | None:
    value = data.get(name)
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _DAY.match(value[:10]):
        raise Invalid(f"{name} must be a date like 2026-10-01")
    data[name] = value[:10]
    return data[name]


def _probability(data: dict[str, Any], name: str) -> None:
    value = data.get(name)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise Invalid(f"{name} must be a probability between 0 and 1")
    data[name] = float(value)
