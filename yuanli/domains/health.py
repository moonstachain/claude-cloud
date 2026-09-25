"""原力健康 — 让身体的每一次反馈，都成为下一次更好的决定。

Facts come from Apple Health's export.xml and from any .csv/.jsonl dropped in
the health inbox (the iOS app / ingest server can write there). Rules turn a
falling HRV or a sleep debt into one concrete, settleable decision.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ..domain import Domain, Emit, Metric, Source, days_after, fact, folder, inbox, mean, propose, values, week
from ..state import State

QUANTITIES = {
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": ("hrv", "mean"),
    "HKQuantityTypeIdentifierRestingHeartRate": ("rhr", "mean"),
    "HKQuantityTypeIdentifierStepCount": ("steps", "sum"),
}
SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"


def apple_health(path: Path) -> Source:
    """Stream-parse export.xml (can be GBs) into daily aggregates."""
    parsed: dict[str, float] = {}

    def fetch() -> Iterator[Emit]:
        mtime = path.stat().st_mtime
        if parsed.get("mtime") == mtime:
            return
        totals: dict[tuple[str, str], list[float]] = defaultdict(list)
        sleep: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
        for _, element in ET.iterparse(path, events=("end",)):
            if element.tag == "Record":
                kind = element.get("type", "")
                if kind in QUANTITIES:
                    totals[(QUANTITIES[kind][0], element.get("startDate", "")[:10])].append(float(element.get("value") or 0))
                elif kind == SLEEP and element.get("value", "").startswith("HKCategoryValueSleepAnalysisAsleep"):
                    start, end = (datetime.strptime(element.get(name, ""), "%Y-%m-%d %H:%M:%S %z") for name in ("startDate", "endDate"))
                    sleep[element.get("endDate", "")[:10]].append((start, end))
            element.clear()
        modes = dict(QUANTITIES.values())
        for (name, day), numbers in sorted(totals.items()):
            yield fact(f"health.{name}", round(mean(numbers) if modes[name] == "mean" else sum(numbers), 1), day)
        for day, spans in sorted(sleep.items()):
            yield fact("health.sleep_h", round(_union_hours(spans), 2), day)
        parsed["mtime"] = mtime

    return Source("health.apple", fetch, every=3600)


def _union_hours(spans: list[tuple[datetime, datetime]]) -> float:
    """Watch and iPhone both log sleep; count overlapping intervals once."""
    total, current_start, current_end = 0.0, None, None
    for start, end in sorted(spans):
        if current_end is None or start > current_end:
            if current_end is not None:
                total += (current_end - current_start).total_seconds()
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_end is not None:
        total += (current_end - current_start).total_seconds()
    return total / 3600


def recovery(state: State, today: str) -> Iterator[Emit]:
    hrv = values(state.series("health.hrv")[-28:])
    if len(hrv) < 14:
        return
    base, recent = mean(hrv[:-3]), mean(hrv[-3:])
    if recent >= 0.85 * base:
        return
    yield propose(
        f"health:recovery:{week(today)}", f"HRV 比基线低 {1 - recent / base:.0%}：本周降负荷",
        priority=1, forecast=0.6, due=days_after(today, 7), evidence=["health.hrv"],
        why=f"近 3 天 HRV 均值 {recent:.0f} ms，28 天基线 {base:.0f} ms。",
        recommend="暂停高强度训练，睡够 8 小时；一周后看 HRV 是否回到基线的 95%。",
        measure={"key": "health.hrv", "target": round(0.95 * base, 1), "good": "up"},
    )


def sleep_debt(state: State, today: str) -> Iterator[Emit]:
    nights = values(state.series("health.sleep_h")[-3:])
    if len(nights) < 3 or mean(nights) >= 6.5:
        return
    yield propose(
        f"health:sleep:{week(today)}", f"连续 3 晚平均只睡 {mean(nights):.1f} 小时",
        priority=2, forecast=0.5, due=days_after(today, 7), evidence=["health.sleep_h"],
        why="睡眠不足会先拖垮 HRV，再拖垮判断质量。",
        recommend="本周 23:00 前上床，取消 21:00 后的会。",
        measure={"key": "health.sleep_h", "target": 7, "good": "up"},
    )


def domain() -> Domain:
    home = folder("health", "YUANLI_HEALTH_DIR")
    sources = [inbox("health", home)]
    export = Path(os.environ.get("YUANLI_APPLE_HEALTH_EXPORT", home / "export.xml")).expanduser()
    if export.exists():
        sources.append(apple_health(export))
    return Domain(
        key="health", title="原力健康", sources=sources, rules=[recovery, sleep_debt],
        metrics=[
            Metric("health.hrv", "HRV", "ms"), Metric("health.rhr", "静息心率", "bpm", good="down"),
            Metric("health.sleep_h", "睡眠", "h"), Metric("health.steps", "步数", "步"),
        ],
    )
