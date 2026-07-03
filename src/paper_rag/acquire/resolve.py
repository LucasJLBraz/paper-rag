"""Fallback chain for finding a legally open-access PDF for a query.

Order: Semantic Scholar (often has a direct OA PDF link already) -> if only
a DOI, resolve via Unpaywall -> repeat against OpenAlex. Stops at the first
hit with a usable pdf_url.
"""
from __future__ import annotations

import sys

import requests

from . import openalex, semantic_scholar, unpaywall


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


def find_oa_pdf(query: str, contact_email: str, s2_api_key: str = "") -> dict | None:
    for hit in _safe(semantic_scholar.search, query, api_key=s2_api_key, limit=3, default=[]):
        if hit.get("pdf_url"):
            return {**hit, "source": "semantic_scholar"}
        if hit.get("doi"):
            oa = _safe(unpaywall.resolve, hit["doi"], contact_email)
            if oa:
                return {**hit, "pdf_url": oa["pdf_url"], "source": "unpaywall"}

    for hit in _safe(openalex.search, query, contact_email, limit=3, default=[]):
        if hit.get("pdf_url"):
            return {**hit, "source": "openalex"}
        if hit.get("doi"):
            oa = _safe(unpaywall.resolve, hit["doi"], contact_email)
            if oa:
                return {**hit, "pdf_url": oa["pdf_url"], "source": "unpaywall"}

    return None
