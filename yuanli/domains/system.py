"""原力OS 自身 — 机器还活着吗？仓库还在动吗？

Heartbeats: one JSON object per line in `<dir>/<host>.jsonl` (`{"ts": ..., "host": ...}`).
Repos: $YUANLI_REPOS, a colon-separated list of local git checkouts.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from ..domain import Domain, Emit, Metric, Source, fact, folder, propose
from ..state import State


def heartbeats(root: Path) -> Source:
    def fetch() -> Iterator[Emit]:
        for path in sorted(root.glob("*.jsonl")):
            for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
                try:
                    beat = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a torn last line: the previous beat is still true
                host = str(beat.get("host") or path.stem)
                yield fact(f"os.heartbeat:{host}", 1, str(beat.get("ts") or ""), label=host)
                break

    return Source("os.heartbeats", fetch, every=300)


def repos(paths: list[str]) -> Source:
    def fetch() -> Iterator[Emit]:
        today = date.today().isoformat()
        for raw in paths:
            path = Path(raw).expanduser()
            result = subprocess.run(["git", "-C", str(path), "log", "-1", "--format=%ct"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                idle = (time.time() - int(result.stdout.strip())) / 86400
                yield fact(f"os.repo_idle_days:{path.name}", round(idle, 1), today, label=path.name, unit="天")

    return Source("os.repos", fetch, every=3600)


def silent_hosts(state: State, today: str) -> Iterator[Emit]:
    hours = float(os.environ.get("YUANLI_HEARTBEAT_HOURS", "6"))
    now = datetime.now(timezone.utc)
    for key in state.keys("os.heartbeat:"):
        at, _ = state.latest(key)
        try:
            seen = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            continue
        seen = seen if seen.tzinfo else seen.astimezone()
        if now - seen > timedelta(hours=hours):
            host = key.split(":", 1)[1]
            silent = (now - seen).total_seconds() / 3600
            yield propose(
                f"os:silent:{host}:{today}", f"{host} 已 {silent:.0f} 小时没有心跳",
                priority=1, evidence=[key], why=f"最后一次心跳 {at}。",
                recommend="确认机器在线、定时任务仍在跑；不再使用就从心跳目录移除。",
            )


def domain() -> Domain:
    sources = [heartbeats(folder("os", "YUANLI_HEARTBEAT_DIR"))]
    repo_paths = [path for path in os.environ.get("YUANLI_REPOS", "").split(":") if path]
    if repo_paths:
        sources.append(repos(repo_paths))
    return Domain(
        key="os", title="原力OS", sources=sources, rules=[silent_hosts],
        metrics=[Metric("os.repo_idle_days:", "闲置", "天", good="down")],
    )
