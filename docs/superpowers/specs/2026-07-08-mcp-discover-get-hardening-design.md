# Design: harden `discover`/`get`/`list_indexed_papers` against real-usage failure modes

Date: 2026-07-08

## Problem

A real literature-review session against this MCP server (~16
`discover_papers` calls, ~20 `get_paper` calls, 3 external `build`s, run
from a separate consuming project and reported back as usage feedback on
2026-07-07/08) surfaced five failure modes in the MCP tools shipped by
[`2026-07-06-discover-get-design.md`](2026-07-06-discover-get-design.md):

1. **`discover_papers` IDs are not stable across calls.** The cache file
   (`discover_cache.json`) is a single slot that each new `discover` call
   fully overwrites — this was an explicit non-goal of the original design
   ("no cross-call cache accumulation... concurrent discover calls... not a
   supported scenario"), but a single long MCP conversation naturally makes
   many `discover_papers` calls across different topical axes, and any call
   after the first invalidates every earlier call's ids. The user's only
   defensive option was to re-run `discover_papers` immediately before each
   `get_paper`, roughly doubling tool calls and re-printing full abstracts
   already read once.
2. **Ranking/order is not deterministic across identical queries.** Confirmed
   not to be a bug in `relevance()` (pure function of query + hit) — it's
   upstream API drift (Semantic Scholar/OpenAlex) — but it's undocumented,
   so callers can't tell the difference between "the tool is flaky" and
   "the world changed" without being told.
3. **`get_paper` reports `status: "ok"` for anti-bot/cookie-wall HTML
   served with HTTP 200.** No validation that downloaded bytes are actually
   a PDF before writing the file and reporting success. Discovered only
   later via `paper-rag build`'s opaque "no chunks extracted", requiring
   manual `file`/`head -c` forensics per suspect file.
4. **`list_indexed_papers` (MCP) serves stale data after an external
   `paper-rag build` (CLI).** The MCP server opens the LanceDB table once
   and caches the handle for the process lifetime; it doesn't see rows
   added by a separate CLI process's `build` run.
5. **No dedup of candidates across separate `discover_papers` calls.**
   Same root cause as #1 (cache is a single overwritten slot, so there's no
   record of what was already surfaced) — repeated/adjacent topical queries
   return the same paper again, and the caller must manually notice by
   reading titles/abstracts.

This design revises the "no cross-call cache accumulation" non-goal from the
original spec — real usage showed a single MCP session reliably makes it
false — and adds the missing content validation and index-freshness
guarantees.

## Goals

- `discover_papers`/`get_paper` ids stay valid for the lifetime of the
  cache file, regardless of how many intervening `discover_papers` calls
  happen (in the same or a later process) — no forced re-query before
  download.
- A candidate already surfaced by an earlier `discover_papers` call (same
  DOI, or same normalized title when DOI is absent) is reported compactly
  on a later call instead of repeating its full abstract/authors payload.
- `get_paper` never reports `status: "ok"` for content that isn't actually
  a PDF, and never leaves a non-PDF file behind under `papers_dir`.
- MCP tools that read the vector index (`search_papers`,
  `list_indexed_papers`) always reflect the latest `paper-rag build`,
  whether that build ran in the same MCP process or a separate CLI
  invocation.
