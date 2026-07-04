"""Download a resolved open-access PDF, with retries."""
from __future__ import annotations

import time

import requests

# A 401/403/404/410 on a specific URL is permanent (publisher blocking
# scripted access, dead link, ...) — retrying the identical URL wastes
# attempts and time. Let the caller (resolve.py's candidate list) move on to
# a different source for the same paper instead.
_PERMANENT_STATUS_CODES = {401, 403, 404, 410}


def fetch_pdf_bytes(pdf_url: str, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(
                pdf_url, timeout=60, headers={"User-Agent": "paper-rag/0.2 (research tool)"}
            )
            r.raise_for_status()
            return r.content
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code in _PERMANENT_STATUS_CODES:
                raise
            last_error = e
        except requests.exceptions.RequestException as e:
            last_error = e
        if attempt < attempts:
            time.sleep(attempt)
    assert last_error is not None
    raise last_error
