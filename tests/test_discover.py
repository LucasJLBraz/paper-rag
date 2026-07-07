from unittest.mock import patch

import requests

from paper_rag.acquire import discover


def test_dedups_by_normalized_doi_keeping_first_source():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search",
        return_value=[
            {"title": "Paper A", "doi": "10.1000/Xyz", "pdf_url": "https://s2.example.com/a.pdf", "abstract": ""}
        ],
    ), patch(
        "paper_rag.acquire.discover.openalex.search",
        return_value=[
            {"title": "Paper A (OpenAlex copy)", "doi": "https://doi.org/10.1000/xyz", "pdf_url": None, "abstract": ""}
        ],
    ):
        results = discover.discover("paper a", contact_email="test@example.com")

    assert len(results) == 1
    assert results[0]["source"] == "semantic_scholar"


def test_dedups_by_normalized_title_when_doi_missing():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search",
        return_value=[{"title": "  Multilinear SVD for ECG  ", "doi": None, "pdf_url": "https://s2.example.com/a.pdf", "abstract": ""}],
    ), patch(
        "paper_rag.acquire.discover.openalex.search",
        return_value=[{"title": "multilinear svd for ecg", "doi": None, "pdf_url": None, "abstract": ""}],
    ):
        results = discover.discover("multilinear svd ecg", contact_email="test@example.com")

    assert len(results) == 1


def test_sorts_by_relevance_descending():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search",
        return_value=[
            {"title": "Totally unrelated paper", "doi": "10.1/a", "pdf_url": "https://s2.example.com/a.pdf", "abstract": ""},
            {
                "title": "tensor decomposition multilinear SVD ECG atrial fibrillation",
                "doi": "10.1/b",
                "pdf_url": "https://s2.example.com/b.pdf",
                "abstract": "",
            },
        ],
    ), patch("paper_rag.acquire.discover.openalex.search", return_value=[]):
        results = discover.discover(
            "tensor decomposition multilinear SVD ECG atrial fibrillation feature extraction",
            contact_email="test@example.com",
        )

    assert [r["doi"] for r in results] == ["10.1/b", "10.1/a"]


def test_truncates_to_limit():
    hits = [
        {"title": f"Paper {i}", "doi": f"10.1/{i}", "pdf_url": "https://s2.example.com/x.pdf", "abstract": ""}
        for i in range(5)
    ]
    with patch("paper_rag.acquire.discover.semantic_scholar.search", return_value=hits), patch(
        "paper_rag.acquire.discover.openalex.search", return_value=[]
    ):
        results = discover.discover("paper", contact_email="test@example.com", limit=2)

    assert len(results) == 2


def test_has_pdf_flag_reflects_direct_pdf_url_only():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search",
        return_value=[{"title": "With PDF", "doi": "10.1/a", "pdf_url": "https://s2.example.com/a.pdf", "abstract": ""}],
    ), patch(
        "paper_rag.acquire.discover.openalex.search",
        return_value=[{"title": "Without PDF", "doi": "10.1/b", "pdf_url": None, "abstract": ""}],
    ):
        results = discover.discover("paper", contact_email="test@example.com")

    by_doi = {r["doi"]: r["has_pdf"] for r in results}
    assert by_doi["10.1/a"] is True
    assert by_doi["10.1/b"] is False


def test_hits_missing_both_doi_and_title_are_not_collapsed_together():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search",
        return_value=[{"title": "", "doi": None, "pdf_url": "https://s2.example.com/a.pdf", "abstract": ""}],
    ), patch(
        "paper_rag.acquire.discover.openalex.search",
        return_value=[{"doi": None, "pdf_url": "https://oa.example.com/b.pdf", "abstract": ""}],
    ):
        results = discover.discover("some query", contact_email="test@example.com")

    assert len(results) == 2


def test_dedup_fallback_key_is_unique_across_separate_source_hit_lists():
    # Regression test for the id()-collision bug: the dedup fallback key used
    # to be f"unique:{id(hit)}". Each source's hit list is only referenced
    # inline during its own _collect(...) call in discover(), so once the
    # first source's list is done being iterated, CPython is free to reuse
    # its freed memory for the second source's hit dicts -- meaning two
    # genuinely distinct doi/title-less hits from *different* source calls
    # could get the same id() and collapse into one result.
    #
    # These two dicts are built as entirely separate objects returned from
    # two separate mock .search() calls (semantic_scholar's list is fully
    # consumed by _collect before openalex.search is even invoked), so this
    # exercises the real "list goes out of scope between sources" pattern
    # rather than relying on both lists staying alive together for the
    # duration of the test. With the counter-based fallback, uniqueness is
    # guaranteed by construction rather than by id()/lifetime luck.
    s2_hit = {"title": "", "doi": None, "pdf_url": "https://s2.example.com/a.pdf", "abstract": ""}
    openalex_hit = {"title": "", "doi": None, "pdf_url": "https://oa.example.com/b.pdf", "abstract": ""}

    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search",
        return_value=[s2_hit],
    ), patch(
        "paper_rag.acquire.discover.openalex.search",
        return_value=[openalex_hit],
    ):
        results = discover.discover("some query", contact_email="test@example.com")

    assert len(results) == 2
    assert {r["source"] for r in results} == {"semantic_scholar", "openalex"}


def test_dedup_key_fallback_uses_the_given_id_not_object_identity():
    # Direct, low-level proof that the fallback key derives from fallback_id
    # rather than from object identity. This calls _dedup_key twice on the
    # *same* dict object with two different fallback_id values: if the
    # implementation still used id(hit) internally, both calls would return
    # the identical key (same object => same id()) and this would fail. It
    # only passes because uniqueness genuinely comes from the counter value
    # threaded through discover(), not from id()/object-lifetime luck --
    # unlike test_dedup_fallback_key_is_unique_across_separate_source_hit_lists
    # above, which keeps both hit dicts alive for the whole test and so would
    # have passed against the old, buggy id(hit) implementation too.
    hit = {"doi": None, "title": ""}
    assert discover._dedup_key(hit, 0) != discover._dedup_key(hit, 1)


def test_one_source_failing_does_not_abort_the_other():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search", side_effect=requests.HTTPError("429 rate limited")
    ), patch(
        "paper_rag.acquire.discover.openalex.search",
        return_value=[{"title": "Found via OpenAlex", "doi": "10.1/a", "pdf_url": "https://oa.example.com/a.pdf", "abstract": ""}],
    ):
        results = discover.discover("some query", contact_email="test@example.com")

    assert len(results) == 1
    assert results[0]["source"] == "openalex"
