from __future__ import annotations

import json
import threading

from conftest import propose

from yuanli.domains import load
from yuanli.kernel import Kernel


def test_state_is_rebuilt_from_the_ledger_alone(kernel, me, tmp_path):
    propose(kernel, me, "t:1")
    kernel.emit(me, "item.decided", {"id": "t:1", "verdict": "approve", "forecast": 0.7})
    kernel.emit(me, "item.settled", {"id": "t:1", "outcome": 1})
    reborn = Kernel(tmp_path / "home", domains=load())
    item = reborn.state.items["t:1"]
    assert (item.status, item.outcome, item.brier, item.rev) == ("done", 1.0, 0.09, 3)
    assert [event.type for event in item.trail] == ["item.proposed", "item.decided", "item.settled"]


def test_same_event_id_is_written_once(kernel, me):
    first = kernel.emit(me, "item.proposed", {"id": "t:1", "domain": "os", "title": "a"}, event_id="k1")
    again = kernel.emit(me, "item.proposed", {"id": "t:1", "domain": "os", "title": "a"}, event_id="k1")
    assert first.seq == again.seq == kernel.ledger.seq == 1


def test_second_process_sees_first_process_writes(kernel, me, tmp_path):
    other = Kernel(tmp_path / "home", domains=load())
    propose(kernel, me, "t:1")
    assert "t:1" not in other.state.items
    other.emit(me, "item.decided", {"id": "t:1", "verdict": "reject"})  # catches up under the lock first
    kernel.sync()
    assert kernel.state.items["t:1"].status == "rejected"
    assert [e["seq"] for e in kernel.events()] == [1, 2]


def test_torn_tail_from_a_crash_is_discarded(kernel, me, tmp_path):
    propose(kernel, me, "t:1")
    with kernel.ledger.path.open("ab") as handle:
        handle.write(b'{"seq":2,"id":"x","ts":"')
    reborn = Kernel(tmp_path / "home", domains=load())
    propose(reborn, me, "t:2")
    lines = kernel.ledger.path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["seq"] for line in lines] == [1, 2]


def test_concurrent_writers_get_unique_sequence_numbers(kernel, me):
    threads = [threading.Thread(target=propose, args=(kernel, me, f"t:{n}")) for n in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    seqs = [event["seq"] for event in kernel.events(limit=1000)]
    assert seqs == list(range(1, 41))


def test_failed_validation_in_a_batch_keeps_the_valid_prefix(kernel, me):
    from yuanli.domain import Emit
    from yuanli.state import Invalid

    good = Emit("item.proposed", {"id": "t:1", "domain": "os", "title": "ok"})
    bad = Emit("item.decided", {"id": "t:1", "verdict": "maybe"})
    try:
        kernel.emit_many(me, [good, bad])
    except Invalid:
        pass
    assert kernel.ledger.seq == 1 and kernel.state.items["t:1"].status == "open"
    assert len(kernel.ledger.path.read_text().splitlines()) == 1
