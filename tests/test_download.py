from unittest.mock import Mock, patch

import pytest
import requests

from paper_rag.acquire import download


def _response(status_code, content=b"", headers=None):
    r = Mock()
    r.status_code = status_code
    r.content = content
    r.headers = headers or {}
    if status_code >= 400:
        r.raise_for_status.side_effect = requests.exceptions.HTTPError(response=r)
    else:
        r.raise_for_status.side_effect = None
    return r


def test_fetch_pdf_bytes_succeeds_on_first_try():
    with patch("paper_rag.acquire.download.requests.get", return_value=_response(200, b"%PDF-1.4")):
        assert download.fetch_pdf_bytes("https://example.com/paper.pdf") == b"%PDF-1.4"


def test_fetch_pdf_bytes_does_not_retry_permanent_403(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return _response(403)

    monkeypatch.setattr(download, "time", Mock(sleep=Mock()))
    with patch("paper_rag.acquire.download.requests.get", side_effect=fake_get):
        with pytest.raises(requests.exceptions.HTTPError):
            download.fetch_pdf_bytes("https://example.com/paper.pdf", attempts=3)

    assert len(calls) == 1


def test_fetch_pdf_bytes_retries_transient_errors(monkeypatch):
    responses = [requests.exceptions.ConnectionError(), requests.exceptions.ConnectionError(), _response(200, b"ok")]

    def fake_get(*args, **kwargs):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(download, "time", Mock(sleep=Mock()))
    with patch("paper_rag.acquire.download.requests.get", side_effect=fake_get):
        assert download.fetch_pdf_bytes("https://example.com/paper.pdf", attempts=3) == b"ok"
