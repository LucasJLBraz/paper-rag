"""Local, disposable cache of the last `discover()` call's results.

Lets a later `get <id>` (CLI) or `get_paper(ids=[...])` (MCP) reference
exactly what was shown, without re-querying the upstream APIs or risking
the result list changing between the two calls. Lives in the same
disposable, gitignored index directory as manifest.json — each new
`discover` call fully overwrites it.
"""
from __future__ import annotations

import json
from pathlib import Path

_CACHE_FILENAME = "discover_cache.json"


class CacheMissError(Exception):
    pass


def _cache_path(index_dir: Path) -> Path:
    return index_dir / _CACHE_FILENAME


def write_cache(index_dir: Path, query: str, results: list[dict]) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    payload = {"query": query, "results": {str(i + 1): r for i, r in enumerate(results)}}
    _cache_path(index_dir).write_text(json.dumps(payload, indent=2))


def read_cache(index_dir: Path) -> dict:
    path = _cache_path(index_dir)
    if not path.exists():
        raise CacheMissError(
            f'No discover cache found at {path}. Run `paper-rag discover "<query>"` first.'
        )
    return json.loads(path.read_text())


def get_result(cache: dict, result_id: int) -> dict | None:
    return cache["results"].get(str(result_id))
