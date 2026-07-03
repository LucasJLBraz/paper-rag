# Changelog

## 0.1.0

Initial release.

- PDF -> markdown -> section-aware chunking -> local embeddings -> LanceDB index.
- Pluggable embedding backends: sentence-transformers (default, `BAAI/bge-m3`) or Ollama.
- Open-access acquisition chain: Semantic Scholar -> OpenAlex -> Unpaywall-by-DOI.
- `paper-rag` CLI: `init`, `build`, `search`, `acquire`.
- `paper-rag-mcp`: MCP stdio server exposing `search_papers` / `list_indexed_papers`.
- `paper-rag init` one-shot configures a target repo (`.paper-rag.toml`, `.mcp.json`, Claude Code skill).
