# Changelog

## 0.5.0

`acquire` no longer writes the wrong paper into `papers_dir` (#5).

- `acquire "<DOI>"` resolves the DOI exactly (Crossref metadata, every
  Unpaywall OA location). No keyword search, so no substitute paper. With no
  open PDF, it writes the `.md` metadata only and exits 1.
- `acquire "arXiv:NNNN.NNNNN"` (or an arxiv.org URL / arXiv DOI) downloads from
  arxiv.org with metadata from the arXiv API.
- Title queries: a candidate is accepted only if its title holds at least 70%
  of the query's terms (title only, not the abstract). Otherwise nothing is
  written, the candidates are listed, and the command exits 1.
  `--accept-low-confidence` overrides this.
- Add `paper-rag add <file.pdf> [--doi DOI]` to import a PDF you downloaded
  yourself, with metadata from Crossref.
- SKILL.md and README no longer point to an `arxiv-paper-fetch` skill.
## 0.4.1

- Fix (#4): `paper-rag build` failed on every PDF with
  `AttributeError: module 'pymupdf4llm' has no attribute 'to_markdown'`.
  `pymupdf4llm` 2.x is an empty shim package and `pymupdf` 2.1 does not ship a
  working replacement. Dependencies are now pinned to `pymupdf4llm<2` and
  `pymupdf<2`. Existing pipx installs: `pipx install --force paper-rag` (or
  `pipx inject paper-rag "pymupdf4llm<2" "pymupdf<2" --force`).
- `build` now exits with status 1 and prints `N of M paper(s) failed` when any
  paper fails to ingest, including papers that yield no chunks. Before, the
  index was left stale with exit status 0.
- Add a real (unmocked) PDF conversion smoke test, so a dependency upgrade that
  breaks conversion fails CI.
- `acquire`/`get` reject downloads whose body is not a PDF (`%PDF-`), and
  `build` skips `*.pdf` files that are not PDFs, with a warning.
- MCP `search_papers` reopens the index on each call, so it sees papers indexed
  after the server started.
- `paper_rag.__version__` now matches the package version.

## 0.4.0

Adds the topical-discovery flow that 0.3.0's docs pointed users away from
this tool for.

- Add: `paper-rag discover "<topic>"` (CLI) and `discover_papers` (MCP) —
  a genuine topical search across Semantic Scholar + OpenAlex. Returns a
  ranked, deduplicated, numbered list of candidates (title, authors, year,
  source, relevance, OA availability) instead of auto-picking one, and
  caches the list locally.
- Add: `paper-rag get <id> [<id> ...]` (CLI) and `get_paper` (MCP) —
  downloads one or more candidates from the last `discover` by id,
  resolving via Unpaywall on demand only for the ids actually requested.
- `acquire` is unchanged — it remains the title/DOI resolver for a paper
  you can already name. Docs (README, SKILL.md) now point topical queries
  at `discover`/`get` instead of WebSearch/`arxiv-paper-fetch`.
- `paper-rag discover`'s CLI output now prints a truncated abstract
  snippet (240 chars) under each candidate, when the source API returned
  one — the abstract already flowed through `discover()`/the cache/the
  MCP `discover_papers` tool, but the CLI's own printed list didn't show
  it, leaving title/authors/year as the only signal for picking an id.

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
