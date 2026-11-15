import logging
import re
import unicodedata
from collections import OrderedDict
from threading import Lock

import jieba
from rank_bm25 import BM25Okapi

jieba.setLogLevel(logging.WARNING)
STOP_WORDS = set(
    "的 了 和 与 及 是 在 我 需要 什么 如何 怎么 是否 请问 一个 可以 有 吗 多少 哪些 怎样".split()
)


def tokenize(text: str) -> list[str]:
    value = unicodedata.normalize("NFKC", text).lower()
    value = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", value)
    return [word for word in jieba.lcut(value) if re.search(r"\w", word) and word not in STOP_WORDS]


class KeywordIndex:
    def __init__(self, corpus):
        tokens = [tokenize(value) for value in corpus]
        self.terms = [set(row) for row in tokens]
        self.model = BM25Okapi(tokens) if tokens and any(tokens) else None

    def rank(self, question, limit):
        query = tokenize(question)
        if not query or self.model is None:
            return []
        scores = self.model.get_scores(query)
        candidates = [i for i, terms in enumerate(self.terms) if terms.intersection(query)]
        return [
            (i, float(scores[i])) for i in sorted(candidates, key=lambda i: (-scores[i], i))[:limit]
        ]


def keyword_ranking(question, corpus, *, limit=30):
    return KeywordIndex(corpus).rank(question, limit)


_CACHE = OrderedDict()
_LOCK = Lock()


def cached_keyword_index(key, corpus):
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        index = KeywordIndex(corpus)
        _CACHE[key] = index
        while len(_CACHE) > 8:
            _CACHE.popitem(last=False)
        return index


def reciprocal_rank_fusion(rankings, k=60):
    scores = {}
    for ranking in rankings:
        seen = set()
        for rank, identity in enumerate(ranking, 1):
            if identity in seen:
                continue
            seen.add(identity)
            scores[identity] = scores.get(identity, 0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))
