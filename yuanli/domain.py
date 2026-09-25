"""A domain app (健康 / 投研 / 创业 / 内容 …) is plain data plus pure functions.

    sources  fetch() -> emits   read the outside world (files, HTTP, git …)
    rules    rule(state, today) -> emits   turn facts into proposals
    metrics  what the domain page charts
    actions  executors run after a human approves an item whose `action` names them

The kernel owns the loop, the ledger, policy, search, calibration and the UI.
A new domain is one file of ~100 lines; it never touches the kernel.
"""
from __future__ import annotations

import csv
import io
import json
import os
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator

if TYPE_CHECKING:
    from .state import Item, State


@dataclass(frozen=True, slots=True)
class Emit:
    type: str
    data: dict[str, Any]
    id: str | None = None
    ts: str | None = None


def fact(key: str, value: Any, at: str | None = None, **extra: Any) -> Emit:
    return Emit("fact.observed", {"key": key, "value": value, "at": at, **extra}, f"f:{key}@{at}={value}")


def propose(item_id: str, title: str, **fields: Any) -> Emit:
    return Emit("item.proposed", {"id": item_id, "title": title, **fields}, f"p:{item_id}")


def candidate(canon_id: str, statement: str, **fields: Any) -> Emit:
    return Emit("canon.proposed", {"id": canon_id, "statement": statement, **fields}, f"c:{canon_id}")


Rule = Callable[["State", str], Iterable[Emit]]
Action = Callable[["Item"], str]


@dataclass(slots=True)
class Source:
    name: str
    fetch: Callable[[], Iterable[Emit]]
    every: int = 3600


@dataclass(frozen=True, slots=True)
class Metric:
    key: str
    label: str
    unit: str = ""
    good: str = "up"


@dataclass(slots=True)
class Domain:
    key: str
    title: str
    sources: list[Source] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    actions: dict[str, Action] = field(default_factory=dict)


# ------------------------------------------------------------------ helpers
def days_before(today: str, days: int) -> str:
    return (date.fromisoformat(today) - timedelta(days=days)).isoformat()


def days_after(today: str, days: int) -> str:
    return (date.fromisoformat(today) + timedelta(days=days)).isoformat()


def week(today: str) -> str:
    year, number, _ = date.fromisoformat(today).isocalendar()
    return f"{year}-W{number:02d}"


def values(points: list[tuple[str, Any]]) -> list[float]:
    return [float(value) for _, value in points if isinstance(value, (int, float))]


def mean(numbers: list[float]) -> float:
    return fmean(numbers) if numbers else 0.0


_COLUMNS = {"key": ("key", "metric"), "value": ("value", "v"), "at": ("at", "date", "day", "time")}


def read_table(path: Path) -> Iterator[dict[str, Any]]:
    """Rows from a .jsonl or .csv file, with common column aliases normalised."""
    if path.suffix == ".jsonl":
        rows: Iterable[dict[str, Any]] = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    else:
        rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")))
    for row in rows:
        normal = dict(row)
        for name, aliases in _COLUMNS.items():
            for alias in aliases:
                if normal.get(name) in (None, "") and normal.get(alias) not in (None, ""):
                    normal[name] = normal[alias]
        yield normal


def number(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return float(value) if any(ch in value for ch in ".eE") else int(value)
        except ValueError:
            return value
    return value


def inbox(domain: str, folder: Path, column: str = "value", family: str | None = None) -> Source:
    """Drop .jsonl/.csv files into a folder; each row becomes a fact.

    Rows need `key,value,at` (or `code,<column>,date` when `family` is set, which
    yields keys like `invest.nav:000001`). Unchanged files are skipped.
    """
    seen: dict[Path, float] = {}

    def fetch() -> Iterator[Emit]:
        folder.mkdir(parents=True, exist_ok=True)
        for path in sorted(folder.glob("*")):
            if path.suffix not in {".csv", ".jsonl"} or seen.get(path) == path.stat().st_mtime:
                continue
            for row in read_table(path):
                key = row.get("key") or (f"{family}:{row['code']}" if family and row.get("code") else None)
                value = row.get("value") if row.get("value") not in (None, "") else row.get(column)
                if not key or value in (None, ""):
                    continue
                key = key if key.startswith(f"{domain}.") else f"{domain}.{key}"
                extra = {name: row[name] for name in ("unit", "label", "scope") if row.get(name)}
                yield fact(key, number(value), str(row.get("at") or "")[:19] or None, **extra)
            seen[path] = path.stat().st_mtime

    return Source(f"{domain}.inbox", fetch, every=600)


def webhook(url: str) -> Action:
    """Executor that hands an approved item to n8n / Dify / Feishu / anything HTTP."""

    def run(item: "Item") -> str:
        body = json.dumps(item.json(), ensure_ascii=False).encode()
        request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return f"webhook {response.status}"

    return run


def folder(domain: str, env: str) -> Path:
    """Where a domain's drop-in files live: $<env>, else $YUANLI_HOME/inbox/<domain>."""
    configured = os.environ.get(env)
    home = Path(os.environ.get("YUANLI_HOME", "~/.yuanli")).expanduser()
    return Path(configured).expanduser() if configured else home / "inbox" / domain
