"""Fallback chain for finding a legally open-access PDF for a query.

Order: Semantic Scholar (often has a direct OA PDF link already) -> if only
a DOI, resolve via Unpaywall -> repeat against OpenAlex. Returns candidates
in priority order rather than stopping at the first hit — a resolved
pdf_url can still fail to download (a publisher blocking scripted access
even on an otherwise-legitimate OA record), so the caller can fall through
to the next candidate for the same query instead of giving up outright.
"""
from __future__ import annotations

import re
import sys

import requests

from . import arxiv, crossref, openalex, semantic_scholar, unpaywall
from .relevance import relevance as _relevance

_MAX_CANDIDATES = 5

# `acquire` matches by title, not topic. A keyword search always returns
# *something*, so a candidate whose title holds less than this fraction of
# the query's terms is treated as a different paper: cli.py writes nothing
# for it unless the user passes --accept-low-confidence (#5). Scored on the
# title only: an abstract shares generic terms with almost any query.
ACQUIRE_MIN_RELEVANCE = 0.7

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/\S+)")
_ARXIV_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arxiv[:.])\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)


def parse_identifier(query: str) -> tuple[str, str] | None:
    """("arxiv", id) or ("doi", doi) when the query is an exact identifier
    (bare, prefixed or as a URL), else None. arXiv is checked first because
    arXiv DOIs (10.48550/arXiv.NNNN) also match the DOI pattern."""
    m = _ARXIV_RE.search(query)
    if m:
        return "arxiv", m.group(1)
    m = _DOI_RE.search(query)
    if m:
        return "doi", m.group(1).rstrip(".,;)").removesuffix(".pdf")
    return None


def resolve_exact(kind: str, identifier: str, contact_email: str) -> tuple[dict | None, list[dict]]:
    """(metadata, candidates) for an exact DOI/arXiv id. Never runs a keyword
    search, so it can not substitute another paper. metadata is None when the
    identifier is unknown; candidates is empty when there is no open PDF."""
    if kind == "arxiv":
        meta = arxiv.lookup(identifier)
        return meta, ([{**meta, "source": "arxiv", "relevance": 1.0}] if meta else [])
    meta = crossref.lookup(identifier, contact_email)
    if meta is None:
        return None, []
    urls = _safe(unpaywall.resolve_all, identifier, contact_email, default=[])
    return meta, [{**meta, "pdf_url": u, "source": "unpaywall", "relevance": 1.0} for u in urls]


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
            score = _relevance(query, {"title": hit.get("title")})
            if hit.get("pdf_url"):
                candidates.append({**hit, "source": source_name, "relevance": score})
            elif hit.get("doi"):
                oa = _safe(unpaywall.resolve, hit["doi"], contact_email)
                if oa:
                    candidates.append(
                        {**hit, "pdf_url": oa["pdf_url"], "source": "unpaywall", "relevance": score}
                    )

    _collect(_safe(semantic_scholar.search, query, api_key=s2_api_key, limit=3, default=[]), "semantic_scholar")
    if len(candidates) < _MAX_CANDIDATES:
        _collect(_safe(openalex.search, query, contact_email, limit=3, default=[]), "openalex")

    return candidates


def find_oa_pdf(query: str, contact_email: str, s2_api_key: str = "") -> dict | None:
    """Single-hit convenience wrapper — returns the first candidate, if any."""
    candidates = find_oa_pdf_candidates(query, contact_email, s2_api_key)
    return candidates[0] if candidates else None
