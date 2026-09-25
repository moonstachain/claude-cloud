from __future__ import annotations

import json

import pytest
from conftest import propose

from yuanli.policy import Actor, Forbidden, authenticate, load_tokens
from yuanli.state import NotFound


def test_agents_observe_and_propose_but_never_decide_or_settle(kernel, me, bot):
    propose(kernel, bot, "t:1")
    kernel.emit(bot, "item.noted", {"id": "t:1", "note": "machine evidence"})
    for kind, data in (("item.decided", {"id": "t:1", "verdict": "approve"}), ("item.settled", {"id": "t:1", "outcome": 1})):
        with pytest.raises(Forbidden):
            kernel.emit(bot, kind, data)
    assert kernel.ledger.seq == 2


def test_viewers_cannot_write_anything(kernel):
    viewer = Actor("guest", role="viewer", audience="public")
    with pytest.raises(Forbidden):
        propose(kernel, viewer)


def test_scope_is_enforced_on_every_read_path(kernel, me, tmp_path):
    propose(kernel, me, "pub:1", title="公开的原则实验", scope="public")
    propose(kernel, me, "team:1", title="团队的原则复盘", scope="team")
    propose(kernel, me, "priv:1", title="私密的原则体检", scope="private")
    public, team = Actor("p", "viewer", "public"), Actor("t", "viewer", "team")
    assert [card["id"] for card in kernel.brief(public)["decide"]] == ["pub:1"]
    assert {card["id"] for card in kernel.brief(team)["decide"]} == {"pub:1", "team:1"}
    assert {hit["id"] for hit in kernel.search(public, "原则")} == {"pub:1"}
    with pytest.raises(NotFound):
        kernel.item(public, "priv:1")
    kernel.export("public", tmp_path / "dist")
    snapshot = (tmp_path / "dist" / "snapshot.json").read_text(encoding="utf-8")
    assert "公开的原则实验" in snapshot and "私密" not in snapshot and "团队" not in snapshot
    assert json.loads(snapshot)["brief"]["sources"]["down"] == []
    assert 'name="yuanli-static"' in (tmp_path / "dist" / "index.html").read_text(encoding="utf-8")


def test_token_spec():
    tokens = load_tokens("aaa:mingge:principal,bbb:ios:agent,ccc:team:viewer:team,ddd:web:viewer")
    assert authenticate(tokens, "bbb") == Actor("ios", "agent", "private")
    assert authenticate(tokens, "ccc").audience == "team"
    assert authenticate(tokens, "ddd").audience == "public"
    assert authenticate(tokens, "zzz") is None and authenticate(tokens, None) is None
    with pytest.raises(ValueError):
        load_tokens("x:y:root")
