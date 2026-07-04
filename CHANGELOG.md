# Changelog

## 0.2.0

Fixes from a live-usage assessment, plus one score-interpretability improvement.

- Fix: `build` now prunes citation_keys whose PDF no longer exists in `papers_dir` from both the LanceDB table and `manifest.json`, on every run (including `--rebuild`). Previously deleted papers' chunks lingered in the index indefinitely.
- Fix: `paper-rag-mcp` now starts serving immediately and defers loading the embedding backend / opening the index to the first tool call, instead of blocking the initial MCP handshake for several seconds.
- Fix: `acquire`'s OpenAlex fallback now reconstructs the abstract from `abstract_inverted_index` instead of always writing an empty one.
- `hybrid_search` / `search_papers` now also return the raw per-method `vector_distance` and `bm25_score` alongside the fused `score`, since the RRF score alone isn't a useful confidence signal.

## 0.1.0

Initial release.

- PDF -> markdown -> section-aware chunking -> local embeddings -> LanceDB index.
- Pluggable embedding backends: sentence-transformers (default, `BAAI/bge-m3`) or Ollama.
- Open-access acquisition chain: Semantic Scholar -> OpenAlex -> Unpaywall-by-DOI.
- `paper-rag` CLI: `init`, `build`, `search`, `acquire`.
- `paper-rag-mcp`: MCP stdio server exposing `search_papers` / `list_indexed_papers`.
- `paper-rag init` one-shot configures a target repo (`.paper-rag.toml`, `.mcp.json`, Claude Code skill).
