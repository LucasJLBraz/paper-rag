from unittest.mock import patch

import requests

from paper_rag.acquire import resolve


def test_falls_through_to_openalex_when_semantic_scholar_errors():
    with patch(
        "paper_rag.acquire.resolve.semantic_scholar.search",
        side_effect=requests.HTTPError("429 rate limited"),
    ), patch(
        "paper_rag.acquire.resolve.openalex.search",
        return_value=[{"title": "Found via OpenAlex", "pdf_url": "https://example.com/paper.pdf", "doi": None}],
    ):
        hit = resolve.find_oa_pdf("some query", contact_email="test@example.com")

    assert hit is not None
    assert hit["source"] == "openalex"
    assert hit["title"] == "Found via OpenAlex"


def test_returns_none_when_all_sources_error():
    with patch(
        "paper_rag.acquire.resolve.semantic_scholar.search", side_effect=requests.ConnectionError()
    ), patch("paper_rag.acquire.resolve.openalex.search", side_effect=requests.Timeout()):
        assert resolve.find_oa_pdf("some query", contact_email="test@example.com") is None


def test_unpaywall_error_on_one_hit_does_not_abort_the_search():
    with patch(
        "paper_rag.acquire.resolve.semantic_scholar.search",
        return_value=[{"title": "No PDF, DOI errors", "pdf_url": None, "doi": "10.1/bad"}],
    ), patch(
        "paper_rag.acquire.resolve.unpaywall.resolve", side_effect=requests.HTTPError("500")
    ), patch(
        "paper_rag.acquire.resolve.openalex.search",
        return_value=[{"title": "Found via OpenAlex", "pdf_url": "https://example.com/paper.pdf", "doi": None}],
    ):
        hit = resolve.find_oa_pdf("some query", contact_email="test@example.com")

    assert hit is not None
    assert hit["source"] == "openalex"
