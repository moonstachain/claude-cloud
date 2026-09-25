"""原力内容 — 每篇内容都是一次下注：数据回来就结算，赢的母题进入正典。

Metric rows (`key=reads:<article>,value,at,label=<title>`) land in the content
inbox. Approved items with `action: publish` are handed to
$YUANLI_CONTENT_PUBLISH_HOOK (a Dify / n8n / Feishu workflow) when it is set.
"""
from __future__ import annotations

import os
from statistics import median
from typing import Iterator

from ..domain import Domain, Emit, Metric, candidate, days_after, days_before, folder, inbox, propose, webhook
from ..state import State


def winners(state: State, today: str) -> Iterator[Emit]:
    reads_by_day7: dict[str, float] = {}
    for key in state.keys("content.reads:"):
        points = state.series(key)
        published = points[0][0][:10]
        if published > days_before(today, 7):
            continue
        horizon = days_after(published, 7)
        window = [value for at, value in points if at[:10] <= horizon and isinstance(value, (int, float))]
        if window:
            reads_by_day7[key] = max(window)
    if len(reads_by_day7) < 5:
        return
    typical = median(reads_by_day7.values()) or 1
    for key, reads in reads_by_day7.items():
        ratio = reads / typical
        if ratio < 2:
            continue
        article = key.split(":", 1)[1]
        title = state.labels.get(key, article)
        yield propose(
            f"content:winner:{article}", f"《{title}》7 天阅读是中位数的 {ratio:.1f} 倍：做成系列？",
            priority=2, forecast=0.5, due=days_after(today, 30), evidence=[key],
            why=f"7 天阅读 {reads:g}，同期中位数 {typical:g}。",
            recommend="同一母题换角度再写 2 篇，验证赢的是选题而不是运气。",
        )
        if ratio >= 3:
            yield candidate(f"content:topic:{article}", f"《{title}》的母题有复利潜力：7 天阅读达中位数 {ratio:.1f} 倍", evidence=[key])


def domain() -> Domain:
    hook = os.environ.get("YUANLI_CONTENT_PUBLISH_HOOK")
    return Domain(
        key="content", title="原力内容",
        sources=[inbox("content", folder("content", "YUANLI_CONTENT_DIR"), family="reads")],
        rules=[winners],
        metrics=[Metric("content.reads:", "阅读")],
        actions={"publish": webhook(hook)} if hook else {},
    )
