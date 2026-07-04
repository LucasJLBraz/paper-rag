from unittest.mock import Mock, patch

import pytest
import requests

from paper_rag.acquire import semantic_scholar


def _response(status_code, data=None, headers=None):
    r = Mock()
    r.status_code = status_code
    r.headers = headers or {}
    r.json.return_value = {"data": data or []}
    r.raise_for_status.side_effect = requests.exceptions.HTTPError(response=r) if status_code >= 400 else None
    return r


def test_search_succeeds_without_retry():
    with patch("paper_rag.acquire.semantic_scholar.requests.get", return_value=_response(200, [{"title": "A"}])):
        results = semantic_scholar.search("query")

    assert results[0]["title"] == "A"


def test_search_retries_on_429_then_succeeds(monkeypatch):
    responses = [_response(429, headers={"Retry-After": "0"}), _response(200, [{"title": "B"}])]

    def fake_get(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(semantic_scholar, "time", Mock(sleep=Mock()))
    with patch("paper_rag.acquire.semantic_scholar.requests.get", side_effect=fake_get):
        results = semantic_scholar.search("query")

    assert results[0]["title"] == "B"
    semantic_scholar.time.sleep.assert_called_once()


def test_search_raises_after_exhausting_429_retries(monkeypatch):
    monkeypatch.setattr(semantic_scholar, "time", Mock(sleep=Mock()))
    with patch(
        "paper_rag.acquire.semantic_scholar.requests.get",
        return_value=_response(429, headers={"Retry-After": "0"}),
    ):
        with pytest.raises(requests.exceptions.HTTPError):
            semantic_scholar.search("query")
