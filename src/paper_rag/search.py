"""Hybrid retrieval: dense vector search (LanceDB) + lexical BM25, merged via
Reciprocal Rank Fusion.

Pure dense search plateaued at 80% Hit Rate@5 on this project's benchmark
(see HANDOFF.md), concentrated on exact-fact lookups — table values, model
names, acronyms — that a dense embedding can blur together across
near-duplicate chunks. BM25 catches exact token matches without any of that
ambiguity, and RRF combines the two rankings without needing their scores
(cosine distance vs. BM25 score) to be on comparable scales.
"""
from __future__ import annotations

import re
from typing import Any

from rank_bm25 import BM25Okapi

_RRF_K = 60
# Each method retrieves its own candidate pool independently before fusion
# narrows down to k; a wider pool than k gives RRF room to promote a result
# that one method ranked highly but the other missed entirely.
_POOL_SIZE_MULTIPLIER = 4
_MIN_POOL_SIZE = 20

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _lexical_search(table, query: str, k: int, citation_key: str | None = None) -> list[dict[str, Any]]:
    # Rebuilds the BM25 index from the full table on every call rather than
    # persisting one — for a corpus of a few hundred to a few thousand
    # chunks this is milliseconds, and it guarantees the lexical index can
    # never drift out of sync with adds/deletes in the vector table.
    df = table.to_pandas()
    if citation_key:
        df = df[df["citation_key"] == citation_key]
    if df.empty:
        return []
    corpus = df["text"].tolist()
    bm25 = BM25Okapi([_tokenize(doc) for doc in corpus])
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(range(len(corpus)), key=lambda i: scores[i], reverse=True)
    rows = df.to_dict("records")
    hits = []
    for i in ranked[:k]:
        if scores[i] <= 0:
            continue
        row = dict(rows[i])
        row["bm25_score"] = float(scores[i])
        hits.append(row)
    return hits


def _reciprocal_rank_fusion(ranked_id_lists: list[list[str]], k: int = _RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked_ids in ranked_id_lists:
        for rank, doc_id in enumerate(ranked_ids):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def hybrid_search(
    index,
    table,
    query: str,
    query_vector: list[float],
    k: int = 5,
    citation_key: str | None = None,
) -> list[dict[str, Any]]:
    """Dense + lexical retrieval, merged by Reciprocal Rank Fusion.

    Returns up to k chunk dicts (chunk_id, citation_key, section, text,
    token_count, pdf_path, plus a fused `score`, higher = more relevant),
    ordered by fused rank.
    """
    pool = max(k * _POOL_SIZE_MULTIPLIER, _MIN_POOL_SIZE)
    vector_hits = index.search(table, query_vector, k=pool, citation_key=citation_key)
    lexical_hits = _lexical_search(table, query, k=pool, citation_key=citation_key)

    by_id = {r["chunk_id"]: r for r in vector_hits}
    for r in lexical_hits:
        if r["chunk_id"] in by_id:
            by_id[r["chunk_id"]]["bm25_score"] = r["bm25_score"]
        else:
            by_id[r["chunk_id"]] = r

    fused = _reciprocal_rank_fusion(
        [
            [r["chunk_id"] for r in vector_hits],
            [r["chunk_id"] for r in lexical_hits],
        ]
    )
    ranked_ids = sorted(fused, key=fused.get, reverse=True)[:k]

    results = []
    for cid in ranked_ids:
        row = dict(by_id[cid])
        row["score"] = fused[cid]
        results.append(row)
    return results
