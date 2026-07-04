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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
