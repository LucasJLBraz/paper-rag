from unittest.mock import patch

from paper_rag import mcp_server


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


def test_discover_papers_returns_ids_and_writes_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    results = [
        {
            "title": "Paper One",
            "authors": ["Jane"],
            "year": 2024,
            "doi": "10.1/a",
            "source": "semantic_scholar",
            "relevance": 0.9,
            "has_pdf": True,
        }
    ]

    with patch("paper_rag.acquire.discover.discover", return_value=results):
        out = mcp_server.discover_papers("some query")

    assert out[0]["id"] == 1
    assert out[0]["title"] == "Paper One"
    assert (tmp_path / ".rag_index" / "discover_cache.json").exists()


def test_get_paper_downloads_by_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    from paper_rag.acquire import cache as cache_mod

    cache_mod.write_cache(
        tmp_path / ".rag_index",
        "some query",
        [
            {
                "title": "Paper One",
                "authors": ["Jane"],
                "year": 2024,
                "doi": "10.1/a",
                "pdf_url": "https://ex.com/a.pdf",
                "source": "semantic_scholar",
                "abstract": "",
            }
        ],
    )

    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"):
        out = mcp_server.get_paper([1])

    assert out[0]["status"] == "ok"
    assert (tmp_path / "papers" / f"{out[0]['citation_key']}.pdf").exists()


def test_get_paper_dedupes_duplicate_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    from paper_rag.acquire import cache as cache_mod

    cache_mod.write_cache(
        tmp_path / ".rag_index",
        "some query",
        [
            {
                "title": "Paper One",
                "authors": ["Jane"],
                "year": 2024,
                "doi": "10.1/a",
                "pdf_url": "https://ex.com/a.pdf",
                "source": "semantic_scholar",
                "abstract": "",
            }
        ],
    )

    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4") as fetch_mock:
        out = mcp_server.get_paper([1, 1])

    assert len(out) == 1
    assert fetch_mock.call_count == 1


def test_get_paper_rejects_citation_key_with_multiple_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    out = mcp_server.get_paper([1, 2], citation_key="mykey")

    assert all(r["status"] == "error" for r in out)


def test_get_paper_errors_when_no_cache_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    out = mcp_server.get_paper([1])

    assert out[0]["status"] == "error"
    assert "paper-rag discover" in out[0]["error"]
