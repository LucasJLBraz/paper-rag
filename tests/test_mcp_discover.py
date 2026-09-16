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


def test_discover_papers_ids_stay_valid_across_later_calls(tmp_path, monkeypatch):
    # Regression test for the real failure mode: a long MCP session makes
    # many discover_papers() calls across different topical axes, and each
    # one used to invalidate every earlier call's ids.
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    with patch(
        "paper_rag.acquire.discover.discover",
        return_value=[{"title": "Axis A Paper", "doi": "10.1/a", "authors": [], "year": 2020, "source": "semantic_scholar", "relevance": 0.8, "has_pdf": True, "pdf_url": "https://ex.com/axis-a.pdf"}],
    ):
        first = mcp_server.discover_papers("axis A query")

    with patch(
        "paper_rag.acquire.discover.discover",
        return_value=[{"title": "Axis B Paper", "doi": "10.1/b", "authors": [], "year": 2021, "source": "openalex", "relevance": 0.7, "has_pdf": True, "pdf_url": "https://ex.com/axis-b.pdf"}],
    ):
        mcp_server.discover_papers("axis B query")

    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"):
        out = mcp_server.get_paper([first[0]["id"]])

    assert out[0]["status"] == "ok"


def test_discover_papers_compacts_a_candidate_already_seen_in_an_earlier_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    shared_hit = {
        "title": "Shared Paper",
        "doi": "10.1/shared",
        "authors": ["Jane"],
        "year": 2022,
        "source": "semantic_scholar",
        "relevance": 0.6,
        "has_pdf": True,
        "abstract": "a long abstract that should not be repeated",
    }
    with patch("paper_rag.acquire.discover.discover", return_value=[shared_hit]):
        first = mcp_server.discover_papers("axis A query")

    # Build a genuinely separate dict for the second call (not the same
    # object kept alive), so this exercises real cross-call comparison
    # rather than something that would also pass if dedup were keyed by
    # object identity.
    shared_hit_again = dict(shared_hit)
    with patch("paper_rag.acquire.discover.discover", return_value=[shared_hit_again]):
        second = mcp_server.discover_papers("axis B query")

    assert second == [{"id": first[0]["id"], "title": "Shared Paper", "duplicate_of_id": first[0]["id"]}]


def test_get_paper_downloads_by_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    from paper_rag.acquire import cache as cache_mod

    cache_mod.append_cache(
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

    cache_mod.append_cache(
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


def test_get_paper_reports_invalid_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    from paper_rag.acquire import cache as cache_mod
    from paper_rag.acquire.download import InvalidPdfContentError

    cache_mod.append_cache(
        tmp_path / ".rag_index",
        "some query",
        [{"title": "Paper One", "authors": [], "year": 2024, "doi": "10.1/a", "pdf_url": "https://ex.com/a.pdf", "source": "semantic_scholar", "abstract": ""}],
    )

    with patch(
        "paper_rag.acquire.get.download.fetch_pdf_bytes",
        side_effect=InvalidPdfContentError("Response is not a PDF (Content-Type: text/html)"),
    ):
        out = mcp_server.get_paper([1])

    assert out[0]["status"] == "invalid_content"


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
