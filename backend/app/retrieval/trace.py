"""Bounded retrieval evidence and actual phase measurements for saved chat details."""

from time import monotonic


def phase(key, started=None, status="completed"):
    return {
        "key": key,
        "status": status,
        "duration_ms": round((monotonic() - started) * 1000, 2) if started is not None else None,
    }


def retrieval_trace(
    question,
    sources,
    fused,
    lexical,
    vector,
    rerank,
    selected,
    stages,
    counts,
    *,
    fusion_order=None,
):
    ranks = {
        "bm25": {identity: rank for rank, identity in enumerate(lexical, 1)},
        "vector": {identity: rank for rank, identity in enumerate(vector, 1)},
        "fusion": {
            identity: rank
            for rank, (identity, score) in enumerate(
                fusion_order if fusion_order is not None else fused, 1
            )
            if score is not None
        },
        "rerank": {identity: rank for rank, identity in enumerate(rerank, 1)},
    }
    return {
        "query": question,
        "stages": stages,
        "counts": counts,
        "candidates": [
            {
                "source": {**sources[identity], "content": sources[identity]["content"][:800]},
                "excerpt_truncated": len(sources[identity]["content"]) > 800,
                "scores": {
                    "bm25": lexical.get(identity),
                    "vector_distance": vector.get(identity),
                    "rrf": score,
                    "rerank": rerank.get(identity),
                },
                "ranks": {key: mapping.get(identity) for key, mapping in ranks.items()},
                "selected": identity in selected,
            }
            for identity, score in fused
        ],
    }
