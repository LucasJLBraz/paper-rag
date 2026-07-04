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


def test_find_oa_pdf_candidates_returns_all_hits_in_priority_order():
    with patch(
        "paper_rag.acquire.resolve.semantic_scholar.search",
        return_value=[{"title": "From S2", "pdf_url": "https://example.com/s2.pdf", "doi": None}],
    ), patch(
        "paper_rag.acquire.resolve.openalex.search",
        return_value=[{"title": "From OpenAlex", "pdf_url": "https://example.com/oa.pdf", "doi": None}],
    ):
        candidates = resolve.find_oa_pdf_candidates("From S2", contact_email="test@example.com")

    assert [c["source"] for c in candidates] == ["semantic_scholar", "openalex"]


def test_relevance_is_high_for_matching_title_and_low_for_unrelated_match():
    query = "permutation feature importance guided LLM tabular augmentation"
    good_hit = {"title": "Permutation feature importance for tabular LLM augmentation", "abstract": ""}
    bad_hit = {"title": "Accurate predictions with a tabular foundation model", "abstract": "permutation invariant"}

    good = resolve._relevance(query, good_hit)
    bad = resolve._relevance(query, bad_hit)

    assert good > resolve.RELEVANCE_WARN_THRESHOLD
    assert bad < resolve.RELEVANCE_WARN_THRESHOLD


def test_find_oa_pdf_candidates_attaches_relevance_field():
    with patch(
        "paper_rag.acquire.resolve.semantic_scholar.search",
        return_value=[{"title": "Totally unrelated paper", "pdf_url": "https://example.com/s2.pdf", "doi": None}],
    ), patch("paper_rag.acquire.resolve.openalex.search", return_value=[]):
        [candidate] = resolve.find_oa_pdf_candidates(
            "permutation feature importance guided llm tabular augmentation", contact_email="test@example.com"
        )

    assert candidate["relevance"] < resolve.RELEVANCE_WARN_THRESHOLD


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
