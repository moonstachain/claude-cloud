"""原力OS kernel: one loop — observe → propose → decide → act → settle → learn.

Every domain app plugs into the same loop. Writes go through `emit`, which
authorises, validates against current state, appends to the ledger and folds
the result into memory under one lock. Reads are served from memory.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import wraps
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .domain import Domain, Emit, Source
from .ledger import Draft, Event, Ledger
from .policy import Actor, agent
from .search import Index
from .state import Conflict, Invalid, Item, NotFound, State

UI = Path(__file__).parent / "ui"


def _read(method: Any) -> Any:
    """Reads take the kernel lock too: microseconds, and no torn dicts mid-write."""

    @wraps(method)
    def locked(self: "Kernel", *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return locked


class Kernel:
    def __init__(self, home: Path | str | None = None, domains: Iterable[Domain] | None = None, tz: str | None = None):
        self.home = Path(home or os.environ.get("YUANLI_HOME", "~/.yuanli")).expanduser()
        self.ledger = Ledger(self.home / "ledger.jsonl")
        self.tz = ZoneInfo(tz or os.environ.get("YUANLI_TZ", "Asia/Shanghai"))
        if domains is None:
            from .domains import load

            domains = load()
        self.domains: dict[str, Domain] = {domain.key: domain for domain in domains}
        self.sources: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.changed = threading.Condition(self._lock)
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="yuanli")
        self._reset()

    def _reset(self) -> None:
        self.state, self.index = State(), Index()
        self._unindexed: dict[str, None] = {}
        self.ledger = Ledger(self.ledger.path)
        self.sync()

    # ------------------------------------------------------------------ write
    def today(self) -> str:
        return datetime.now(self.tz).date().isoformat()

    def sync(self) -> int:
        """Fold events written by other processes (CLI, cron, a second server)."""
        with self._lock:
            events = self.ledger.tail()
            for event in events:
                self._apply(event)
            if events:
                self.changed.notify_all()
            return len(events)

    def emit(self, actor: Actor, kind: str, data: dict[str, Any], event_id: str | None = None, ts: str | None = None) -> Event:
        return self.emit_many(actor, [Emit(kind, data, event_id)], ts=ts)[0]

    def emit_many(self, actor: Actor, emits: Iterable[Emit], ts: str | None = None, skip_invalid: bool = False) -> list[Event]:
        emits = list(emits)
        for emit in emits:
            actor.require(emit.type)
        written: list[Event] = []
        results: list[Event] = []
        with self._lock, self.ledger.lock():
            self.sync()
            today = self.today()
            try:
                for emit in emits:
                    existing = self.ledger.get(emit.id) if emit.id else None
                    if existing:
                        results.append(existing)
                        continue
                    try:
                        data = self.state.validate(emit.type, emit.data, today)
                        if "domain" in data and data["domain"] not in self.domains:
                            raise Invalid(f"unknown domain {data['domain']}")
                    except (Invalid, Conflict, NotFound):
                        if skip_invalid:
                            continue
                        raise
                    event = self.ledger.make(Draft(emit.type, actor.name, data, emit.id, emit.ts or ts))
                    self._apply(event)
                    written.append(event)
                    results.append(event)
            finally:
                if written:
                    try:
                        self.ledger.flush(written)
                    except OSError:
                        self._reset()
                        raise
                    self.changed.notify_all()
        for event in written:
            self._after(event)
        return results

    def _apply(self, event: Event) -> None:
        self.state.apply(event)
        kind, data = event.type, event.data
        if kind.startswith(("item.", "canon.")) or (kind == "fact.observed" and len(self.state.facts[data["key"]]) == 1):
            self._unindexed[f"{kind.split('.')[0]}:{data.get('id') or data.get('key')}"] = None

    def _reindex(self) -> None:
        """Tokenise each touched document once, when search first needs it."""
        for doc_id in self._unindexed:
            kind, _, key = doc_id.partition(":")
            if kind == "item" and (item := self.state.items.get(key)):
                self.index.put(doc_id, f"{item.id} {item.domain} {item.title} {item.why} {item.recommend} {item.note}")
            elif kind == "canon" and (canon := self.state.canon.get(key)):
                self.index.put(doc_id, f"{canon.id} {canon.domain} {canon.statement}")
            elif kind == "fact":
                self.index.put(doc_id, f"{key} {self.state.labels.get(key, '')}")
        self._unindexed.clear()

    def _after(self, event: Event) -> None:
        """An approved item whose domain registers its `action` gets executed."""
        if event.type != "item.decided" or event.data.get("verdict") != "approve":
            return
        item = self.state.items.get(event.data["id"])
        domain = self.domains.get(item.domain) if item else None
        run = domain.actions.get(item.action or "") if domain else None
        if run:
            self._pool.submit(self._execute, item, run)

    def _execute(self, item: Item, run: Any) -> None:
        try:
            note = f"已执行 {item.action}：{run(item)}"
        except Exception as exc:  # the executor's failure is data, not a crash
            note = f"执行 {item.action} 失败：{exc}"
        self.emit(agent(f"{item.domain}:{item.action}"), "item.noted", {"id": item.id, "note": note[:2000]})

    # ---------------------------------------------------------------- collect
    def collect(self, only: set[str] | None = None, due_only: bool = False) -> dict[str, Any]:
        """Run sources concurrently, then every domain's rules."""
        jobs = [
            (domain, source)
            for domain in self.domains.values()
            for source in domain.sources
            if (only is None or domain.key in only or source.name in only)
            and (not due_only or time.monotonic() - self.sources.get(source.name, {}).get("t", -1e9) >= source.every)
        ]
        written = 0
        futures = {self._pool.submit(_fetch, source): (domain, source) for domain, source in jobs}
        for future in as_completed(futures):
            domain, source = futures[future]
            emits, status = future.result()
            self.sources[source.name] = {"domain": domain.key, **status}
            if emits:
                before = self.ledger.seq
                self.emit_many(agent(f"{domain.key}:{source.name}"), (_default_domain(emit, domain.key) for emit in emits), skip_invalid=True)
                written += self.ledger.seq - before
        before = self.ledger.seq
        with self._lock:
            today = self.today()
            for domain in self.domains.values():
                for rule in domain.rules:
                    emits = [_default_domain(emit, domain.key) for emit in rule(self.state, today)]
                    self.emit_many(agent(f"{domain.key}:{rule.__name__}"), emits, skip_invalid=True)
        return {"sources": len(jobs), "facts": written, "proposals": self.ledger.seq - before}

    def run_forever(self, interval: int = 60) -> threading.Thread:
        def loop() -> None:
            while True:
                try:
                    self.collect(due_only=True)
                except Exception as exc:  # keep the loop alive; the status page shows the failure
                    self.sources["kernel.loop"] = {"domain": "os", "ok": False, "detail": str(exc)[:200], "at": _now()}
                time.sleep(interval)

        thread = threading.Thread(target=loop, name="yuanli-collect", daemon=True)
        thread.start()
        return thread

    # ------------------------------------------------------------------ read
    @_read
    def item(self, actor: Actor, item_id: str) -> dict[str, Any]:
        item = self.state.items.get(item_id)
        if item is None or not actor.sees(item.scope):
            raise NotFound(item_id)
        return self._card(item, self.today(), trail=True)

    @_read
    def items(self, actor: Actor, status: str | None = None, domain: str | None = None) -> list[dict[str, Any]]:
        today = self.today()
        chosen = [
            item for item in self.state.items.values()
            if actor.sees(item.scope) and (status is None or item.status == status) and (domain is None or item.domain == domain)
        ]
        chosen.sort(key=lambda item: item.updated, reverse=True)
        return [self._card(item, today) for item in chosen]

    @_read
    def lanes(self, actor: Actor, domain: str | None = None, limit: int = 60) -> dict[str, Any]:
        """Two lanes: what needs a call now, and what is approved but not yet settled.
        Cards beyond `limit` are counted, not serialised: a screen is for deciding, not scrolling."""
        today = self.today()
        decide: list[Item] = []
        doing: list[Item] = []
        for item in self.state.items.values():
            if not actor.sees(item.scope) or (domain and item.domain != domain):
                continue
            if self._awaits(item, today):
                decide.append(item)
            elif item.status == "approved":
                doing.append(item)
        decide.sort(key=lambda item: (item.priority, item.created))
        doing.sort(key=lambda item: (item.due or "9999", item.priority))
        return {
            "decide": [self._card(item, today) for item in decide[:limit]], "decide_total": len(decide),
            "doing": [self._card(item, today) for item in doing[:limit]], "doing_total": len(doing),
            "overdue_total": sum(bool(item.due) and item.due < today for item in doing),
        }

    @_read
    def brief(self, actor: Actor) -> dict[str, Any]:
        lanes = self.lanes(actor)
        decide, overdue = lanes["decide"], lanes["overdue_total"]
        down = [
            {"name": name, **status} for name, status in sorted(self.sources.items())
            if not status["ok"] and actor.audience == "private"
        ]
        p0 = sum(card["priority"] == 0 for card in decide)
        if p0:
            verdict = f"{p0} 个 P0 待你拍板，先处理它们。"
        elif decide:
            verdict = f"{lanes['decide_total']} 件事待你拍板，约 {lanes['decide_total']} 分钟。"
        elif overdue:
            verdict = f"{overdue} 件已批准的事逾期未结算，去看看结果。"
        elif down:
            verdict = f"{len(down)} 个数据源掉线，先恢复事实链。"
        else:
            verdict = "今天没有需要你拍板的事。"
        return {
            "date": self.today(),
            "seq": self.state.seq,
            "verdict": verdict,
            **lanes,
            "sources": {"total": len(self.sources), "down": down},
            "calibration": self.calibration(actor)["overall"],
            "domains": [self.domain_view(actor, key, lanes=False) for key in self.domains],
        }

    @_read
    def domain_view(self, actor: Actor, key: str, lanes: bool = True) -> dict[str, Any]:
        domain = self.domains.get(key)
        if domain is None:
            raise NotFound(key)
        today = self.today()
        tiles = []
        for metric in domain.metrics:
            keys = self.state.keys(metric.key) if metric.key.endswith(":") else [metric.key]
            for fact_key in keys[:12]:
                points = self.state.series(fact_key)
                if not points or not actor.sees(self.state.fact_scope.get(fact_key, "private")):
                    continue
                suffix = self.state.labels.get(fact_key) or fact_key.split(":", 1)[-1] if metric.key.endswith(":") else ""
                tiles.append({
                    "key": fact_key, "label": f"{metric.label} {suffix}".strip(), "unit": metric.unit, "good": metric.good,
                    "at": points[-1][0], "value": points[-1][1],
                    "spark": [[at[:10], value] for at, value in points[-30:] if isinstance(value, (int, float))],
                })
        view: dict[str, Any] = {
            "key": domain.key, "title": domain.title, "metrics": tiles,
            "open": sum(item.domain == key and self._awaits(item, today) and actor.sees(item.scope) for item in self.state.items.values()),
            "sources": [
                {"name": source.name, **self.sources.get(source.name, {"ok": None, "detail": "尚未采集"})}
                for source in domain.sources
            ] if actor.audience == "private" else [],
        }
        if lanes:
            view.update(self.lanes(actor, key))
        return view

    @_read
    def facts(self, actor: Actor, key: str) -> dict[str, Any]:
        if key not in self.state.facts or not actor.sees(self.state.fact_scope.get(key, "private")):
            raise NotFound(key)
        return {"key": key, "label": self.state.labels.get(key, key), "points": self.state.series(key)}

    @_read
    def calibration(self, actor: Actor) -> dict[str, Any]:
        """Brier score per domain and per forecaster. 0 is perfect; 0.25 is a coin flip."""
        settled = [item for item in self.state.items.values() if item.brier is not None and actor.sees(item.scope)]

        def summary(group: list[Item]) -> dict[str, Any]:
            return {"n": len(group), "brier": round(fmean(item.brier for item in group), 4) if group else None}

        groups: dict[str, list[Item]] = {}
        for item in settled:
            groups.setdefault(f"domain:{item.domain}", []).append(item)
            who = "machine" if ":" in (item.forecast_by or "") else "human"
            groups.setdefault(f"by:{who}", []).append(item)
        bins = []
        for low in range(10):
            members = [item for item in settled if low / 10 <= item.forecast < (low + 1) / 10 or (low == 9 and item.forecast == 1.0)]
            if members:
                bins.append({
                    "forecast": round(fmean(item.forecast for item in members), 2),
                    "observed": round(fmean(item.outcome for item in members), 2), "n": len(members),
                })
        return {"overall": summary(settled), "groups": {name: summary(group) for name, group in sorted(groups.items())}, "reliability": bins}

    @_read
    def canon(self, actor: Actor) -> list[dict[str, Any]]:
        order = {"candidate": 0, "canon": 1, "retired": 2, "rejected": 3}
        chosen = [canon for canon in self.state.canon.values() if actor.sees(canon.scope)]
        return [canon.json() for canon in sorted(chosen, key=lambda canon: (order[canon.status], canon.updated))]

    @_read
    def search(self, actor: Actor, query: str, limit: int = 12) -> list[dict[str, Any]]:
        self._reindex()
        hits: list[dict[str, Any]] = []
        for doc_id, score in self.index.search(query, limit * 4):
            kind, _, key = doc_id.partition(":")
            if kind == "item" and (item := self.state.items.get(key)) and actor.sees(item.scope):
                hits.append({"kind": "item", "id": key, "title": item.title, "domain": item.domain, "status": item.status, "text": item.why, "score": round(score, 2)})
            elif kind == "canon" and (canon := self.state.canon.get(key)) and actor.sees(canon.scope):
                hits.append({"kind": "canon", "id": key, "title": canon.statement, "domain": canon.domain, "status": canon.status, "text": "", "score": round(score, 2)})
            elif kind == "fact" and actor.sees(self.state.fact_scope.get(key, "private")):
                at, value = self.state.latest(key) or ("", "")
                hits.append({"kind": "fact", "id": key, "title": self.state.labels.get(key, key), "domain": key.split(".")[0], "status": "", "text": f"{value} @ {at}", "score": round(score, 2)})
            if len(hits) >= limit:
                break
        return hits

    def ask(self, actor: Actor, question: str) -> dict[str, Any]:
        from . import brain

        hits = self.search(actor, question, limit=8)
        return {"question": question, "answer": brain.answer(question, hits), "citations": hits}

    def events(self, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        """Raw ledger tail for audit and sync; principal only (enforced by the API)."""
        with self.ledger.path.open("rb") as handle:
            lines = [line for line in handle if line.strip()]
        return [json.loads(line) for line in lines[after : after + limit]]

    @_read
    def export(self, audience: str, out: Path) -> dict[str, Any]:
        """Static, action-free snapshot for one audience. Privacy is by construction:
        only records whose scope the audience may see are ever serialised."""
        viewer = Actor("export", "viewer", audience)
        out.mkdir(parents=True, exist_ok=True)
        for name in ("app.js", "app.css"):
            shutil.copyfile(UI / name, out / name)
        page = (UI / "index.html").read_text(encoding="utf-8")
        (out / "index.html").write_text(page.replace("<head>", '<head>\n  <meta name="yuanli-static" content="snapshot.json">', 1), encoding="utf-8")
        snapshot = {
            "static": True, "audience": audience, "brief": self.brief(viewer),
            "domains": {key: self.domain_view(viewer, key) for key in self.domains},
            "calibration": self.calibration(viewer), "canon": self.canon(viewer),
        }
        (out / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        return {"out": str(out), "audience": audience, "items": len(snapshot["brief"]["decide"]) + len(snapshot["brief"]["doing"])}

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _awaits(item: Item, today: str) -> bool:
        """Needs a human call now: open, or deferred and back on the table."""
        return item.status == "open" or (item.status == "deferred" and (item.until or "") <= today)

    def _card(self, item: Item, today: str, trail: bool = False) -> dict[str, Any]:
        card = item.json(trail=trail)
        card["overdue"] = item.status == "approved" and bool(item.due) and item.due < today
        card["suggest"] = self._suggest(item)
        return card

    def _suggest(self, item: Item) -> dict[str, Any] | None:
        """If the item names a measurable fact, pre-compute the outcome for one-key settling."""
        measure = item.measure or {}
        latest = self.state.latest(measure.get("key", "")) if measure else None
        if not latest or "target" not in measure or not isinstance(latest[1], (int, float)):
            return None
        at, value = latest
        hit = value >= measure["target"] if measure.get("good", "up") == "up" else value <= measure["target"]
        return {"outcome": 1.0 if hit else 0.0, "value": value, "at": at, "target": measure["target"], "key": measure["key"]}


def _fetch(source: Source) -> tuple[list[Emit], dict[str, Any]]:
    started = time.monotonic()
    try:
        emits = list(source.fetch())
        status = {"ok": True, "detail": f"{len(emits)} 条"}
    except Exception as exc:  # a broken source degrades to a visible status, never a crash
        emits, status = [], {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:300]}
    return emits, {**status, "at": _now(), "ms": round((time.monotonic() - started) * 1000), "t": time.monotonic()}


def _default_domain(emit: Emit, domain: str) -> Emit:
    if emit.type in {"item.proposed", "canon.proposed"} and "domain" not in emit.data:
        return Emit(emit.type, {**emit.data, "domain": domain}, emit.id, emit.ts)
    return emit


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
