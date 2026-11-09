import argparse
from unittest.mock import patch

from paper_rag.cli import cmd_discover


def _write_config(tmp_path):
    config_path = tmp_path / ".paper-rag.toml"
    config_path.write_text(
        """
[corpus]
papers_dir = "papers"

[index]
dir = ".rag_index"

[acquire]
contact_email = "test@example.com"
"""
    )
    return config_path


def test_discover_prints_numbered_list_and_writes_cache(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    results = [
        {
            "title": "Multilinear SVD for ECG",
            "authors": ["Silva"],
            "year": 2019,
            "doi": "10.1/a",
            "source": "semantic_scholar",
            "relevance": 0.71,
            "has_pdf": True,
        },
        {
            "title": "Tensor decomposition in biomedical signals",
            "authors": ["Kim"],
            "year": 2021,
            "doi": "10.1/b",
            "source": "openalex",
            "relevance": 0.55,
            "has_pdf": False,
        },
    ]

    with patch("paper_rag.acquire.discover.discover", return_value=results):
        cmd_discover(argparse.Namespace(config=str(config_path), query="tensor ecg", limit=10))

    out = capsys.readouterr()
    assert "[1] (relevance=0.71, OA: yes)  Multilinear SVD for ECG" in out.out
    assert "[2] (relevance=0.55, OA: no)  Tensor decomposition in biomedical signals" in out.out
    assert "Silva, 2019" in out.out
    assert "paper-rag get" in out.err
    assert (tmp_path / ".rag_index" / "discover_cache.json").exists()


def test_discover_prints_truncated_abstract_snippet_when_present(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    long_abstract = "This paper explores tensor decomposition. " * 10
    results = [
        {
            "title": "Multilinear SVD for ECG",
            "authors": ["Silva"],
            "year": 2019,
            "doi": "10.1/a",
            "source": "semantic_scholar",
            "relevance": 0.71,
            "has_pdf": True,
            "abstract": long_abstract,
        },
    ]

    with patch("paper_rag.acquire.discover.discover", return_value=results):
        cmd_discover(argparse.Namespace(config=str(config_path), query="tensor ecg", limit=10))

    out = capsys.readouterr().out
    assert long_abstract[:240] in out
    assert "..." in out
    # must not print the full (untruncated) abstract
    assert long_abstract.strip() not in out


def test_discover_omits_abstract_line_when_missing(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    results = [
        {
            "title": "Multilinear SVD for ECG",
            "authors": ["Silva"],
            "year": 2019,
            "doi": "10.1/a",
            "source": "semantic_scholar",
            "relevance": 0.71,
            "has_pdf": True,
        },
    ]

    with patch("paper_rag.acquire.discover.discover", return_value=results):
        cmd_discover(argparse.Namespace(config=str(config_path), query="tensor ecg", limit=10))

    out = capsys.readouterr().out
    assert "None" not in out


def test_discover_reports_no_results(tmp_path, capsys):
    config_path = _write_config(tmp_path)

    with patch("paper_rag.acquire.discover.discover", return_value=[]):
        cmd_discover(argparse.Namespace(config=str(config_path), query="nothing matches", limit=10))

    out = capsys.readouterr()
    assert "No results found" in out.err


def test_discover_prints_duplicate_line_for_a_candidate_seen_in_an_earlier_run(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    shared = {
        "title": "Shared Paper",
        "authors": ["Kim"],
        "year": 2021,
        "doi": "10.1/shared",
        "source": "openalex",
        "relevance": 0.6,
        "has_pdf": True,
    }

    with patch("paper_rag.acquire.discover.discover", return_value=[shared]):
        cmd_discover(argparse.Namespace(config=str(config_path), query="axis A", limit=10))
    capsys.readouterr()  # discard first run's output

    with patch("paper_rag.acquire.discover.discover", return_value=[dict(shared)]):
        cmd_discover(argparse.Namespace(config=str(config_path), query="axis B", limit=10))

    out = capsys.readouterr().out
    assert "DUPLICATE" in out
    assert "already seen as [1]" in out
    assert "Shared Paper" in out
