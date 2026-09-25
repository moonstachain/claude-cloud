"""Incremental inverted index. Chinese is tokenised into bigrams, so
"健康数据最近怎么样" matches "健康" and "数据" instead of needing the whole
sentence verbatim."""
from __future__ import annotations

import math
import re
from collections import defaultdict

_WORD = re.compile(r"[a-z0-9][a-z0-9_.:\-]*|[㐀-鿿豈-﫿]+")


def tokens(text: str) -> set[str]:
    found: set[str] = set()
    for run in _WORD.findall(text.lower()):
        if run[0].isascii():
            found.add(run)
            found.update(part for part in re.split(r"[_.:\-]", run) if len(part) > 1)
        elif len(run) == 1:
            found.add(run)
        else:
            found.update(run[i : i + 2] for i in range(len(run) - 1))
    return found


class Index:
    def __init__(self) -> None:
        self._postings: dict[str, set[str]] = defaultdict(set)
        self._docs: dict[str, set[str]] = {}

    def put(self, doc_id: str, text: str) -> None:
        new = tokens(text)
        old = self._docs.get(doc_id, set())
        for token in old - new:
            self._postings[token].discard(doc_id)
        for token in new - old:
            self._postings[token].add(doc_id)
        self._docs[doc_id] = new

    def search(self, query: str, limit: int = 20) -> list[tuple[str, float]]:
        total = len(self._docs) or 1
        scores: dict[str, float] = defaultdict(float)
        for token in tokens(query):
            posting = self._postings.get(token)
            if posting:
                weight = math.log(1 + total / len(posting))
                for doc_id in posting:
                    scores[doc_id] += weight
        return sorted(scores.items(), key=lambda pair: -pair[1])[:limit]
