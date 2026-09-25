"""原力创业 — 每个项目要么在推进，要么被砍掉，要么被明确地推迟。

Reads the existing `project_evidence_envelope_v1` files (`<dir>/<project>/envelope.json`)
as-is: progress and risk become facts, `decisions_needed` become items.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Iterator

from ..domain import Domain, Emit, Metric, Source, days_after, days_before, fact, folder, inbox, propose, week
from ..state import State

RISK = {"green": 0, "amber": 1, "red": 2}


def envelopes(root: Path) -> Source:
    def fetch() -> Iterator[Emit]:
        for path in sorted(root.glob("*/envelope.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            project = document.get("project") or {}
            state = document.get("state") or {}
            pid = project.get("project_id") or path.parent.name
            title = project.get("title") or pid
            at = str(document.get("updated_at") or "")[:10] or None
            progress = (state.get("progress") or {}).get("weighted_execution_pct")
            if progress is not None:
                yield fact(f"venture.progress:{pid}", progress, at, label=title, unit="%")
            risk = RISK.get(str(project.get("risk_level")))
            if risk is not None:
                yield fact(f"venture.risk:{pid}", risk, at, label=title)
            for need in state.get("decisions_needed") or []:
                text = str(need.get("decision") if isinstance(need, dict) else need)
                digest = hashlib.sha1(text.encode()).hexdigest()[:8]
                yield propose(
                    f"venture:{pid}:{digest}", f"{title}：{text}", priority=0 if risk == 2 else 1,
                    why=str(project.get("next_action") or ""), evidence=[f"{pid}/envelope.json"],
                )

    return Source("venture.projects", fetch, every=1800)


def stalled(state: State, today: str) -> Iterator[Emit]:
    days = int(os.environ.get("YUANLI_VENTURE_STALE_DAYS", "14"))
    cutoff = days_before(today, days)
    for key in state.keys("venture.progress:"):
        at, progress = state.latest(key)
        if at[:10] >= cutoff:
            continue
        pid = key.split(":", 1)[1]
        idle = (date.fromisoformat(today) - date.fromisoformat(at[:10])).days
        yield propose(
            f"venture:stalled:{pid}:{week(today)}", f"{state.labels.get(key, pid)} 已 {idle} 天没有进展：推进、砍掉，还是推迟？",
            priority=1, due=days_after(today, 7), evidence=[key],
            why=f"最近一次进度 {progress}%，记录于 {at[:10]}。",
            recommend="写下下一步和日期；三个月内不会做的，就砍掉并写下原因。",
        )


def red_risk(state: State, today: str) -> Iterator[Emit]:
    for key in state.keys("venture.risk:"):
        at, risk = state.latest(key)
        if risk == RISK["red"]:
            pid = key.split(":", 1)[1]
            yield propose(
                f"venture:red:{pid}:{week(today)}", f"{state.labels.get(key, pid)} 风险转红",
                priority=0, evidence=[key], due=days_after(today, 3),
                why=f"项目在 {at[:10]} 标记为红色风险。",
                recommend="48 小时内和负责人对一次：止损、换打法，还是追加资源。",
            )


def domain() -> Domain:
    home = folder("venture", "YUANLI_VENTURE_DIR")
    return Domain(
        key="venture", title="原力创业",
        sources=[inbox("venture", home), envelopes(Path(os.environ.get("YUANLI_VENTURE_PROJECTS", home)).expanduser())],
        rules=[stalled, red_risk],
        metrics=[Metric("venture.progress:", "进度", "%")],
    )
