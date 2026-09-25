"""The ledger: one append-only JSONL file. It is the *only* source of truth.

Everything else — the decision queue, receipts, history, traces, calibration —
is a projection folded from this file. One writer lock (flock), one fsync per
batch, idempotency by event id, and cross-process catch-up by byte offset.
"""
from __future__ import annotations

import fcntl
import json
import os
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class Event:
    seq: int
    id: str
    ts: str
    type: str
    actor: str
    data: dict[str, Any]

    def line(self) -> bytes:
        body = {"seq": self.seq, "id": self.id, "ts": self.ts, "type": self.type, "actor": self.actor, "data": self.data}
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"

    @classmethod
    def parse(cls, line: bytes) -> "Event":
        raw = json.loads(line)
        return cls(raw["seq"], raw["id"], raw["ts"], raw["type"], raw["actor"], raw["data"])

    def json(self) -> dict[str, Any]:
        return {"seq": self.seq, "id": self.id, "ts": self.ts, "type": self.type, "actor": self.actor, "data": self.data}


@dataclass(frozen=True, slots=True)
class Draft:
    type: str
    actor: str
    data: dict[str, Any]
    id: str | None = None
    ts: str | None = None


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        self.seq = 0
        self._offset = 0
        self._ids: dict[str, Event] = {}

    def get(self, event_id: str) -> Event | None:
        return self._ids.get(event_id)

    def tail(self) -> list[Event]:
        """Complete events appended since the last call, by any process."""
        with self.path.open("rb") as handle:
            handle.seek(self._offset)
            chunk = handle.read()
        end = chunk.rfind(b"\n") + 1
        events = [Event.parse(line) for line in chunk[:end].splitlines() if line.strip()]
        self._offset += end
        for event in events:
            self._ids[event.id] = event
            self.seq = event.seq
        return events

    @contextmanager
    def lock(self) -> Iterator[None]:
        with self.path.open("ab") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def make(self, draft: Draft) -> Event:
        """Stage an event (assign seq/id/ts). Caller holds lock() and has drained tail()."""
        self.seq += 1
        event = Event(self.seq, draft.id or secrets.token_hex(8), draft.ts or now_iso(), draft.type, draft.actor, draft.data)
        self._ids[event.id] = event
        return event

    def flush(self, events: list[Event]) -> None:
        """Persist staged events with a single fsync."""
        if os.path.getsize(self.path) > self._offset:
            # Bytes past the last newline are a torn write from a crashed writer.
            os.truncate(self.path, self._offset)
        payload = b"".join(event.line() for event in events)
        with self.path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        self._offset += len(payload)