- Docstrings make the non-deterministic-ranking behavior (#2) and the
  duplicate/id semantics (#1, #5) explicit, so callers don't have to
  rediscover them by trial and error.

## Non-goals

- No automatic pruning/expiry of `discover_cache.json` — it's small,
  git-ignored, and disposable; unbounded growth across a project's
  lifetime is an accepted trade-off, not solved here.
- No dedup against the *already-indexed corpus* (citation keys already
  downloaded/built) — scope is limited to dedup across `discover_papers`
  calls within the same cache file, matching the feedback's #5 exactly.
- No retry-on-invalid-content in `download.py` — an anti-bot/cookie-wall
  response is treated as permanent for that URL (same philosophy already
  used for 401/403/404/410), not transient.
- No change to `discover.py`'s existing per-call, cross-source dedup
  (Semantic Scholar vs. OpenAlex within one `discover()` call) — that
  logic and its `itertools.count()`-based fallback key (see
  [[feedback-id-based-dedup-keys]]) are reused as-is by the new
  cross-call layer, not replaced.

## Architecture

### `acquire/cache.py` — cumulative cache with global ids and cross-call dedup

New on-disk schema for `discover_cache.json`:

```json
{
  "next_id": 9,
  "queries": ["query A", "query B"],
  "seen_keys": {"doi:10.1/a": 1, "title:some normalized title": 2},
  "results": {"1": {"...hit fields...": "...", "query": "query A"}, "2": {}}
}
```

- `next_id` is a monotonic counter that only ever increases — persisted in
  the file, so it survives both across `discover_papers` calls within one
  MCP process and across separate CLI process invocations.
- `seen_keys` maps the same dedup key scheme as `discover.py`'s
  `_dedup_key` (normalized DOI, else normalized title) to the id that first
  claimed it.
- `results` holds one full hit per *newly seen* candidate, keyed by id
  (string, matching the existing `get_result` lookup contract).

Replace `write_cache` with:

```python
def append_cache(index_dir: Path, query: str, results: list[dict]) -> list[dict]:
    ...
```

For each hit in `results` (already ranked by `discover.discover()`):
- Compute its dedup key via the same normalization `discover.py` uses
  (extract `_dedup_key`'s doi/title normalization into a shared helper in
  `acquire/relevance.py` or a small new `acquire/dedup.py`, imported by
  both `discover.py` and `cache.py`, so the two don't drift).
- If the key is already in `seen_keys`: emit `{"id": <existing id>,
  "title": hit.get("title"), "duplicate_of_id": <existing id>}` — no new
  slot is created, no abstract/authors/etc. is included.
- Else: assign `id = next_id`, increment `next_id`, store the full hit
  (plus `"query": query` for provenance) in `results[str(id)]`, register
  `seen_keys[key] = id`.

Write the updated cache back to disk and return the annotated list in the
same order `discover()` produced, for the caller (`mcp_server.py`,
`cli.py`) to return/print directly — this also removes the redundant
second `enumerate(results, start=1)` currently duplicated in
`cli.cmd_discover`.

`get_result(cache, result_id)` keeps its current signature, now reading
from the new `results` sub-dict (already how it reads today —
`cache["results"].get(str(result_id))` needs no change).

### `acquire/discover.py` / `mcp_server.py` / `cli.py` — docstrings

- `discover_papers` (MCP) and `cmd_discover`/`cmd_get` (CLI): document that
  ids are stable and cumulative for the life of the cache file; that
  candidates already seen in an earlier call come back compact with
  `duplicate_of_id`; and that identical queries can rank differently
  between calls because they reflect live upstream API state, not a local
  bug.
- `cache.py` module docstring: replace "each new discover call fully
  overwrites it" with the new cumulative/append behavior.

### `acquire/download.py` — magic-byte validation

```python
class InvalidPdfContentError(Exception):
    pass
```

In `fetch_pdf_bytes`, after `r.raise_for_status()` succeeds: check
`r.content[:5] == b"%PDF-"`. If not, raise `InvalidPdfContentError` with a
message including the response's `Content-Type` header (helps distinguish
"anti-bot HTML" from other unexpected content at a glance). This is treated
like the existing `_PERMANENT_STATUS_CODES` — no retry, since a repeat
request against the same anti-bot wall won't succeed.

### `acquire/get.py` — surface `invalid_content` as its own status

In `download_candidate`, add a dedicated `except InvalidPdfContentError as
e` branch (before the existing generic `except Exception` around the fetch
call) returning `{"status": "invalid_content", "error": str(e)}`. Nothing
is written to `papers_dir` in this path — the existing code already only
writes after a successful fetch, so this just needs the new exception type
to short-circuit before that point.

### `mcp_server.py` / `cli.py` — surface the new status

- `get_paper` docstring: `status: "ok"|"error"|"invalid_content"`.
- `cmd_get` (CLI): `invalid_content` counts as a failure (same branch as
  today's `else`, which already just prints `result["error"]` — no code
  change needed there, only the docstring/help text mentioning the new
  status value).

### `mcp_server.py` — index freshness

`_get_index()` keeps caching `backend`/`index`/`table` in `_state` (the
expensive part — constructing the `SentenceTransformer` backend — must stay
cached), but calls `_state["table"].checkout_latest()` (LanceDB's built-in,
local, no-network call to point the table handle at the latest committed
version) every time `_get_index()` is called, before returning. This
applies uniformly to every tool that reads the index — `search_papers` and
`list_indexed_papers` — so neither can serve stale data after an external
`paper-rag build`.

## Error handling

- `append_cache` performs one read + one write of a small local JSON file;
  no new failure modes beyond what `write_cache` already had (parent dir
  creation, disk write).
- `InvalidPdfContentError` is caught at the same boundary
  (`download_candidate`) that already catches network/IO errors for this
  candidate — a batch of ids in `get_paper`/`cmd_get` still reports
  per-item results without one bad candidate aborting the rest.
- `checkout_latest()` failure modes (e.g. corrupted table) are not
  specially handled — they'd surface the same way any other LanceDB read
  error does today.

## Testing

`tests/test_mcp_discover.py`:
- Update existing tests that call `cache.write_cache` directly to use
  `cache.append_cache`.
- New: two `discover_papers` calls with different queries, second one
  returning a hit with the same DOI as one from the first — assert the
  second call's matching entry has `duplicate_of_id` equal to the first
  call's id for that hit, has no `abstract`/`authors` keys, and that
  `get_paper` with the *first* call's id still succeeds after the second
  call (proves ids survive across calls, not just within one — the actual
  bug from the feedback report).
- New: same scenario via two separate `append_cache` calls hitting the
  *same object* for the duplicate (following the
  [[feedback-id-based-dedup-keys]] lesson — a test using genuinely
  separate dict instances per call, not objects kept alive across the
  simulated calls, so it would fail against a naive re-`id()`-based
  implementation if one were mistakenly reintroduced).

New `tests/test_download.py`:
- `fetch_pdf_bytes` raises `InvalidPdfContentError` when the mocked
  response body is HTML.
- `download_candidate` returns `status: "invalid_content"` and does not
  create a `pdf_path`/`.md` file when the fetch raises
  `InvalidPdfContentError`.

`tests/test_mcp_discover.py` (or a new `tests/test_mcp_index_refresh.py`):
- `list_indexed_papers` reflects rows added to the LanceDB table *after*
  `_get_index()` was first called in the test process (simulating an
  external `build`) — using a real temp LanceDB table, not a mock, so
  `checkout_latest()` is exercised for real.

## Migration notes

- `discover_cache.json`'s schema changes; old-format files (single `query`
  + flat `results` keyed `"1".."N"`) are not migrated — the file is
  disposable and git-ignored, so a stale one is simply ignored/overwritten
  on the next `discover` call. No explicit migration code.
