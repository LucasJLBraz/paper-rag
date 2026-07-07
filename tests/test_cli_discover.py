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


def test_discover_reports_no_results(tmp_path, capsys):
    config_path = _write_config(tmp_path)

    with patch("paper_rag.acquire.discover.discover", return_value=[]):
        cmd_discover(argparse.Namespace(config=str(config_path), query="nothing matches", limit=10))

    out = capsys.readouterr()
    assert "No results found" in out.err
