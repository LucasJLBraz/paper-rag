from paper_rag.acquire.dedup import natural_key


def test_prefers_normalized_doi_over_title():
    assert natural_key({"doi": "https://doi.org/10.1000/Xyz", "title": "Anything"}) == "doi:10.1000/xyz"


def test_falls_back_to_normalized_title_when_doi_missing():
    assert natural_key({"doi": None, "title": "  Multilinear   SVD for ECG  "}) == "title:multilinear svd for ecg"


def test_returns_none_when_both_doi_and_title_are_missing():
    assert natural_key({"doi": None, "title": ""}) is None
    assert natural_key({}) is None
