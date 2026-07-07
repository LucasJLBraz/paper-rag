from unittest.mock import patch

from paper_rag.acquire import get


def _hit(**overrides):
    base = {
        "title": "A Great Paper",
        "authors": ["Jane Smith"],
        "year": 2024,
        "doi": "10.1/xyz",
        "pdf_url": "https://example.com/a.pdf",
        "source": "semantic_scholar",
        "abstract": "some abstract",
    }
    base.update(overrides)
    return base


def test_downloads_directly_when_pdf_url_present(tmp_path):
    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"):
        result = get.download_candidate(
            _hit(),
            contact_email="test@example.com",
            papers_dir=tmp_path / "papers",
            root=tmp_path,
            citation_key=None,
            fallback_title="query text",
        )

    assert result["status"] == "ok"
    assert result["source"] == "semantic_scholar"
    assert (tmp_path / "papers" / f"{result['citation_key']}.pdf").exists()
    assert (tmp_path / "papers" / f"{result['citation_key']}.md").exists()


def test_lazily_resolves_via_unpaywall_when_no_direct_pdf_url(tmp_path):
    hit = _hit(pdf_url=None)
    with patch(
        "paper_rag.acquire.get.unpaywall.resolve",
        return_value={"pdf_url": "https://oa.example.com/a.pdf", "license": None},
    ), patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4") as fetch:
        result = get.download_candidate(
            hit,
            contact_email="test@example.com",
            papers_dir=tmp_path / "papers",
            root=tmp_path,
            citation_key=None,
            fallback_title="query text",
        )

    assert result["status"] == "ok"
    assert result["source"] == "unpaywall"
    fetch.assert_called_once_with("https://oa.example.com/a.pdf")


def test_errors_when_no_pdf_available_anywhere(tmp_path):
    hit = _hit(pdf_url=None, doi=None)

    result = get.download_candidate(
        hit,
        contact_email="test@example.com",
        papers_dir=tmp_path / "papers",
        root=tmp_path,
        citation_key=None,
        fallback_title="query text",
    )

    assert result["status"] == "error"
    assert "No open-access PDF" in result["error"]


def test_errors_when_download_fails(tmp_path):
    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", side_effect=Exception("403 Forbidden")):
        result = get.download_candidate(
            _hit(),
            contact_email="test@example.com",
            papers_dir=tmp_path / "papers",
            root=tmp_path,
            citation_key=None,
            fallback_title="query text",
        )

    assert result["status"] == "error"
    assert "Download failed" in result["error"]


def test_honors_citation_key_override(tmp_path):
    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"):
        result = get.download_candidate(
            _hit(),
            contact_email="test@example.com",
            papers_dir=tmp_path / "papers",
            root=tmp_path,
            citation_key="mykey2024",
            fallback_title="query text",
        )

    assert result["citation_key"] == "mykey2024"
    assert (tmp_path / "papers" / "mykey2024.pdf").exists()
