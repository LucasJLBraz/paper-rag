"""Cumulative cache of `discover()` candidates, for this cache file's
lifetime (one MCP server process, or a CLI "session" spanning separate
`discover`/`get` invocations that share the same index directory).

Lets a later `get <id>` (CLI) or `get_paper(ids=[...])` (MCP) reference
exactly what was shown, without re-querying the upstream APIs. Ids come
from a counter that only ever grows — a new `discover` call never resets
or overwrites it — so an id handed out by an earlier call stays valid
after later calls. A hit that matches (by normalized doi, else normalized
title — see acquire/dedup.py) one already in the cache is reported back
compactly, pointing at its existing id, instead of being stored again.
Lives in the same disposable, gitignored index directory as manifest.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from .dedup import natural_key

_CACHE_FILENAME = "discover_cache.json"


class CacheMissError(Exception):
    pass


def _cache_path(index_dir: Path) -> Path:
    return index_dir / _CACHE_FILENAME


def _load(index_dir: Path) -> dict:
    path = _cache_path(index_dir)
    if not path.exists():
        return {"next_id": 1, "queries": [], "seen_keys": {}, "results": {}}
    return json.loads(path.read_text())


def _save(index_dir: Path, cache: dict) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(index_dir).write_text(json.dumps(cache, indent=2))


def append_cache(index_dir: Path, query: str, results: list[dict]) -> list[dict]:
    """Merge `results` (from one `discover()` call) into the persistent
    cache; return the annotated list to show/return to the caller.

    Each hit gets a fresh id the first time its doi/title is seen. A hit
    that matches an id already in the cache is replaced with a compact
    `{"id", "title", "duplicate_of_id"}` entry instead — full metadata is
    stored at most once per genuinely new candidate.
    """
    cache = _load(index_dir)
    cache["queries"].append(query)

    annotated = []
    for hit in results:
        key = natural_key(hit)
        existing_id = cache["seen_keys"].get(key) if key is not None else None
        if existing_id is not None:
            annotated.append({"id": existing_id, "title": hit.get("title"), "duplicate_of_id": existing_id})
            continue

        result_id = cache["next_id"]
        cache["next_id"] += 1
        cache["results"][str(result_id)] = {**hit, "query": query}
        if key is not None:
            cache["seen_keys"][key] = result_id
        annotated.append({**hit, "id": result_id})

    _save(index_dir, cache)
    return annotated


def read_cache(index_dir: Path) -> dict:
    path = _cache_path(index_dir)
    if not path.exists():
        raise CacheMissError(
            f'No discover cache found at {path}. Run `paper-rag discover "<query>"` first.'
        )
    return json.loads(path.read_text())


def get_result(cache: dict, result_id: int) -> dict | None:
    return cache["results"].get(str(result_id))
