from __future__ import annotations

import pytest

from yuanli.domains import load
from yuanli.kernel import Kernel
from yuanli.policy import Actor


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("YUANLI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("YUANLI_TZ", "UTC")
    for name in ("YUANLI_TOKENS", "YUANLI_BRAIN", "YUANLI_REPOS", "YUANLI_CONTENT_PUBLISH_HOOK", "YUANLI_DOMAINS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def kernel(tmp_path):
    return Kernel(tmp_path / "home", domains=load())


@pytest.fixture
def me():
    return Actor("mingge")


@pytest.fixture
def bot():
    return Actor("health:rules", role="agent")


def propose(kernel, actor, item_id="t:1", **fields):
    data = {"id": item_id, "domain": "health", "title": "测试决策", **fields}
    return kernel.emit(actor, "item.proposed", data)
