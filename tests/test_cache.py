import json

import pytest

from paper_rag.acquire import cache


def test_append_then_read_round_trip(tmp_path):
    index_dir = tmp_path / ".rag_index"
    results = [
        {"title": "Paper One", "doi": "10.1/a", "relevance": 0.9},
        {"title": "Paper Two", "doi": "10.1/b", "relevance": 0.5},
    ]

    annotated = cache.append_cache(index_dir, "my query", results)
    cached = cache.read_cache(index_dir)

    assert [h["id"] for h in annotated] == [1, 2]
    assert cache.get_result(cached, 1)["title"] == "Paper One"
    assert cache.get_result(cached, 2)["title"] == "Paper Two"
    assert cache.get_result(cached, 1)["query"] == "my query"


def test_get_result_returns_none_for_unknown_id(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.append_cache(index_dir, "q", [{"title": "Only One"}])
    cached = cache.read_cache(index_dir)

    assert cache.get_result(cached, 99) is None


def test_ids_from_an_earlier_call_stay_valid_after_a_later_call(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.append_cache(index_dir, "first query", [{"title": "Old Result", "doi": "10.1/old"}])
    cache.append_cache(index_dir, "second query", [{"title": "New Result", "doi": "10.1/new"}])

    cached = cache.read_cache(index_dir)

    assert cache.get_result(cached, 1)["title"] == "Old Result"
    assert cache.get_result(cached, 2)["title"] == "New Result"


def test_a_hit_seen_in_an_earlier_call_comes_back_compact_with_duplicate_of_id(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.append_cache(index_dir, "axis A", [{"title": "Shared Paper", "doi": "10.1/shared", "abstract": "long text"}])
    second = cache.append_cache(index_dir, "axis B", [{"title": "Shared Paper", "doi": "10.1/shared", "abstract": "long text"}])

    assert second == [{"id": 1, "title": "Shared Paper", "duplicate_of_id": 1}]
    # No second slot was created in the persisted cache.
    cached = cache.read_cache(index_dir)
    assert cached["next_id"] == 2


def test_dedup_matches_on_normalized_title_when_doi_missing(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.append_cache(index_dir, "axis A", [{"title": "  Some Title  ", "doi": None}])
    second = cache.append_cache(index_dir, "axis B", [{"title": "some title", "doi": None}])

    assert second[0]["duplicate_of_id"] == 1


def test_hits_with_neither_doi_nor_title_are_never_treated_as_duplicates(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.append_cache(index_dir, "axis A", [{"title": "", "doi": None}])
    second = cache.append_cache(index_dir, "axis B", [{"title": "", "doi": None}])

    assert "duplicate_of_id" not in second[0]
    assert second[0]["id"] == 2


def test_read_cache_raises_clear_error_when_missing(tmp_path):
    index_dir = tmp_path / ".rag_index"

    with pytest.raises(cache.CacheMissError, match="paper-rag discover"):
        cache.read_cache(index_dir)


def test_append_cache_treats_old_schema_file_as_absent(tmp_path):
    # Regression test: the design spec promises an old-format file (single
    # top-level "query" + flat "results" keyed "1".."N", no "queries"/
    # "next_id"/"seen_keys") is "ignored/overwritten on the next `discover`
    # call" rather than crashing. Assert append_cache succeeds and starts
    # fresh (new hit gets id 1), proving the old file wasn't partially
    # merged into the new schema.
    index_dir = tmp_path / ".rag_index"
    index_dir.mkdir(parents=True)
    (index_dir / "discover_cache.json").write_text(
        json.dumps({"query": "old", "results": {"1": {"title": "Old Paper"}}})
    )

    annotated = cache.append_cache(index_dir, "new query", [{"title": "New Paper", "doi": "10.1/new"}])

    assert annotated == [{"title": "New Paper", "doi": "10.1/new", "id": 1}]
    cached = cache.read_cache(index_dir)
    assert cache.get_result(cached, 1)["title"] == "New Paper"


def test_append_cache_treats_corrupt_json_file_as_absent(tmp_path):
    # Same fallback as above, but for a genuinely corrupt/truncated file
    # (json.JSONDecodeError) rather than a parseable-but-old-schema one.
    index_dir = tmp_path / ".rag_index"
    index_dir.mkdir(parents=True)
    (index_dir / "discover_cache.json").write_text("{not valid json")

    annotated = cache.append_cache(index_dir, "new query", [{"title": "New Paper", "doi": "10.1/new"}])

    assert annotated[0]["id"] == 1


def test_append_cache_treats_wrong_typed_keys_as_absent(tmp_path):
    # Regression test: a mangled file that has all the right top-level
    # keys but wrong-typed values (e.g. "seen_keys" as a list instead of
    # a dict) used to pass the presence-only check in `_load()` and then
    # crash in `append_cache()` on `cache["seen_keys"].get(...)`.
    index_dir = tmp_path / ".rag_index"
    index_dir.mkdir(parents=True)
    (index_dir / "discover_cache.json").write_text(
        json.dumps({"next_id": 1, "queries": [], "seen_keys": [], "results": {}})
    )

    annotated = cache.append_cache(index_dir, "new query", [{"title": "New Paper", "doi": "10.1/new"}])

    assert annotated == [{"title": "New Paper", "doi": "10.1/new", "id": 1}]


def test_read_cache_raises_clear_error_for_old_schema_file(tmp_path):
    # Regression test: `read_cache()` used to blindly `json.loads()` the
    # file, so an old-schema or corrupt cache reached by `get`/`get_paper`
    # (without an intervening `append_cache()` call) crashed with
    # KeyError/JSONDecodeError instead of the same clear CacheMissError
    # `append_cache()` already recovers from.
    index_dir = tmp_path / ".rag_index"
    index_dir.mkdir(parents=True)
    (index_dir / "discover_cache.json").write_text(
        json.dumps({"query": "old", "results": {"1": {"title": "Old Paper"}}})
    )

    with pytest.raises(cache.CacheMissError, match="paper-rag discover"):
        cache.read_cache(index_dir)


def test_read_cache_raises_clear_error_for_corrupt_json(tmp_path):
    index_dir = tmp_path / ".rag_index"
    index_dir.mkdir(parents=True)
    (index_dir / "discover_cache.json").write_text("{not valid json")

    with pytest.raises(cache.CacheMissError, match="paper-rag discover"):
        cache.read_cache(index_dir)
