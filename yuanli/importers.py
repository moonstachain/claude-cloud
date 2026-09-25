"""One-shot import of yuanli-os-max history into the ledger.

`decision-queue.json` (6 statuses × 3 parallel lifecycle fields) and
`calibration/takes.json` (a separate 5-state take machine) both collapse into
the single item lifecycle. Event ids are deterministic, so re-running is a no-op.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain import Emit
from .kernel import Kernel
from .policy import Actor


def _ts(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00")) if "T" in text else datetime.fromisoformat(text[:10])
    parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _refs(item: dict[str, Any]) -> list[str]:
    raw = [item.get("source_ref"), *(item.get("evidence_refs") or []), *(item.get("evidence") or []), *(item.get("dq_refs") or [])]
    return list(dict.fromkeys(str(ref) for ref in raw if ref))


def queue_emits(document: dict[str, Any]) -> list[tuple[str, Emit]]:
    emits: list[tuple[str, Emit]] = []
    as_of = _ts(document.get("meta", {}).get("as_of"))
    for item in document["items"]:
        key, owner = item["id"], str(item.get("owner") or "mingge")
        decided = _ts(item.get("decided_at"))
        emits.append((owner, Emit("item.proposed", {
            "id": key, "domain": "os", "title": item.get("title") or key, "why": item.get("two_sentence", ""),
            "recommend": item.get("recommend", ""), "priority": item.get("priority", "P2"),
            "scope": item.get("scope") or "private", "evidence": _refs(item), "due": item.get("due_at"),
            "manual": item.get("gate") == "G2",
        }, f"osmax:{key}:proposed", decided or as_of)))
        status = item.get("status", "pending")
        note = str(item.get("decision_note") or "")
        if status in {"decided", "close_ready", "done"}:
            emits.append((owner, Emit("item.decided", {"id": key, "verdict": "approve", "note": note}, f"osmax:{key}:decided", decided)))
        elif status == "deferred":
            reason = "；".join(filter(None, [note, item.get("defer_reason"), item.get("resume_condition")]))
            emits.append((owner, Emit("item.decided", {"id": key, "verdict": "defer", "until": item.get("due_at"), "note": reason}, f"osmax:{key}:decided", decided)))
        elif status == "dropped":
            emits.append((owner, Emit("item.decided", {"id": key, "verdict": "reject", "note": note}, f"osmax:{key}:decided", decided)))
        if status == "close_ready":
            emits.append((owner, Emit("item.noted", {"id": key, "note": "已执行，待验收（自 os-max close_ready 导入）"}, f"osmax:{key}:executed", decided)))
        if status == "done":
            outcome = item.get("outcome")
            emits.append((owner, Emit("item.settled", {
                "id": key, "outcome": float(outcome) if isinstance(outcome, (int, float)) else None,
                "note": str(outcome) if outcome is not None and not isinstance(outcome, (int, float)) else note,
            }, f"osmax:{key}:settled", decided)))
    return emits


def take_emits(document: dict[str, Any]) -> list[tuple[str, Emit]]:
    emits: list[tuple[str, Emit]] = []
    for take in document.get("items", []):
        key, owner = take["take_id"], str(take.get("owner") or "mingge")
        history = take.get("history") or [{}]
        emits.append((owner, Emit("item.proposed", {
            "id": key, "domain": "os", "title": take["claim"], "due": take.get("due_date"), "evidence": _refs(take),
        }, f"osmax:{key}:proposed", _ts(history[0].get("at")))))
        if take.get("status") == "void":
            emits.append((owner, Emit("item.decided", {"id": key, "verdict": "reject", "note": "作废"}, f"osmax:{key}:decided", None)))
            continue
        if take.get("weight") is not None:
            emits.append((owner, Emit("item.decided", {"id": key, "verdict": "approve", "forecast": take["weight"]},
                                      f"osmax:{key}:decided", _ts(take.get("weight_decided_at")))))
        if take.get("outcome") is not None:
            emits.append((owner, Emit("item.settled", {"id": key, "outcome": float(take["outcome"])},
                                      f"osmax:{key}:settled", _ts(take.get("outcome_decided_at")))))
    return emits


def import_osmax(kernel: Kernel, repo: Path) -> dict[str, int]:
    emits: list[tuple[str, Emit]] = []
    queue = repo / "data" / "decision-queue.json"
    takes = repo / "data" / "calibration" / "takes.json"
    if queue.exists():
        emits += queue_emits(json.loads(queue.read_text(encoding="utf-8")))
    if takes.exists():
        emits += take_emits(json.loads(takes.read_text(encoding="utf-8")))
    before = kernel.ledger.seq
    for owner in dict.fromkeys(owner for owner, _ in emits):
        kernel.emit_many(Actor(owner), [emit for who, emit in emits if who == owner])
    return {"events": kernel.ledger.seq - before, "items": len(kernel.state.items)}
