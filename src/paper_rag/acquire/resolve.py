"""Fallback chain for finding a legally open-access PDF for a query.

Order: Semantic Scholar (often has a direct OA PDF link already) -> if only
a DOI, resolve via Unpaywall -> repeat against OpenAlex. Returns candidates
in priority order rather than stopping at the first hit — a resolved
pdf_url can still fail to download (a publisher blocking scripted access
even on an otherwise-legitimate OA record), so the caller can fall through
to the next candidate for the same query instead of giving up outright.
"""
from __future__ import annotations

import sys

import requests

from . import openalex, semantic_scholar, unpaywall
from .relevance import relevance as _relevance

_MAX_CANDIDATES = 5

# `acquire` matches by title/DOI, not topic — it has no real relevance
# ranking, just "first hit with a pdf_url." A candidate that shares few of
# the query's meaningful terms with its own title/abstract is worth
# flagging to the caller even though it can't be proven wrong outright (see
# resolve() below and cli.py's warning on the returned "relevance" field).
RELEVANCE_WARN_THRESHOLD = 0.5


def _safe(fn, *args, default=None, **kwargs):
    # Each source is a separate free public API (Semantic Scholar's
    # unauthenticated tier rate-limits aggressively in particular) -- a
    # 429/5xx/timeout from one must fall through to the next source, not
    # take down the whole acquire command.
    try:
        return fn(*args, **kwargs)
    except requests.RequestException as e:
        source = fn.__module__.rsplit(".", 1)[-1]
        print(f"  ({source} lookup failed, skipping: {e})", file=sys.stderr)
        return default


def find_oa_pdf_candidates(query: str, contact_email: str, s2_api_key: str = "") -> list[dict]:
    """Up to _MAX_CANDIDATES OA-PDF candidates, best source first, each with
    a `source` and `relevance` field attached."""
    candidates: list[dict] = []

    def _collect(hits, source_name: str) -> None:
        for hit in hits:
            if len(candidates) >= _MAX_CANDIDATES:
                return
            if hit.get("pdf_url"):
                candidates.append({**hit, "source": source_name, "relevance": _relevance(query, hit)})
            elif hit.get("doi"):
                oa = _safe(unpaywall.resolve, hit["doi"], contact_email)
                if oa:
                    candidates.append(
                        {**hit, "pdf_url": oa["pdf_url"], "source": "unpaywall", "relevance": _relevance(query, hit)}
                    )

    _collect(_safe(semantic_scholar.search, query, api_key=s2_api_key, limit=3, default=[]), "semantic_scholar")
    if len(candidates) < _MAX_CANDIDATES:
        _collect(_safe(openalex.search, query, contact_email, limit=3, default=[]), "openalex")

    return candidates


def find_oa_pdf(query: str, contact_email: str, s2_api_key: str = "") -> dict | None:
    """Single-hit convenience wrapper — returns the first candidate, if any."""
    candidates = find_oa_pdf_candidates(query, contact_email, s2_api_key)
    return candidates[0] if candidates else None
