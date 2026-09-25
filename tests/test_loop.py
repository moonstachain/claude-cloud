from __future__ import annotations

import pytest
from conftest import propose

from yuanli.state import Conflict, Invalid, NotFound


def test_the_whole_loop_propose_decide_note_settle(kernel, me):
    propose(kernel, me, "t:1", priority="P0", forecast=0.8, due="2099-01-01")
    assert [card["id"] for card in kernel.brief(me)["decide"]] == ["t:1"]
    kernel.emit(me, "item.decided", {"id": "t:1", "verdict": "approve", "note": "去做"})
    brief = kernel.brief(me)
    assert not brief["decide"] and brief["doing"][0]["id"] == "t:1"
    kernel.emit(me, "item.noted", {"id": "t:1", "note": "已执行", "evidence": ["receipt.json"]})
    kernel.emit(me, "item.settled", {"id": "t:1", "outcome": True, "note": "达成"})
    item = kernel.item(me, "t:1")
    assert item["status"] == "done" and item["brier"] == pytest.approx(0.04)
    assert "receipt.json" in item["evidence"]
    assert kernel.brief(me)["doing"] == []


def test_stale_revision_is_rejected(kernel, me):
    propose(kernel, me, "t:1")
    kernel.emit(me, "item.noted", {"id": "t:1", "note": "新证据"})
    with pytest.raises(Conflict, match="rev 2, you saw 1"):
        kernel.emit(me, "item.decided", {"id": "t:1", "verdict": "approve", "rev": 1})
    kernel.emit(me, "item.decided", {"id": "t:1", "verdict": "approve", "rev": 2})


def test_closed_items_cannot_be_decided_or_reproposed(kernel, me):
    propose(kernel, me, "t:1")
    kernel.emit(me, "item.decided", {"id": "t:1", "verdict": "reject"})
    with pytest.raises(Conflict):
        kernel.emit(me, "item.decided", {"id": "t:1", "verdict": "approve"})
    with pytest.raises(Conflict):
        propose(kernel, me, "t:1")
    with pytest.raises(NotFound):
        kernel.emit(me, "item.decided", {"id": "nope", "verdict": "approve"})


def test_defer_defaults_to_a_week_and_comes_back_when_due(kernel, me):
    propose(kernel, me, "t:1")
    event = kernel.emit(me, "item.decided", {"id": "t:1", "verdict": "defer"})
    assert event.data["until"] > kernel.today()
    assert kernel.brief(me)["decide"] == []
    propose(kernel, me, "t:2")
    kernel.emit(me, "item.decided", {"id": "t:2", "verdict": "defer", "until": "2000-01-01"})
    assert [card["id"] for card in kernel.brief(me)["decide"]] == ["t:2"]


@pytest.mark.parametrize("data, message", [
    ({"id": "t:9", "domain": "health"}, "title is required"),
    ({"id": "t:9", "domain": "health", "title": "x", "priority": "P7"}, "priority"),
    ({"id": "t:9", "domain": "health", "title": "x", "forecast": 1.5}, "probability"),
    ({"id": "t:9", "domain": "health", "title": "x", "due": "next week"}, "date"),
    ({"id": "t:9", "domain": "health", "title": "x", "scope": "world"}, "scope"),
    ({"id": "t:9", "domain": "mars", "title": "x"}, "unknown domain"),
    ({"id": "t:9", "domain": "health", "title": "x", "measure": {"key": "health.hrv", "target": "high"}}, "measure target"),
])
def test_bad_proposals_never_reach_the_ledger(kernel, me, data, message):
    with pytest.raises(Invalid, match=message):
        kernel.emit(me, "item.proposed", data)
    assert kernel.ledger.seq == 0


def test_overdue_and_measured_suggestion(kernel, me):
    propose(kernel, me, "t:1", due="2000-01-01", measure={"key": "health.hrv", "target": 50, "good": "up"})
    kernel.emit(me, "item.decided", {"id": "t:1", "verdict": "approve"})
    kernel.emit(me, "fact.observed", {"key": "health.hrv", "value": 52, "at": "2026-09-20"})
    card = kernel.brief(me)["doing"][0]
    assert card["overdue"] is True
    assert card["suggest"] == {"outcome": 1.0, "value": 52, "at": "2026-09-20", "target": 50, "key": "health.hrv"}


def test_calibration_separates_human_and_machine_forecasts(kernel, me, bot):
    propose(kernel, bot, "m:1", forecast=0.9)
    propose(kernel, me, "h:1")
    kernel.emit(me, "item.decided", {"id": "m:1", "verdict": "approve"})
    kernel.emit(me, "item.decided", {"id": "h:1", "verdict": "approve", "forecast": 0.6})
    kernel.emit(me, "item.settled", {"id": "m:1", "outcome": 0})
    kernel.emit(me, "item.settled", {"id": "h:1", "outcome": 1})
    calibration = kernel.calibration(me)
    assert calibration["groups"]["by:machine"] == {"n": 1, "brier": 0.81}
    assert calibration["groups"]["by:human"] == {"n": 1, "brier": 0.16}
    assert calibration["overall"] == {"n": 2, "brier": 0.485}
    assert {bin_["forecast"] for bin_ in calibration["reliability"]} == {0.6, 0.9}


def test_canon_lifecycle(kernel, me, bot):
    kernel.emit(bot, "canon.proposed", {"id": "c:1", "statement": "长期主义胜过短期刺激", "domain": "content"})
    with pytest.raises(Conflict):
        kernel.emit(me, "canon.ruled", {"id": "c:1", "verdict": "retire"})
    kernel.emit(me, "canon.ruled", {"id": "c:1", "verdict": "admit"})
    kernel.emit(me, "canon.ruled", {"id": "c:1", "verdict": "retire"})
    assert kernel.canon(me)[0]["status"] == "retired"


def test_search_understands_chinese_without_spaces(kernel, me):
    propose(kernel, me, "t:1", title="八类凭据轮换与三机 token 收口")
    propose(kernel, me, "t:2", title="第三期定价")
    hits = kernel.search(me, "凭据什么时候轮换完")
    assert hits[0]["id"] == "t:1" and all(hit["id"] != "t:2" for hit in hits)
    answer = kernel.ask(me, "凭据轮换")
    assert "八类凭据" in answer["answer"] and answer["citations"][0]["id"] == "t:1"
