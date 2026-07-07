"""Topical paper search across Semantic Scholar + OpenAlex.

Unlike resolve.py (title/DOI match, picks one candidate to auto-download),
this returns a ranked, deduplicated list of candidates for the caller to
choose from — see cli.py's `discover`/`get` commands and mcp_server.py's
`discover_papers`/`get_paper` tools.
"""
from __future__ import annotations

import re
import sys

import requests

from . import openalex, semantic_scholar
from .relevance import relevance as _relevance

_PER_SOURCE_LIMIT = 8
_DEFAULT_LIMIT = 10
_DOI_PREFIX_RE = re.compile(r"^https?://doi\.org/", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def _safe(fn, *args, default=None, **kwargs):
    # Same fallback philosophy as resolve.py's _safe: a single source's
    # 429/5xx/timeout must not take down the whole discover() call.
    try:
        return fn(*args, **kwargs)
    except requests.RequestException as e:
        source = fn.__module__.rsplit(".", 1)[-1]
        print(f"  ({source} lookup failed, skipping: {e})", file=sys.stderr)
        return default


def _dedup_key(hit: dict) -> str:
    doi = (hit.get("doi") or "").strip()
    if doi:
        return "doi:" + _DOI_PREFIX_RE.sub("", doi).lower()
    title = _WHITESPACE_RE.sub(" ", (hit.get("title") or "").strip().lower())
    return "title:" + title


def discover(query: str, contact_email: str, s2_api_key: str = "", limit: int = _DEFAULT_LIMIT) -> list[dict]:
    """Ranked, deduplicated topical search across sources.

    Each result carries `source`, `relevance`, and `has_pdf` (true only if
    the source API already returned a direct pdf_url — no Unpaywall lookup
    happens here; that's deferred to download time, see get.py).
    """
    hits: list[dict] = []
    seen: set[str] = set()

    def _collect(source_hits, source_name: str) -> None:
        for hit in source_hits:
            key = _dedup_key(hit)
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
