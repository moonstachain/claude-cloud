"""The same hot paths measured on yuanli-os-max, for docs/prototype/REVIEW-OSMAX.md §6.

    cd yuanli-os-max && uv sync --extra dev --locked
    uv run python /path/to/bench_osmax.py [repo_root]

To reproduce the 5,000-item row, clone the repo, expand data/decision-queue.json
to 5,000 items (copy entries, renumber ids), and point repo_root at the copy.
"""
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

from osmax.config import Settings
from osmax.service import build_brief, deterministic_chat, project
from osmax.store import ReadModel

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
os.environ.setdefault("OSMAX_CSRF_SECRET", "x" * 32)
var = Path(tempfile.mkdtemp())
settings = Settings(repo_root=root, var_dir=var, db_path=var / "rm.sqlite3", profile="private", csrf_secret="x" * 32)
started = time.perf_counter()
project(settings)
print("collect/project:", round((time.perf_counter() - started) * 1000, 1), "ms")
model = ReadModel(settings.db_path)


def bench(name, fn, n=30):
    samples = []
    for _ in range(n):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    print(f"{name}: median {statistics.median(samples):.2f} ms  p95 {sorted(samples)[int(n * .95) - 1]:.2f} ms")


ids = [record["id"] for record in model.list_records(kind="decision")]
bench("build_brief", lambda: build_brief(model, "private", settings))
bench("get_record", lambda: model.get_record(ids[-1]))
bench("chat 今天只需我拍板什么", lambda: deterministic_chat(model, "今天只需我拍板什么", "private", settings), n=15)
bench("chat 晨会 队列 收敛", lambda: deterministic_chat(model, "晨会 队列 收敛", "private", settings), n=15)
print("decision items:", len(ids))
