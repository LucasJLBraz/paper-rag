import argparse
from unittest.mock import patch

from paper_rag.cli import cmd_acquire


def _write_config(tmp_path):
    config_path = tmp_path / ".paper-rag.toml"
    config_path.write_text(
        """
[corpus]
papers_dir = "papers"

[acquire]
contact_email = "test@example.com"
"""
    )
    return config_path


def test_acquire_falls_through_to_next_candidate_on_download_failure(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    candidates = [
        {
            "title": "Blocked by publisher",
            "authors": ["Jane Smith"],
            "year": 2024,
            "doi": None,
            "pdf_url": "https://blocked.example.com/paper.pdf",
            "source": "unpaywall",
            "relevance": 1.0,
        },
        {
            "title": "Actually downloadable",
            "authors": ["Jane Smith"],
            "year": 2024,
            "doi": None,
            "pdf_url": "https://ok.example.com/paper.pdf",
            "source": "openalex",
            "relevance": 1.0,
        },
    ]

    def fake_fetch(pdf_url, *args, **kwargs):
        if "blocked" in pdf_url:
            raise Exception("403 Forbidden")
        return b"%PDF-1.4"

    with patch(
        "paper_rag.acquire.resolve.find_oa_pdf_candidates", return_value=candidates
    ), patch("paper_rag.acquire.download.fetch_pdf_bytes", side_effect=fake_fetch):
        cmd_acquire(argparse.Namespace(config=str(config_path), query="actually downloadable", citation_key=None))

    out = capsys.readouterr()
    assert "trying the next candidate" in out.err
    assert "Actually downloadable" in out.out
    assert (tmp_path / "papers").exists()
    assert len(list((tmp_path / "papers").glob("*.pdf"))) == 1


def test_acquire_warns_on_low_relevance_match(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    candidates = [
        {
            "title": "Totally unrelated paper",
            "authors": ["Jane Smith"],
            "year": 2024,
            "doi": None,
            "pdf_url": "https://ok.example.com/paper.pdf",
            "source": "openalex",
            "relevance": 0.1,
        }
    ]

    with patch(
        "paper_rag.acquire.resolve.find_oa_pdf_candidates", return_value=candidates
    ), patch("paper_rag.acquire.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"):
        cmd_acquire(argparse.Namespace(config=str(config_path), query="some specific topic", citation_key=None))

    out = capsys.readouterr()
    assert "WARNING: low keyword overlap" in out.err
