"""Latency of the hot paths, on the same workload used to measure yuanli-os-max.

    python bench/bench.py [path/to/yuanli-os-max] [items]

With an os-max checkout, its real decision queue is imported and then cloned up
to `items` entries (the old benchmark used 5,000). Without one, synthetic items.
"""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

from yuanli.domain import fact
from yuanli.domains import load
from yuanli.importers import queue_emits
from yuanli.kernel import Kernel
from yuanli.policy import Actor


def timed(label: str, fn, runs: int = 30) -> None:
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    print(f"  {label:<34} median {statistics.median(samples):8.3f} ms   p95 {samples[int(runs * 0.95) - 1]:8.3f} ms")


def main() -> None:
    osmax = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    home = Path(tempfile.mkdtemp())
    kernel = Kernel(home, domains=load())
    me = Actor("mingge")
    if osmax and (osmax / "data" / "decision-queue.json").exists():
        base = json.loads((osmax / "data" / "decision-queue.json").read_text(encoding="utf-8"))["items"]
    else:
        base = [{"id": "DQ-1", "title": "示例决策 凭据 轮换", "two_sentence": "两句话说明", "recommend": "建议", "priority": "P1", "status": "pending"}]
    items = [{**base[n % len(base)], "id": f"DQ-{n + 1000:05d}"} for n in range(target)]

    started = time.perf_counter()
    kernel.emit_many(me, [emit for _, emit in queue_emits({"meta": {}, "items": items})])
    kernel.emit_many(Actor("invest:bench", "agent"), [fact(f"invest.nav:{n % 200:06d}", 1 + n % 97 / 100, f"2026-{1 + n // 200 // 28 % 12:02d}-{1 + n // 200 % 28:02d}") for n in range(20000)])
    print(f"ledger: {kernel.ledger.seq} events, {kernel.ledger.path.stat().st_size / 1e6:.1f} MB, written in {(time.perf_counter() - started) * 1000:.0f} ms")

    started = time.perf_counter()
    reborn = Kernel(home, domains=load())
    print(f"cold start (replay all events): {(time.perf_counter() - started) * 1000:.0f} ms\n")

    some = items[-1]["id"]
    timed("brief (the whole Today page)", lambda: reborn.brief(me))
    timed("item lookup", lambda: reborn.item(me, some))
    timed("search 晨会 队列 收敛", lambda: reborn.search(me, "晨会 队列 收敛"))
    timed("ask 今天只需我拍板什么", lambda: reborn.ask(me, "今天只需我拍板什么"), runs=15)
    timed("domain view 原力投研 (200 series)", lambda: reborn.domain_view(me, "invest"))
    counter = iter(range(10**9))
    timed("write one event (fsync)", lambda: reborn.emit(me, "item.noted", {"id": some, "note": f"n{next(counter)}"}))


if __name__ == "__main__":
    main()
