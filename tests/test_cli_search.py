import argparse
from unittest.mock import patch

from paper_rag.cli import cmd_search


class _FakeBackend:
    def embed(self, texts, is_query=False):
        return [[0.0, 0.0, 0.0, 0.0] for _ in texts]


def test_cmd_search_prints_raw_per_method_scores(capsys):
    results = [
        {
            "citation_key": "paperA",
            "section": "Results",
            "text": "some matched text",
            "score": 0.0328,
            "vector_distance": 0.12,
            "bm25_score": 4.5,
        },
        {
            "citation_key": "paperB",
            "section": "Intro",
            "text": "lexical-only match",
            "score": 0.016,
            "bm25_score": 2.1,
        },
    ]

    with patch("paper_rag.cli.load_config"), patch(
        "paper_rag.cli._open_index", return_value=(_FakeBackend(), object(), object())
    ), patch("paper_rag.cli.hybrid_search", return_value=results):
        cmd_search(argparse.Namespace(config=None, query="q", k=5, paper=None))

    out = capsys.readouterr().out
    assert "vector_distance=0.1200" in out
    assert "bm25_score=4.5000" in out
    assert "bm25_score=2.1000" in out
    # paperB has no vector_distance — must not print a stale/leftover value for it.
    paperb_line = next(line for line in out.splitlines() if "paperB" in line)
    assert "vector_distance" not in paperb_line
