from unittest.mock import patch

from paper_rag.acquire import openalex


def _fake_response(results):
    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": results}

    return _R()


def test_search_reconstructs_abstract_from_inverted_index():
    inverted_index = {"Deep": [0], "learning": [1], "is": [2], "great": [3]}
    work = {
        "title": "A Paper",
        "doi": "https://doi.org/10.1/abcd",
        "authorships": [],
        "publication_year": 2024,
        "best_oa_location": {"pdf_url": "https://example.com/paper.pdf"},
        "abstract_inverted_index": inverted_index,
        "id": "https://openalex.org/W123",
    }
    with patch("paper_rag.acquire.openalex.requests.get", return_value=_fake_response([work])):
        [result] = openalex.search("a paper", contact_email="test@example.com")

    assert result["abstract"] == "Deep learning is great"


def test_search_abstract_none_when_inverted_index_missing():
    work = {
        "title": "A Paper",
        "doi": None,
        "authorships": [],
        "publication_year": 2024,
        "best_oa_location": {},
        "id": "https://openalex.org/W123",
    }
    with patch("paper_rag.acquire.openalex.requests.get", return_value=_fake_response([work])):
        [result] = openalex.search("a paper", contact_email="test@example.com")

    assert result["abstract"] is None
