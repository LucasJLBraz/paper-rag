"""Download a resolved open-access PDF, with retries."""
from __future__ import annotations

import time

import requests

# A 401/403/404/410 on a specific URL is permanent (publisher blocking
# scripted access, dead link, ...) — retrying the identical URL wastes
# attempts and time. Let the caller (resolve.py's candidate list) move on to
# a different source for the same paper instead.
_PERMANENT_STATUS_CODES = {401, 403, 404, 410}

_PDF_MAGIC = b"%PDF-"


class InvalidPdfContentError(Exception):
    """Raised when a fetch returns HTTP 200 with a body that isn't a real
    PDF — e.g. an anti-bot challenge page or a cookie-wall response served
    in place of the actual file. Treated as permanent for this URL, like
    the codes in _PERMANENT_STATUS_CODES: retrying won't turn an anti-bot
    page into a PDF."""


def fetch_pdf_bytes(pdf_url: str, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(
                pdf_url, timeout=60, headers={"User-Agent": "paper-rag/0.2 (research tool)"}
            )
            r.raise_for_status()
            if r.content[:5] != _PDF_MAGIC:
                content_type = r.headers.get("Content-Type", "unknown")
                raise InvalidPdfContentError(
                    f"Response for {pdf_url} is not a PDF (Content-Type: {content_type}) — "
                    "likely an anti-bot challenge page or a cookie-wall, not the actual paper."
                )
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
