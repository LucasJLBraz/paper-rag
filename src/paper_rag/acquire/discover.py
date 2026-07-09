"""Topical paper search across Semantic Scholar + OpenAlex.

Unlike resolve.py (title/DOI match, picks one candidate to auto-download),
this returns a ranked, deduplicated list of candidates for the caller to
choose from — see cli.py's `discover`/`get` commands and mcp_server.py's
`discover_papers`/`get_paper` tools.
"""
from __future__ import annotations

import itertools
import sys

import requests

from . import openalex, semantic_scholar
from .dedup import natural_key
from .relevance import relevance as _relevance

_PER_SOURCE_LIMIT = 8
_DEFAULT_LIMIT = 10


def _safe(fn, *args, default=None, **kwargs):
    # Same fallback philosophy as resolve.py's _safe: a single source's
    # 429/5xx/timeout must not take down the whole discover() call.
    try:
        return fn(*args, **kwargs)
    except requests.RequestException as e:
        source = fn.__module__.rsplit(".", 1)[-1]
        print(f"  ({source} lookup failed, skipping: {e})", file=sys.stderr)
        return default


def _dedup_key(hit: dict, fallback_id: int) -> str:
    key = natural_key(hit)
    if key is not None:
        return key
    # Neither doi nor title: fall back to a key unique per hit rather than
    # colliding every such hit onto the same bare "title:" key. fallback_id
    # comes from a counter shared across the whole discover() call, so
    # uniqueness holds by construction regardless of object lifetime.
    return f"unique:{fallback_id}"


def discover(query: str, contact_email: str, s2_api_key: str = "", limit: int = _DEFAULT_LIMIT) -> list[dict]:
    """Ranked, deduplicated topical search across sources.

    Each result carries `source`, `relevance`, and `has_pdf` (true only if
    the source API already returned a direct pdf_url — no Unpaywall lookup
    happens here; that's deferred to download time, see get.py).
    """
    hits: list[dict] = []
    seen: set[str] = set()
    counter = itertools.count()

    def _collect(source_hits, source_name: str) -> None:
        for hit in source_hits:
            key = _dedup_key(hit, next(counter))
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                {**hit, "source": source_name, "relevance": _relevance(query, hit), "has_pdf": bool(hit.get("pdf_url"))}
            )

    _collect(_safe(semantic_scholar.search, query, api_key=s2_api_key, limit=_PER_SOURCE_LIMIT, default=[]), "semantic_scholar")
    _collect(_safe(openalex.search, query, contact_email, limit=_PER_SOURCE_LIMIT, default=[]), "openalex")

    hits.sort(key=lambda h: h["relevance"], reverse=True)
    return hits[:limit]
