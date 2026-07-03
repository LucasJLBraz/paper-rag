"""Download a resolved open-access PDF, with retries."""
from __future__ import annotations

import requests


def fetch_pdf_bytes(pdf_url: str, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(
                pdf_url, timeout=60, headers={"User-Agent": "paper-rag/0.1 (research tool)"}
            )
            r.raise_for_status()
            return r.content
        except requests.exceptions.RequestException as e:
            last_error = e
    assert last_error is not None
    raise last_error
