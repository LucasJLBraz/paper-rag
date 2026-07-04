"""Semantic Scholar Graph API — search + direct open-access PDF links.

Works without an API key at a low rate limit; pass one via
acquire.semantic_scholar_api_key in .paper-rag.toml to raise it.
"""
from __future__ import annotations

import time

import requests

API = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,authors,year,externalIds,openAccessPdf,abstract"

# The unauthenticated tier 429s aggressively but the cooldown is usually
# short — a bounded retry here means one transient rate limit doesn't
# permanently skip this source for an entire `acquire` call. Once
# exhausted, this still raises and resolve.py's fallback chain moves on to
# OpenAlex/Unpaywall as before.
_MAX_ATTEMPTS = 3
_MAX_BACKOFF_SECONDS = 10.0


def _retry_wait_seconds(retry_after: str | None, attempt: int) -> float:
    if retry_after:
        try:
            return min(float(retry_after), _MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return min(2.0**attempt, _MAX_BACKOFF_SECONDS)


def search(query: str, api_key: str = "", limit: int = 5) -> list[dict]:
    headers = {"x-api-key": api_key} if api_key else {}
    params = {"query": query, "limit": limit, "fields": FIELDS}

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        r = requests.get(API, params=params, headers=headers, timeout=30)
        if r.status_code == 429 and attempt < _MAX_ATTEMPTS:
            time.sleep(_retry_wait_seconds(r.headers.get("Retry-After"), attempt))
            continue
        r.raise_for_status()
        break

    results = []
    for p in r.json().get("data", []):
        oa = p.get("openAccessPdf") or {}
        results.append(
            {
                "title": p.get("title"),
                "doi": (p.get("externalIds") or {}).get("DOI"),
                "authors": [a["name"] for a in p.get("authors", [])],
                "year": p.get("year"),
                "pdf_url": oa.get("url"),
                "abstract": p.get("abstract"),
                "semantic_scholar_id": p.get("paperId"),
            }
        )
    return results
