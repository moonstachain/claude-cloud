"""Domain apps. Add one by writing a module with `domain() -> Domain` and listing it here."""
from __future__ import annotations

import os

from ..domain import Domain
from . import content, health, invest, system, venture

MODULES = {"health": health, "invest": invest, "venture": venture, "content": content, "os": system}


def load(names: str | None = None) -> list[Domain]:
    chosen = names or os.environ.get("YUANLI_DOMAINS") or ",".join(MODULES)
    return [MODULES[name.strip()].domain() for name in chosen.split(",") if name.strip()]
