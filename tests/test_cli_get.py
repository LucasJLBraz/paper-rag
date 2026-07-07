import argparse
from unittest.mock import patch

import pytest

from paper_rag.cli import cmd_get


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


def _seed_cache(tmp_path):
    from paper_rag.acquire import cache

    results = [
        {
            "title": "Paper One",
            "authors": ["Jane"],
            "year": 2024,
            "doi": "10.1/a",
            "pdf_url": "https://ex.com/a.pdf",
            "source": "semantic_scholar",
            "abstract": "",
        },
        {
            "title": "Paper Two",
            "authors": ["Jane"],
            "year": 2024,
            "doi": "10.1/b",
            "pdf_url": None,
            "source": "openalex",
            "abstract": "",
        },
    ]
    cache.write_cache(tmp_path / ".rag_index", "some query", results)


def test_get_downloads_multiple_ids_and_reports_summary(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    _seed_cache(tmp_path)

    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"), patch(
        "paper_rag.acquire.get.unpaywall.resolve", return_value=None
    ):
        with pytest.raises(SystemExit):
            cmd_get(argparse.Namespace(config=str(config_path), ids=[1, 2], citation_key=None))

    out = capsys.readouterr()
    assert "[1] Downloaded via semantic_scholar" in out.out
    assert "1 downloaded, 1 failed" in out.err


def test_get_errors_on_unknown_id(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    _seed_cache(tmp_path)

    with pytest.raises(SystemExit):
        cmd_get(argparse.Namespace(config=str(config_path), ids=[99], citation_key=None))

    out = capsys.readouterr()
    assert "No such id in the discover cache" in out.err
    assert "0 downloaded, 1 failed" in out.err


def test_get_rejects_citation_key_with_multiple_ids(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    _seed_cache(tmp_path)

    with pytest.raises(SystemExit):
        cmd_get(argparse.Namespace(config=str(config_path), ids=[1, 2], citation_key="mykey"))

    out = capsys.readouterr()
    assert "single id" in out.err


def test_get_errors_when_no_cache_exists(tmp_path, capsys):
    config_path = _write_config(tmp_path)

    with pytest.raises(SystemExit):
        cmd_get(argparse.Namespace(config=str(config_path), ids=[1], citation_key=None))

    out = capsys.readouterr()
    assert "paper-rag discover" in out.err
