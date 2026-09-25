"""Who may write what, and who may see what. That is the whole governance layer.

Three roles replace G0/G1/G2, truth-writer env flags, CSRF secrets and
substring blacklists:

    principal  the human. Only a principal decides, settles and rules on canon.
    agent      machines and domain adapters. They observe, propose and annotate.
    viewer     read-only, limited to an audience scope (team or public).
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from .state import SCOPES

HUMAN_ONLY = frozenset({"item.decided", "item.settled", "canon.ruled"})
AGENT_WRITES = frozenset({"fact.observed", "item.proposed", "item.noted", "canon.proposed"})
_RANK = {scope: rank for rank, scope in enumerate(SCOPES)}


class Forbidden(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class Actor:
    name: str
    role: str = "principal"
    audience: str = "private"

    def can_write(self, kind: str) -> bool:
        if self.role == "principal":
            return True
        return self.role == "agent" and kind in AGENT_WRITES

    def require(self, kind: str) -> None:
        if not self.can_write(kind):
            raise Forbidden(f"{self.role} {self.name} cannot write {kind}")

    def sees(self, scope: str) -> bool:
        return _RANK.get(scope, _RANK["private"]) <= _RANK[self.audience]


def principal() -> Actor:
    return Actor(os.environ.get("YUANLI_PRINCIPAL", "principal"))


def agent(name: str) -> Actor:
    return Actor(name, role="agent")


def load_tokens(spec: str | None = None) -> dict[str, Actor]:
    """`YUANLI_TOKENS="token:name:role[:audience],..."` -> {token: Actor}."""
    tokens: dict[str, Actor] = {}
    for entry in filter(None, (spec if spec is not None else os.environ.get("YUANLI_TOKENS", "")).split(",")):
        token, name, role, *rest = entry.strip().split(":")
        audience = rest[0] if rest else ("private" if role != "viewer" else "public")
        if role not in {"principal", "agent", "viewer"} or audience not in SCOPES:
            raise ValueError(f"bad token entry for {name}")
        tokens[token] = Actor(name, role, audience)
    return tokens


def authenticate(tokens: dict[str, Actor], supplied: str | None) -> Actor | None:
    if not supplied:
        return None
    for token, actor in tokens.items():
        if hmac.compare_digest(token, supplied):
            return actor
    return None
