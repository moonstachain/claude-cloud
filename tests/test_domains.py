from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from conftest import propose

from yuanli.domain import Domain, fact, inbox
from yuanli.domains import health, load
from yuanli.kernel import Kernel

TODAY = datetime.now(timezone.utc).date()


def day(offset: int) -> str:
    return (TODAY - timedelta(days=offset)).isoformat()


def seed(kernel, me, rows):
    kernel.emit_many(me, [fact(key, value, at, **extra) for key, value, at, extra in rows])


def test_inbox_reads_csv_and_jsonl_with_column_aliases(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.csv").write_text("date,code,nav\n2026-09-01,000001,1.25\n2026-09-02,000001,1.20\n", encoding="utf-8")
    (folder / "b.jsonl").write_text(json.dumps({"key": "nav:000002", "value": 2, "at": "2026-09-02", "label": "债基"}) + "\n", encoding="utf-8")
    source = inbox("invest", folder, column="nav", family="nav")
    facts = [emit.data for emit in source.fetch()]
    assert [(f["key"], f["value"]) for f in facts] == [("invest.nav:000001", 1.25), ("invest.nav:000001", 1.2), ("invest.nav:000002", 2)]
    assert facts[2]["label"] == "债基"
    assert list(source.fetch()) == []  # unchanged files are skipped


def test_health_recovery_and_sleep_rules(kernel, me):
    rows = [("health.hrv", 55 if n > 2 else 38, day(n), {}) for n in range(20)]
    rows += [("health.sleep_h", 5.9, day(n), {}) for n in range(3)]
    seed(kernel, me, rows)
    result = kernel.collect(only={"health"})
    assert result["proposals"] == 2
    recovery = next(item for item in kernel.state.items.values() if item.id.startswith("health:recovery"))
    assert recovery.measure["target"] == 52.2 and recovery.forecast == 0.6
    assert kernel.collect(only={"health"})["proposals"] == 0  # same week: no duplicate


def test_apple_health_export_merges_overlapping_sleep(tmp_path):
    export = tmp_path / "export.xml"
    export.write_text("""<?xml version="1.0"?><HealthData>
      <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" value="40" startDate="2026-09-20 07:00:00 +0800" endDate="2026-09-20 07:01:00 +0800"/>
      <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" value="50" startDate="2026-09-20 08:00:00 +0800" endDate="2026-09-20 08:01:00 +0800"/>
      <Record type="HKQuantityTypeIdentifierStepCount" value="3000" startDate="2026-09-20 09:00:00 +0800" endDate="2026-09-20 10:00:00 +0800"/>
      <Record type="HKQuantityTypeIdentifierStepCount" value="4000" startDate="2026-09-20 11:00:00 +0800" endDate="2026-09-20 12:00:00 +0800"/>
      <Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisAsleepCore" startDate="2026-09-19 23:00:00 +0800" endDate="2026-09-20 05:00:00 +0800"/>
      <Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisAsleepDeep" startDate="2026-09-20 04:00:00 +0800" endDate="2026-09-20 06:30:00 +0800"/>
      <Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisInBed" startDate="2026-09-19 22:00:00 +0800" endDate="2026-09-20 07:00:00 +0800"/>
    </HealthData>""", encoding="utf-8")
    facts = {emit.data["key"]: emit.data["value"] for emit in health.apple_health(export).fetch()}
    assert facts == {"health.hrv": 45.0, "health.steps": 7000.0, "health.sleep_h": 7.5}


def test_invest_drawdown_escalates_with_depth(kernel, me):
    seed(kernel, me, [("invest.nav:000001", nav, day(n), {"label": "宽基增强"}) for n, nav in enumerate([0.6, 0.8, 1.0, 1.2])])
    kernel.collect(only={"invest"})
    item = next(iter(kernel.state.items.values()))
    assert item.title.startswith("宽基增强 回撤 50%") and item.priority == 0


def test_venture_envelopes_and_stalled_projects(kernel, tmp_path, monkeypatch):
    root = tmp_path / "projects" / "camp"
    root.mkdir(parents=True)
    (root / "envelope.json").write_text(json.dumps({
        "schema": "project_evidence_envelope_v1",
        "project": {"project_id": "camp", "title": "创业营", "risk_level": "red", "next_action": "定名单"},
        "state": {"progress": {"weighted_execution_pct": 40}, "decisions_needed": [{"decision": "定价 9800？"}]},
        "updated_at": day(30) + "T10:00:00+08:00",
    }), encoding="utf-8")
    monkeypatch.setenv("YUANLI_VENTURE_PROJECTS", str(tmp_path / "projects"))
    kernel = Kernel(tmp_path / "home2", domains=load("venture"))
    kernel.collect()
    titles = sorted(item.title for item in kernel.state.items.values())
    assert titles == ["创业营 已 30 天没有进展：推进、砍掉，还是推迟？", "创业营 风险转红", "创业营：定价 9800？"]
    assert {item.priority for item in kernel.state.items.values()} == {0, 1}


def test_content_winner_becomes_item_and_canon_candidate(kernel, me):
    rows = []
    for n in range(6):
        reads = 9000 if n == 0 else 1000
        rows += [(f"content.reads:A{n}", reads * (d + 1) // 8, day(20 - d), {"label": f"文章{n}"}) for d in range(8)]
    seed(kernel, me, rows)
    kernel.collect(only={"content"})
    assert "content:winner:A0" in kernel.state.items
    assert kernel.state.canon["content:topic:A0"].status == "candidate"


def test_silent_host_and_torn_heartbeat(kernel, tmp_path, monkeypatch):
    beats = tmp_path / "beats"
    beats.mkdir()
    old = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 12 * 3600))
    (beats / "m3.jsonl").write_text(json.dumps({"ts": old, "host": "m3"}) + '\n{"ts": "2026-', encoding="utf-8")
    monkeypatch.setenv("YUANLI_HEARTBEAT_DIR", str(beats))
    kernel = Kernel(tmp_path / "home3", domains=load("os"))
    kernel.collect()
    assert [item.title for item in kernel.state.items.values()] == ["m3 已 12 小时没有心跳"]


def test_broken_source_degrades_to_a_status_not_a_crash(tmp_path):
    def explode():
        raise OSError("disk gone")
        yield

    from yuanli.domain import Source

    kernel = Kernel(tmp_path / "home4", domains=[Domain("health", "健康", sources=[Source("boom", explode)])])
    assert kernel.collect() == {"sources": 1, "facts": 0, "proposals": 0}
    assert kernel.sources["boom"]["ok"] is False and "disk gone" in kernel.sources["boom"]["detail"]


def test_approved_item_runs_its_domain_action(tmp_path, me):
    ran = []
    domain = Domain("content", "内容", actions={"publish": lambda item: ran.append(item.id) or "draft 42"})
    kernel = Kernel(tmp_path / "home5", domains=[domain])
    propose(kernel, me, "c:1", domain="content", action="publish")
    kernel.emit(me, "item.decided", {"id": "c:1", "verdict": "approve"})
    kernel._pool.shutdown(wait=True)
    assert ran == ["c:1"]
    assert kernel.state.items["c:1"].trail[-1].data["note"] == "已执行 publish：draft 42"
