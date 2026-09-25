from __future__ import annotations

import json

from yuanli.importers import import_osmax


def queue_item(key: str, status: str, **extra) -> dict:
    return {"id": key, "title": f"{key} 标题", "two_sentence": "两句话", "recommend": "建议", "priority": "P1",
            "gate": "G1", "status": status, "source_ref": "open-loops#1", "decided_at": "2026-07-10", "owner": "mingge", **extra}


def test_os_max_history_collapses_into_one_lifecycle(kernel, me, tmp_path):
    data = tmp_path / "osmax" / "data"
    (data / "calibration").mkdir(parents=True)
    (data / "decision-queue.json").write_text(json.dumps({"meta": {"as_of": "2026-07-17"}, "items": [
        queue_item("DQ-001", "pending", gate="G2"),
        queue_item("DQ-002", "decided", decision_note="批准"),
        queue_item("DQ-003", "deferred", due_at="2000-01-01", defer_reason="等凭证", resume_condition="凭证到位"),
        queue_item("DQ-004", "dropped"),
        queue_item("DQ-005", "close_ready"),
        queue_item("DQ-006", "done", outcome="上线验收通过"),
    ]}, ensure_ascii=False), encoding="utf-8")
    (data / "calibration" / "takes.json").write_text(json.dumps({"items": [
        {"take_id": "TAKE-001", "claim": "7/21 前 pending<5", "due_date": "2026-07-21", "weight": 0.6, "outcome": 1,
         "weight_decided_at": "2026-07-14T07:00:39+00:00", "outcome_decided_at": "2026-07-22T01:00:00+00:00",
         "status": "settled", "history": [{"at": "2026-07-14T07:00:28+00:00"}], "dq_refs": ["DQ-056"]},
    ]}, ensure_ascii=False), encoding="utf-8")

    first = import_osmax(kernel, tmp_path / "osmax")
    assert import_osmax(kernel, tmp_path / "osmax")["events"] == 0
    statuses = {key: item.status for key, item in kernel.state.items.items()}
    assert statuses == {"DQ-001": "open", "DQ-002": "approved", "DQ-003": "deferred", "DQ-004": "rejected",
                        "DQ-005": "approved", "DQ-006": "done", "TAKE-001": "done"}
    assert first == {"events": 16, "items": 7}
    assert kernel.state.items["DQ-001"].manual is True
    assert "等凭证" in kernel.state.items["DQ-003"].note and "DQ-003" in [c["id"] for c in kernel.brief(me)["decide"]]
    assert kernel.state.items["DQ-006"].note == "上线验收通过"
    take = kernel.state.items["TAKE-001"]
    assert (take.forecast, take.outcome, take.brier, take.forecast_by) == (0.6, 1.0, 0.16, "mingge")
    assert take.trail[0].ts == "2026-07-14T07:00:28Z"
