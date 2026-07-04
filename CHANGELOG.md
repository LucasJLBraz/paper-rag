# Changelog

## 0.3.2

- Fix: `paper-rag search` (the CLI) never actually printed the raw `vector_distance`/`bm25_score` fields added in 0.2.0 — they were only wired into `hybrid_search`'s return value and the MCP `search_papers` tool output, not the CLI's own print statement. The fused `score` alone was still all a CLI user ever saw. Now prints whichever of `vector_distance`/`bm25_score` are present per result, plus a one-line explanation of which direction is "better" for each (lower vector_distance, higher bm25_score).

## 0.3.1

- Fix: added `pandas` as an explicit dependency. `ingest/index.py`, `search.py`, and `mcp_server.py` all call `.to_pandas()` on LanceDB query results, but nothing in `pyproject.toml` declared it — `lancedb` itself doesn't depend on it either. Worked by accident wherever pandas happened to already be installed; on a genuinely clean `pipx install`, `search`/`search_papers`/`list_indexed_papers` (anything hitting a non-empty table) crashed with `ModuleNotFoundError: No module named 'pandas'`. `build` on an empty/new index could appear to succeed since the affected code path is skipped for a 0-row table.

## 0.3.0

`acquire` reliability fixes from a live-usage assessment's follow-up (topic-level discovery was flagged as weaker than search; these narrow that gap without turning `acquire` into a discovery tool).

- Fix: `acquire` no longer blindly trusts the first hit with a `pdf_url`. It now collects up to 5 ranked candidates from Semantic Scholar/OpenAlex/Unpaywall, and if a candidate's PDF fails to download (e.g. a publisher blocking scripted access on an otherwise-legitimate OA record), falls through to the next candidate for the same query instead of giving up outright.
- Fix: `acquire` now prints a low-confidence warning when the matched title/abstract shares few terms with the query, since it matches by title/DOI and has no real relevance ranking — this is the same failure mode that let a vague topical query silently match an unrelated paper.
- Fix: `download.fetch_pdf_bytes` no longer retries a permanent 401/403/404/410 against the same URL 3 times before giving up; it now fails fast on those and only retries transient errors (with backoff).
- Fix: `semantic_scholar.search` now retries once or twice with backoff (honoring `Retry-After`) on a 429 instead of immediately falling through to OpenAlex, since the unauthenticated tier's rate limit cooldown is usually short-lived.
- Docs: SKILL.md now states plainly that `acquire` is a title/DOI resolver, not a topic-discovery tool, and to prefer WebSearch/`arxiv-paper-fetch` for the latter.

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
