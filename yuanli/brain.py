"""Answer a question from retrieved records. Deterministic by default; with
YUANLI_BRAIN=1 (and the `anthropic` package + credentials) Claude writes a short
grounded answer that cites the records by number."""
from __future__ import annotations

import os
from typing import Any

SYSTEM = (
    "你是原力OS的检索助手。只依据用户消息里编号列出的记录回答，用 2-3 句中文。"
    "每个结论后用 [编号] 标注出处；记录不足以回答时直接说明缺什么，不要推测。"
)
STATUS = {"open": "待拍板", "approved": "进行中", "deferred": "已推迟", "rejected": "已否决", "done": "已结算",
          "candidate": "候选", "canon": "正典", "retired": "已退役"}


def answer(question: str, hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "没有找到相关记录。"
    if os.environ.get("YUANLI_BRAIN") == "1":
        try:
            return _claude(question, hits)
        except Exception as exc:  # the brain is optional; retrieval still answers
            return f"{_plain(hits)}（Claude 不可用：{type(exc).__name__}）"
    return _plain(hits)


def _plain(hits: list[dict[str, Any]]) -> str:
    listed = "；".join(f"[{n}] {hit['title']}" + (f"（{STATUS.get(hit['status'], hit['status'])}）" if hit["status"] else "")
                      for n, hit in enumerate(hits[:5], 1))
    return f"找到 {len(hits)} 条相关记录：{listed}"


def _claude(question: str, hits: list[dict[str, Any]]) -> str:
    import anthropic

    records = "\n".join(
        f"[{n}] ({hit['kind']}/{hit['domain']}/{STATUS.get(hit['status'], hit['status']) or '-'}) {hit['title']} {hit['text']}".strip()
        for n, hit in enumerate(hits, 1)
    )
    response = anthropic.Anthropic().beta.messages.create(
        model=os.environ.get("YUANLI_MODEL", "claude-opus-5"),
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": f"记录：\n{records}\n\n问题：{question}"}],
    )
    if response.stop_reason == "refusal":
        return _plain(hits)
    return "".join(block.text for block in response.content if block.type == "text").strip() or _plain(hits)
