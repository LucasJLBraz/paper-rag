from paper_rag.acquire.relevance import relevance


def test_relevance_is_high_for_matching_title_and_low_for_unrelated_match():
    query = "permutation feature importance guided LLM tabular augmentation"
    good_hit = {"title": "Permutation feature importance for tabular LLM augmentation", "abstract": ""}
    bad_hit = {"title": "Accurate predictions with a tabular foundation model", "abstract": "permutation invariant"}

    assert relevance(query, good_hit) > 0.5
    assert relevance(query, bad_hit) < 0.5


def test_relevance_is_one_for_empty_query():
    assert relevance("", {"title": "anything", "abstract": ""}) == 1.0


def test_relevance_handles_missing_abstract_field():
    assert relevance("some query terms", {"title": "some query terms"}) == 1.0
