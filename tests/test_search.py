import pandas as pd

from paper_rag.search import _reciprocal_rank_fusion, hybrid_search


def test_reciprocal_rank_fusion_rewards_agreement():
    fused = _reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]])
    # "a" and "b" appear near the top of both lists, so they should
    # outscore "c" and "d", which only appear in one list each.
    assert fused["a"] > fused["c"]
    assert fused["b"] > fused["d"]


def test_reciprocal_rank_fusion_single_list_preserves_order():
    fused = _reciprocal_rank_fusion([["x", "y", "z"]])
    assert fused["x"] > fused["y"] > fused["z"]


class _FakeIndex:
    """Stands in for PaperIndex.search: returns canned vector-search hits,
    deliberately omitting the chunk that only a lexical match would find.
    """

    def __init__(self, hits):
        self._hits = hits

    def search(self, table, query_vector, k=5, citation_key=None):
        hits = self._hits
        if citation_key:
            hits = [h for h in hits if h["citation_key"] == citation_key]
        hits = [dict(h, vector_distance=0.1) for h in hits[:k]]
        return hits


_ROWS = [
    {
        "chunk_id": "paperA::0",
        "citation_key": "paperA",
        "section": "Results",
        "text": "The model achieves state of the art performance on the benchmark.",
        "token_count": 10,
        "pdf_path": "paperA.pdf",
    },
    {
        "chunk_id": "paperA::1",
        "citation_key": "paperA",
        "section": "Results",
        "text": "Hellinger distance for GC on Acute Myeloid Leukemia was 0.042.",
        "token_count": 10,
        "pdf_path": "paperA.pdf",
    },
    {
        "chunk_id": "paperB::0",
        "citation_key": "paperB",
        "section": "Intro",
        "text": "Synthetic tabular data generation is an active research area.",
        "token_count": 10,
        "pdf_path": "paperB.pdf",
    },
]


def _fake_table(rows):
    class _T:
        def to_pandas(self):
            return pd.DataFrame(rows)

    return _T()


def test_hybrid_search_surfaces_lexical_only_match():
    # Vector search "misses" the exact-fact chunk (paperA::1) entirely —
    # only BM25 keyword overlap on "Hellinger" and "Leukemia" should pull
    # it into the fused top-k.
    vector_hits = [dict(_ROWS[0]), dict(_ROWS[2])]
    index = _FakeIndex(vector_hits)
    table = _fake_table(_ROWS)

    results = hybrid_search(
        index, table, "Hellinger distance GC Acute Myeloid Leukemia", query_vector=[0.0], k=2
    )

    ids = [r["chunk_id"] for r in results]
    assert "paperA::1" in ids
    assert all("score" in r for r in results)

    # The lexical-only match should carry a raw bm25_score but no
    # vector_distance (vector search never returned it); the vector-only
    # match should carry vector_distance but no bm25_score.
    lexical_only = next(r for r in results if r["chunk_id"] == "paperA::1")
    assert "bm25_score" in lexical_only
    assert "vector_distance" not in lexical_only


def test_hybrid_search_respects_citation_key_filter():
    index = _FakeIndex([dict(r) for r in _ROWS])
    table = _fake_table(_ROWS)

    results = hybrid_search(
        index, table, "synthetic tabular data", query_vector=[0.0], k=5, citation_key="paperA"
    )

    assert all(r["citation_key"] == "paperA" for r in results)
