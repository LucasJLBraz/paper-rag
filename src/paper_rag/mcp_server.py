"""MCP stdio server exposing the local paper index as native Claude Code tools.

Registered per-repo via .mcp.json (see `paper-rag init`). Run manually with:
    paper-rag-mcp
"""
from __future__ import annotations

from .config import load_config
from .ingest.embed import build_backend
from .ingest.index import PaperIndex
from .search import hybrid_search

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("paper-rag")

# Lazily built on first tool call rather than at process start: constructing
# the SentenceTransformer backend triggers HuggingFace Hub HEAD requests
# (~8-10s even with a warm local cache), and until that's done the process
# can't respond to any MCP request — including the initial handshake. If the
# client's patience window for a first response is shorter than that load
# time, the symptom is a transport-level "Connected" that never lists tools.
_state: dict = {}


def _get_index():
    if "index" not in _state:
        cfg = load_config()
        backend = build_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.ollama_host)
        index = PaperIndex(cfg.root / cfg.index.dir, cfg.index.table_name, backend.dim, backend.name)
        table = index.open_or_create()
        _state["backend"] = backend
        _state["index"] = index
        _state["table"] = table
    else:
        # A separate `paper-rag build` (CLI) process may have committed new
        # rows since this table handle was opened; checkout_latest() is a
        # local, no-network call that points it at the newest version
        # without paying the embedding backend's construction cost again.
        _state["table"].checkout_latest()
    return _state["backend"], _state["index"], _state["table"]


@mcp.tool()
def search_papers(query: str, k: int = 5, citation_key: str | None = None) -> list[dict]:
    """Hybrid (dense + BM25) search over the local paper corpus.

    Returns up to k ranked chunks, each with citation_key, section, text,
    and score (higher = more relevant). Pass citation_key to restrict the
    search to one paper.
    """
    backend, index, table = _get_index()
    [vector] = backend.embed([query], is_query=True)
    results = hybrid_search(index, table, query, vector, k=k, citation_key=citation_key)
    return [
        {
            "citation_key": r["citation_key"],
            "section": r["section"],
            "text": r["text"],
            "score": r["score"],
            "vector_distance": r.get("vector_distance"),
            "bm25_score": r.get("bm25_score"),
        }
        for r in results
    ]


@mcp.tool()
def list_indexed_papers() -> list[str]:
    """List citation_keys currently present in the local vector index."""
    _, _, table = _get_index()
    df = table.to_pandas()
    return sorted(df["citation_key"].unique().tolist()) if len(df) else []


@mcp.tool()
def discover_papers(query: str, limit: int = 10) -> list[dict]:
    """Topical search across Semantic Scholar + OpenAlex (not a title/DOI match).

    Returns up to `limit` ranked candidates, each with title, authors,
    year, doi, source, relevance, has_pdf, and id. Ids are assigned from a
    counter that never resets for this cache file, so an id from an
    earlier discover_papers() call stays valid for get_paper() even after
    later calls — there's no need to re-run discover_papers before
    downloading. A candidate already surfaced by an earlier call in this
    cache (same doi, or same normalized title when doi is absent) comes
    back compact — just {id, title, duplicate_of_id} pointing at its
    original id — instead of repeating its full metadata/abstract. Note
    that repeat queries can rank differently between calls: this reflects
    live upstream API state (Semantic Scholar/OpenAlex), not a local bug.
    """
    cfg = load_config()
    from .acquire import cache, discover

    results = discover.discover(query, cfg.acquire.contact_email, cfg.acquire.semantic_scholar_api_key, limit=limit)
    index_dir = cfg.root / cfg.index.dir
    return cache.append_cache(index_dir, query, results)


@mcp.tool()
def get_paper(ids: list[int], citation_key: str | None = None) -> list[dict]:
    """Download one or more discover_papers() candidates by id.

    citation_key is only honored for a single id. Returns one dict per
    requested id: {id, status: "ok"|"error"|"invalid_content", citation_key,
    pdf_path, source, error}. "invalid_content" means the download
    succeeded but the response wasn't a real PDF (e.g. an anti-bot
    challenge page or cookie-wall) — no file was written for that id.
    """
    cfg = load_config()
    from .acquire import cache, get as get_mod

    ids = list(dict.fromkeys(ids))

    if citation_key and len(ids) > 1:
        return [{"id": i, "status": "error", "error": "citation_key can only be used with a single id"} for i in ids]

    index_dir = cfg.root / cfg.index.dir
    try:
        cached = cache.read_cache(index_dir)
    except cache.CacheMissError as e:
        return [{"id": i, "status": "error", "error": str(e)} for i in ids]

    papers_dir = cfg.root / cfg.corpus.papers_dir
    out = []
    for result_id in ids:
        hit = cache.get_result(cached, result_id)
        if hit is None:
            out.append({"id": result_id, "status": "error", "error": "no such id in the discover cache"})
            continue
        result = get_mod.download_candidate(
            hit,
            contact_email=cfg.acquire.contact_email,
            papers_dir=papers_dir,
            root=cfg.root,
            citation_key=citation_key,
            fallback_title=hit.get("query", ""),
        )
        out.append({"id": result_id, **result})
    return out


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
