import pytest

from paper_rag.acquire import cache


def test_write_then_read_round_trip(tmp_path):
    index_dir = tmp_path / ".rag_index"
    results = [
        {"title": "Paper One", "doi": "10.1/a", "relevance": 0.9},
        {"title": "Paper Two", "doi": "10.1/b", "relevance": 0.5},
    ]

    cache.write_cache(index_dir, "my query", results)
    cached = cache.read_cache(index_dir)

    assert cached["query"] == "my query"
    assert cache.get_result(cached, 1)["title"] == "Paper One"
    assert cache.get_result(cached, 2)["title"] == "Paper Two"


def test_get_result_returns_none_for_unknown_id(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.write_cache(index_dir, "q", [{"title": "Only One"}])
    cached = cache.read_cache(index_dir)

    assert cache.get_result(cached, 99) is None


def test_new_discover_overwrites_previous_cache(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.write_cache(index_dir, "first query", [{"title": "Old Result"}])
    cache.write_cache(index_dir, "second query", [{"title": "New Result"}])

    cached = cache.read_cache(index_dir)

    assert cached["query"] == "second query"
    assert cache.get_result(cached, 1)["title"] == "New Result"


def test_read_cache_raises_clear_error_when_missing(tmp_path):
    index_dir = tmp_path / ".rag_index"

    with pytest.raises(cache.CacheMissError, match="paper-rag discover"):
        cache.read_cache(index_dir)
