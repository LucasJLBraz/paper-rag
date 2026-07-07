# Design: `discover` + `get` — topical paper search and multi-download

Date: 2026-07-06

## Problem

`paper-rag acquire "<query>"` only matches by title/DOI: it auto-downloads
the first open-access candidate whose keyword overlap with the query is
high enough, and its own CLI output explicitly warns that topical/discovery
searches should go elsewhere (WebSearch, arxiv-paper-fetch). There is no
way today to run a topical query (e.g. "tensor decomposition multilinear
SVD ECG atrial fibrillation feature extraction"), see a ranked list of
matching papers, and then choose one or more to download.

## Goals

- A topic-style free-text search that returns a ranked list of candidate
  papers (title, authors, year, source, DOI, relevance score, OA
  availability) — not just the single best guess.
- A follow-up step that downloads one or more chosen items from that list
  by ID, without re-querying the upstream APIs.
- Works identically from the CLI and from Claude Code via MCP tools, since
  both are first-class ways this tool gets used.
- `acquire` stays untouched — it remains the "I know the exact
  title/DOI" flow.

## Non-goals

- No interactive terminal prompt/menu (breaks the MCP/agent path, which has
  no interactive stdin).
- No cross-call cache accumulation — each `discover` overwrites the
  previous cache. Concurrent `discover` calls in different terminals are
  not a supported scenario for this local, single-user tool.
- No eager Unpaywall resolution for every candidate during `discover` —
  only at `get` time, for the specific item(s) requested.

## Architecture

### New module: `acquire/discover.py`

- `discover(query: str, contact_email: str, s2_api_key: str = "", limit: int = 10) -> list[dict]`
- Queries `semantic_scholar.search` and `openalex.search` with a wider
  per-source limit than `resolve.py` uses today (e.g. 8 each) — these are
  genuinely topical queries, not title lookups.
- Deduplicates across sources: same normalized DOI (lowercased, stripped
  of the `https://doi.org/` prefix) is a duplicate; if either side lacks a
  DOI, fall back to normalized title (lowercased, whitespace-collapsed).
  First occurrence wins (Semantic Scholar is queried first, so it takes
  priority on a duplicate).
- Reuses the existing `_relevance()` keyword-overlap function from
  `resolve.py` (moved to a shared location, e.g. `acquire/relevance.py`,
  and imported by both `resolve.py` and `discover.py`) to score and sort
  results, highest relevance first.
- Truncates to `limit` results.
- Each returned dict gets a `has_pdf: bool` field (true if `pdf_url` is
  already present from the source API — no Unpaywall call at this stage).

### New module: `acquire/cache.py`

- `write_cache(index_dir: Path, query: str, results: list[dict]) -> None`
  — writes `discover_cache.json` inside the existing disposable index
  directory (already gitignored, same directory as `manifest.json`).
  Assigns sequential integer IDs (1..N) to the results as stored.
- `read_cache(index_dir: Path) -> dict` — returns the cached payload
  (`{"query": ..., "results": {id: {...}, ...}}`), or raises a clear
  `FileNotFoundError`-derived error if no cache exists yet.
- Each `discover` call fully overwrites the file (no accumulation).

### CLI (`cli.py`)

- `paper-rag discover "<query>" [--limit N]` (default `limit=10`)
  - Calls `discover()`, writes the cache, prints a numbered list:
    `[id] (relevance=X.XX, OA: yes|no)  Title` then a line with
    `Authors, Year — source — doi: ...`.
  - Footer line pointing at `paper-rag get <id> [<id> ...]`.
- `paper-rag get <id> [<id> ...] [--citation-key KEY]`
  - `--citation-key` is only valid with exactly one ID (error otherwise).
  - Reads the cache; for each requested ID:
    - Unknown ID → per-item error, continue with the rest.
    - `has_pdf` false but a DOI is present → lazily try
      `unpaywall.resolve()` at this point (not during `discover`).
    - No resolvable PDF → per-item error (says so plainly, suggests
      manual download), continue with the rest.
    - Otherwise downloads via the existing `download.fetch_pdf_bytes` +
      `metadata.write_metadata` path (same citation-key generation logic
      `acquire` already uses).
  - Prints a per-item result line as it goes, then a one-line summary
    (`N downloaded, M failed`) at the end. Exits non-zero if at least one
    requested ID failed.

### MCP (`mcp_server.py`)

- `discover_papers(query: str, limit: int = 10) -> list[dict]` — same
  underlying call + cache write, returns the same structured list (with
  `id` included) so the agent can present it and pick from it.
- `get_paper(ids: list[int], citation_key: str | None = None) -> list[dict]`
  — same validation/lazy-resolve/download logic as the CLI `get`, returns
  one result dict per requested ID (`{"id":, "status": "ok"|"error",
  "citation_key":, "pdf_path":, "error":}`).

## Data flow example

```
$ paper-rag discover "tensor decomposition multilinear SVD ECG atrial fibrillation feature extraction"
[1] (relevance=0.71, OA: yes)  Multilinear SVD-based feature extraction for ECG classification
    Silva et al., 2019 — semantic_scholar — doi: 10.xxxx/...
[2] (relevance=0.55, OA: no)   Tensor decomposition methods in biomedical signal processing
    Kim et al., 2021 — openalex — doi: 10.yyyy/...
...
Cached 8 result(s) -> <index_dir>/discover_cache.json
Run `paper-rag get <id> [<id> ...]` to download one or more (only "OA: yes" is guaranteed downloadable; others are resolved on demand).

$ paper-rag get 1 2
[1] Downloaded via semantic_scholar: papers/silva2019multilinear.pdf
[2] Downloaded via unpaywall: papers/kim2021tensor.pdf
2 downloaded, 0 failed
```

## Error handling

- `discover`: no results from either source → clear message, non-fatal
  exit; a single source failing (429/timeout/etc.) does not prevent the
  other source's results from being shown (same fallback philosophy as
  `resolve.py`).
- `get`: missing/empty cache → error telling the user to run `discover`
  first; unknown ID(s), unresolvable PDF(s) → per-item errors that don't
  abort the rest of the batch; `--citation-key` with multiple IDs → hard
  error before doing any downloads.

## Testing

- `discover.py`: dedup by DOI and by normalized title, relevance scoring/
  sorting, `limit` truncation, per-source failure fallback.
- `cache.py`: write/read round-trip, ID lookup, overwrite-on-new-`discover`
  behavior, missing-cache error.
- CLI: `discover` output formatting; `get` with multiple IDs (mixed
  success/failure), invalid ID handling, `--citation-key` + multi-ID
  rejection.
- MCP: `discover_papers` / `get_paper` covered analogously to the existing
  `test_mcp`/`search_papers` tests.
