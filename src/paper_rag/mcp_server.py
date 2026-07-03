"""MCP stdio server exposing the local paper index as native Claude Code tools.

Registered per-repo via .mcp.json (see `paper-rag init`). Run manually with:
    paper-rag-mcp
"""
from __future__ import annotations

from .config import load_config
from .ingest.embed import build_backend
from .ingest.index import PaperIndex

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("paper-rag")


def main() -> None:
    cfg = load_config()
    backend = build_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.ollama_host)
    index = PaperIndex(cfg.root / cfg.index.dir, cfg.index.table_name, backend.dim, backend.name)
    table = index.open_or_create()

    @mcp.tool()
    def search_papers(query: str, k: int = 5, citation_key: str | None = None) -> list[dict]:
        """Semantic search over the local paper corpus.

        Returns up to k ranked chunks, each with citation_key, section, text,
        and distance (lower = more relevant). Pass citation_key to restrict the
        search to one paper.
        """
        [vector] = backend.embed([query])
        results = index.search(table, vector, k=k, citation_key=citation_key)
        return [
            {
                "citation_key": r["citation_key"],
                "section": r["section"],
                "text": r["text"],
                "distance": r["_distance"],
            }
            for r in results
        ]

    @mcp.tool()
    def list_indexed_papers() -> list[str]:
        """List citation_keys currently present in the local vector index."""
        df = table.to_pandas()
        return sorted(df["citation_key"].unique().tolist()) if len(df) else []

    mcp.run()


if __name__ == "__main__":
    main()
