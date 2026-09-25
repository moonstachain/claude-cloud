"""原力投研 — 每个判断都有概率、到期日和结算。

NAV rows (`code,nav,date` or `key,value,at`) dropped in the invest inbox become
`invest.nav:<code>` facts. The ledger records *when* each value became known, so
every replay and every calibrated thesis is point-in-time by construction.
Theses themselves are ordinary items: a claim, a forecast, a due date.
"""
from __future__ import annotations

import os
from typing import Iterator

from ..domain import Domain, Emit, Metric, days_after, days_before, folder, inbox, propose, values
from ..state import State


def drawdown(state: State, today: str) -> Iterator[Emit]:
    threshold = float(os.environ.get("YUANLI_INVEST_DRAWDOWN", "0.15"))
    since = days_before(today, 365)
    for key in state.keys("invest.nav:"):
        navs = values([point for point in state.series(key) if point[0][:10] >= since])
        if len(navs) < 2 or max(navs) <= 0:
            continue
        peak, last = max(navs), navs[-1]
        loss = 1 - last / peak
        if loss < threshold:
            continue
        code = key.split(":", 1)[1]
        name = state.labels.get(key, code)
        yield propose(
            f"invest:drawdown:{code}:{today[:7]}", f"{name} 回撤 {loss:.0%}：复核持仓",
            priority=0 if loss >= 2 * threshold else 1, due=days_after(today, 14), evidence=[key],
            why=f"最新净值 {last:g}，一年内高点 {peak:g}。",
            recommend="回到买入时的逻辑：逻辑还在就持有，并写下一个带概率和到期日的新判断；逻辑破了就减仓。",
        )


def domain() -> Domain:
    return Domain(
        key="invest", title="原力投研",
        sources=[inbox("invest", folder("invest", "YUANLI_INVEST_DIR"), column="nav", family="nav")],
        rules=[drawdown],
        metrics=[Metric("invest.nav:", "净值")],
    )
