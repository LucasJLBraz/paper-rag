# MCP discover/get hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the five failure modes a real literature-review session surfaced in paper-rag's `discover_papers`/`get_paper` MCP tools: unstable ids, undocumented ranking non-determinism, silent false-positive "ok" downloads of non-PDF content, a stale `list_indexed_papers` after external builds, and no cross-call duplicate detection.

**Architecture:** `acquire/cache.py`'s `discover_cache.json` moves from a single-slot, overwrite-on-every-call file to a cumulative one with a monotonic global id counter and a doi/title dedup index (`seen_keys`), shared by both the CLI (`discover`/`get`) and the MCP tools (`discover_papers`/`get_paper`). A new `acquire/dedup.py` centralizes the doi/title normalization already used inside `discover.py`'s per-call dedup, so `cache.py`'s cross-call dedup can't drift from it. `acquire/download.py` gains magic-byte validation so a non-PDF HTTP 200 response raises a distinct `InvalidPdfContentError` instead of being silently saved. `mcp_server.py`'s index-reading tools call LanceDB's `checkout_latest()` before every read so they never serve data older than the last `paper-rag build`, from any process.

**Tech Stack:** Python 3.12, pytest, LanceDB (`lancedb>=0.15`, actually pinned to 0.34.0 in the dev venv), `requests`, FastMCP (`mcp` package).

## Global Constraints

- No new third-party dependencies — everything here uses the stdlib, `requests`, and `lancedb`, all already in use.
- Follow the existing "never raise, return `{"status": ..., "error": ...}`" contract in `acquire/get.py::download_candidate` — batch operations (`get_paper`, `cmd_get`) must keep reporting per-item results without one bad candidate aborting the rest.
- No backward-compatibility shims for the old `discover_cache.json` schema or the old `cache.write_cache` name — it's a disposable, git-ignored file and an internal API with two callers, both fixed in this plan (see spec's Migration notes).
- Every new/changed status value, id-stability guarantee, and dedup behavior gets documented in the relevant tool/command docstring — this whole feature exists because prior behavior was undocumented and cost a real session ~10s of thousands of wasted tokens.

Spec: `docs/superpowers/specs/2026-07-08-mcp-discover-get-hardening-design.md`

---

## Task 1: Shared doi/title normalization (`acquire/dedup.py`)

**Files:**
- Create: `src/paper_rag/acquire/dedup.py`
- Modify: `src/paper_rag/acquire/discover.py:1-49`
- Test: `tests/test_dedup.py` (new)

**Interfaces:**
- Produces: `dedup.natural_key(hit: dict) -> str | None` — `"doi:<normalized doi>"` if `hit["doi"]` is truthy after stripping; else `"title:<normalized title>"` if `hit["title"]` is truthy after stripping; else `None`. Used by Task 2 (`cache.py`) and by `discover.py`'s existing `_dedup_key`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dedup.py`:

```python
from paper_rag.acquire.dedup import natural_key


def test_prefers_normalized_doi_over_title():
    assert natural_key({"doi": "https://doi.org/10.1000/Xyz", "title": "Anything"}) == "doi:10.1000/xyz"


def test_falls_back_to_normalized_title_when_doi_missing():
    assert natural_key({"doi": None, "title": "  Multilinear   SVD for ECG  "}) == "title:multilinear svd for ecg"


def test_returns_none_when_both_doi_and_title_are_missing():
    assert natural_key({"doi": None, "title": ""}) is None
    assert natural_key({}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dedup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paper_rag.acquire.dedup'`

- [ ] **Step 3: Create `acquire/dedup.py`**

```python
"""Shared "is this the same paper" normalization.

Used by discover.py's within-call, cross-source dedup (Semantic Scholar
vs. OpenAlex) and cache.py's cross-call dedup (this discover_papers() call
vs. everything already in discover_cache.json) — kept in one place so the
two can't quietly drift apart.
"""
from __future__ import annotations

import re

_DOI_PREFIX_RE = re.compile(r"^https?://doi\.org/", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def natural_key(hit: dict) -> str | None:
    """Normalized doi (preferred) or title key for `hit`, or None if it has
    neither. Callers decide what "no natural key" means for their own
    fallback: discover.py assigns a per-call-unique key (two hits with no
    identifying info can't be proven to be the same paper, but also
    shouldn't collide onto the same bogus key); cache.py treats it as
    always-new for the same reason."""
    doi = (hit.get("doi") or "").strip()
    if doi:
        return "doi:" + _DOI_PREFIX_RE.sub("", doi).lower()
    title = _WHITESPACE_RE.sub(" ", (hit.get("title") or "").strip().lower())
    if title:
        return "title:" + title
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dedup.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Point `discover.py` at the shared helper**

In `src/paper_rag/acquire/discover.py`, remove the now-duplicated `import re` and the two module-level regexes, and rewrite `_dedup_key` to delegate:

Replace:
```python
import itertools
import re
import sys

import requests

from . import openalex, semantic_scholar
from .relevance import relevance as _relevance

_PER_SOURCE_LIMIT = 8
_DEFAULT_LIMIT = 10
_DOI_PREFIX_RE = re.compile(r"^https?://doi\.org/", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
```
with:
```python
import itertools
import sys

import requests

from . import openalex, semantic_scholar
from .dedup import natural_key
from .relevance import relevance as _relevance

_PER_SOURCE_LIMIT = 8
_DEFAULT_LIMIT = 10
```

Replace:
```python
def _dedup_key(hit: dict, fallback_id: int) -> str:
    doi = (hit.get("doi") or "").strip()
    if doi:
        return "doi:" + _DOI_PREFIX_RE.sub("", doi).lower()
    title = _WHITESPACE_RE.sub(" ", (hit.get("title") or "").strip().lower())
    if title:
        return "title:" + title
    # Neither doi nor title: fall back to a key unique per hit rather than
    # colliding every such hit onto the same bare "title:" key. fallback_id
    # comes from a counter shared across the whole discover() call, so
    # uniqueness holds by construction regardless of object lifetime.
    return f"unique:{fallback_id}"
```
with:
```python
def _dedup_key(hit: dict, fallback_id: int) -> str:
    key = natural_key(hit)
    if key is not None:
        return key
    # Neither doi nor title: fall back to a key unique per hit rather than
    # colliding every such hit onto the same bare "title:" key. fallback_id
    # comes from a counter shared across the whole discover() call, so
    # uniqueness holds by construction regardless of object lifetime.
    return f"unique:{fallback_id}"
```

- [ ] **Step 6: Run the full discover test suite to confirm no regression**

Run: `pytest tests/test_discover.py tests/test_dedup.py -v`
Expected: PASS (all tests, including the existing `test_dedup_key_fallback_uses_the_given_id_not_object_identity` and `test_dedup_fallback_key_is_unique_across_separate_source_hit_lists`, which exercise `_dedup_key` unchanged)

- [ ] **Step 7: Commit**

```bash
git add src/paper_rag/acquire/dedup.py src/paper_rag/acquire/discover.py tests/test_dedup.py
git commit -m "Extract doi/title dedup normalization into acquire/dedup.py"
```

---

## Task 2: Cumulative cache with global ids and cross-call dedup (`acquire/cache.py`)

**Files:**
- Modify: `src/paper_rag/acquire/cache.py` (full rewrite)
- Modify: `tests/test_cache.py` (full rewrite)
- Modify: `tests/test_cli_get.py:26-49` (`_seed_cache` helper)

**Interfaces:**
- Consumes: `dedup.natural_key(hit: dict) -> str | None` (Task 1).
- Produces:
  - `cache.append_cache(index_dir: Path, query: str, results: list[dict]) -> list[dict]` — replaces `write_cache`. Returns the same list `results` came in as, in the same order, with each item either annotated with a fresh `"id"` (new candidate) or replaced by a compact `{"id", "title", "duplicate_of_id"}` dict (candidate already in the cache under the same doi/title).
  - `cache.read_cache(index_dir: Path) -> dict` — unchanged signature; internal schema changes (see below), still raises `CacheMissError` if the file doesn't exist.
  - `cache.get_result(cache: dict, result_id: int) -> dict | None` — unchanged signature; the returned hit now also carries a `"query"` key (the query that first surfaced it), consumed by Task 5/6 as the new `fallback_title`.
  - `cache.CacheMissError` — unchanged.

New on-disk schema for `discover_cache.json`:
```json
{
  "next_id": 3,
  "queries": ["query A", "query B"],
  "seen_keys": {"doi:10.1/a": 1, "title:some normalized title": 2},
  "results": {"1": {"...hit fields...": "...", "query": "query A"}, "2": {}}
}
```

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_cache.py` entirely with:

```python
import pytest

from paper_rag.acquire import cache


def test_append_then_read_round_trip(tmp_path):
    index_dir = tmp_path / ".rag_index"
    results = [
        {"title": "Paper One", "doi": "10.1/a", "relevance": 0.9},
        {"title": "Paper Two", "doi": "10.1/b", "relevance": 0.5},
    ]

    annotated = cache.append_cache(index_dir, "my query", results)
    cached = cache.read_cache(index_dir)

    assert [h["id"] for h in annotated] == [1, 2]
    assert cache.get_result(cached, 1)["title"] == "Paper One"
    assert cache.get_result(cached, 2)["title"] == "Paper Two"
    assert cache.get_result(cached, 1)["query"] == "my query"


def test_get_result_returns_none_for_unknown_id(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.append_cache(index_dir, "q", [{"title": "Only One"}])
    cached = cache.read_cache(index_dir)

    assert cache.get_result(cached, 99) is None


def test_ids_from_an_earlier_call_stay_valid_after_a_later_call(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.append_cache(index_dir, "first query", [{"title": "Old Result", "doi": "10.1/old"}])
    cache.append_cache(index_dir, "second query", [{"title": "New Result", "doi": "10.1/new"}])

    cached = cache.read_cache(index_dir)

    assert cache.get_result(cached, 1)["title"] == "Old Result"
    assert cache.get_result(cached, 2)["title"] == "New Result"


def test_a_hit_seen_in_an_earlier_call_comes_back_compact_with_duplicate_of_id(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.append_cache(index_dir, "axis A", [{"title": "Shared Paper", "doi": "10.1/shared", "abstract": "long text"}])
    second = cache.append_cache(index_dir, "axis B", [{"title": "Shared Paper", "doi": "10.1/shared", "abstract": "long text"}])

    assert second == [{"id": 1, "title": "Shared Paper", "duplicate_of_id": 1}]
    # No second slot was created in the persisted cache.
    cached = cache.read_cache(index_dir)
    assert cached["next_id"] == 2


def test_dedup_matches_on_normalized_title_when_doi_missing(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.append_cache(index_dir, "axis A", [{"title": "  Some Title  ", "doi": None}])
    second = cache.append_cache(index_dir, "axis B", [{"title": "some title", "doi": None}])

    assert second[0]["duplicate_of_id"] == 1


def test_hits_with_neither_doi_nor_title_are_never_treated_as_duplicates(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.append_cache(index_dir, "axis A", [{"title": "", "doi": None}])
    second = cache.append_cache(index_dir, "axis B", [{"title": "", "doi": None}])

    assert "duplicate_of_id" not in second[0]
    assert second[0]["id"] == 2


def test_read_cache_raises_clear_error_when_missing(tmp_path):
    index_dir = tmp_path / ".rag_index"

    with pytest.raises(cache.CacheMissError, match="paper-rag discover"):
        cache.read_cache(index_dir)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cache.py -v`
Expected: FAIL (`AttributeError: module 'paper_rag.acquire.cache' has no attribute 'append_cache'`)

- [ ] **Step 3: Rewrite `acquire/cache.py`**

```python
"""Cumulative cache of `discover()` candidates, for this cache file's
lifetime (one MCP server process, or a CLI "session" spanning separate
`discover`/`get` invocations that share the same index directory).

Lets a later `get <id>` (CLI) or `get_paper(ids=[...])` (MCP) reference
exactly what was shown, without re-querying the upstream APIs. Ids come
from a counter that only ever grows — a new `discover` call never resets
or overwrites it — so an id handed out by an earlier call stays valid
after later calls. A hit that matches (by normalized doi, else normalized
title — see acquire/dedup.py) one already in the cache is reported back
compactly, pointing at its existing id, instead of being stored again.
Lives in the same disposable, gitignored index directory as manifest.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from .dedup import natural_key

_CACHE_FILENAME = "discover_cache.json"


class CacheMissError(Exception):
    pass


def _cache_path(index_dir: Path) -> Path:
    return index_dir / _CACHE_FILENAME


def _load(index_dir: Path) -> dict:
    path = _cache_path(index_dir)
    if not path.exists():
        return {"next_id": 1, "queries": [], "seen_keys": {}, "results": {}}
    return json.loads(path.read_text())


def _save(index_dir: Path, cache: dict) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(index_dir).write_text(json.dumps(cache, indent=2))


def append_cache(index_dir: Path, query: str, results: list[dict]) -> list[dict]:
    """Merge `results` (from one `discover()` call) into the persistent
    cache; return the annotated list to show/return to the caller.

    Each hit gets a fresh id the first time its doi/title is seen. A hit
    that matches an id already in the cache is replaced with a compact
    `{"id", "title", "duplicate_of_id"}` entry instead — full metadata is
    stored at most once per genuinely new candidate.
    """
    cache = _load(index_dir)
    cache["queries"].append(query)

    annotated = []
    for hit in results:
        key = natural_key(hit)
        existing_id = cache["seen_keys"].get(key) if key is not None else None
        if existing_id is not None:
            annotated.append({"id": existing_id, "title": hit.get("title"), "duplicate_of_id": existing_id})
            continue

        result_id = cache["next_id"]
        cache["next_id"] += 1
        cache["results"][str(result_id)] = {**hit, "query": query}
        if key is not None:
            cache["seen_keys"][key] = result_id
        annotated.append({**hit, "id": result_id})

    _save(index_dir, cache)
    return annotated


def read_cache(index_dir: Path) -> dict:
    path = _cache_path(index_dir)
    if not path.exists():
        raise CacheMissError(
            f'No discover cache found at {path}. Run `paper-rag discover "<query>"` first.'
        )
    return json.loads(path.read_text())


def get_result(cache: dict, result_id: int) -> dict | None:
    return cache["results"].get(str(result_id))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cache.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Fix the other test file that seeds the cache directly**

In `tests/test_cli_get.py`, in `_seed_cache` (around line 49), replace:
```python
    cache.write_cache(tmp_path / ".rag_index", "some query", results)
```
with:
```python
    cache.append_cache(tmp_path / ".rag_index", "some query", results)
```

- [ ] **Step 6: Run the full suite to confirm no other breakage yet**

Run: `pytest tests/test_cli_get.py tests/test_cache.py tests/test_dedup.py tests/test_discover.py -v`
Expected: PASS. (`tests/test_mcp_discover.py` and `tests/test_cli_discover.py` are expected to still FAIL at this point — they call `cache.write_cache` directly and are fixed in Tasks 5 and 6.)

- [ ] **Step 7: Commit**

```bash
git add src/paper_rag/acquire/cache.py tests/test_cache.py tests/test_cli_get.py
git commit -m "Make discover_cache.json cumulative with global ids and cross-call dedup"
```

---

## Task 3: Reject non-PDF content at download time (`acquire/download.py`)

**Files:**
- Modify: `src/paper_rag/acquire/download.py` (full rewrite)
- Modify: `tests/test_download.py` (append new tests)

**Interfaces:**
- Produces: `download.InvalidPdfContentError(Exception)` — raised by `fetch_pdf_bytes` when the HTTP response is 200 but the body's first 5 bytes aren't `b"%PDF-"`. Not retried (same "permanent for this URL" treatment as `_PERMANENT_STATUS_CODES`). Consumed by Task 4 (`get.py`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_download.py`:

```python
def test_fetch_pdf_bytes_rejects_non_pdf_content():
    html = b"<html><body>Please verify you are human</body></html>"
    with patch(
        "paper_rag.acquire.download.requests.get",
        return_value=_response(200, html, headers={"Content-Type": "text/html"}),
    ):
        with pytest.raises(download.InvalidPdfContentError, match="text/html"):
            download.fetch_pdf_bytes("https://example.com/paper.pdf")


def test_fetch_pdf_bytes_does_not_retry_non_pdf_content():
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return _response(200, b"<html>nope</html>", headers={"Content-Type": "text/html"})

    monkeypatch_target = Mock(sleep=Mock())
    with patch("paper_rag.acquire.download.time", monkeypatch_target), patch(
        "paper_rag.acquire.download.requests.get", side_effect=fake_get
    ):
        with pytest.raises(download.InvalidPdfContentError):
            download.fetch_pdf_bytes("https://example.com/paper.pdf", attempts=3)

    assert len(calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_download.py -v`
Expected: FAIL with `AttributeError: module 'paper_rag.acquire.download' has no attribute 'InvalidPdfContentError'`

- [ ] **Step 3: Rewrite `acquire/download.py`**

```python
"""Download a resolved open-access PDF, with retries."""
from __future__ import annotations

import time

import requests

# A 401/403/404/410 on a specific URL is permanent (publisher blocking
# scripted access, dead link, ...) — retrying the identical URL wastes
# attempts and time. Let the caller (resolve.py's candidate list) move on to
# a different source for the same paper instead.
_PERMANENT_STATUS_CODES = {401, 403, 404, 410}

_PDF_MAGIC = b"%PDF-"


class InvalidPdfContentError(Exception):
    """Raised when a fetch returns HTTP 200 with a body that isn't a real
    PDF — e.g. an anti-bot challenge page or a cookie-wall response served
    in place of the actual file. Treated as permanent for this URL, like
    the codes in _PERMANENT_STATUS_CODES: retrying won't turn an anti-bot
    page into a PDF."""


def fetch_pdf_bytes(pdf_url: str, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(
                pdf_url, timeout=60, headers={"User-Agent": "paper-rag/0.2 (research tool)"}
            )
            r.raise_for_status()
            if r.content[:5] != _PDF_MAGIC:
                content_type = r.headers.get("Content-Type", "unknown")
                raise InvalidPdfContentError(
                    f"Response for {pdf_url} is not a PDF (Content-Type: {content_type}) — "
                    "likely an anti-bot challenge page or a cookie-wall, not the actual paper."
                )
            return r.content
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code in _PERMANENT_STATUS_CODES:
                raise
            last_error = e
        except requests.exceptions.RequestException as e:
            last_error = e
        if attempt < attempts:
            time.sleep(attempt)
    assert last_error is not None
    raise last_error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_download.py -v`
Expected: PASS (all tests, including the 3 pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/paper_rag/acquire/download.py tests/test_download.py
git commit -m "Reject non-PDF content (anti-bot/cookie-wall pages) in fetch_pdf_bytes"
```

---

## Task 4: Surface `invalid_content` as its own `get_paper`/`get` status

**Files:**
- Modify: `src/paper_rag/acquire/get.py:1-79`
- Modify: `src/paper_rag/mcp_server.py:87-94` (docstring only)
- Modify: `src/paper_rag/cli.py:438-441` (help text only)
- Test: `tests/test_get.py` (append new tests)

**Interfaces:**
- Consumes: `download.InvalidPdfContentError` (Task 3).
- Produces: `get.download_candidate(...)` now may return `{"status": "invalid_content", "error": str}` in addition to its existing `"ok"`/`"error"` outcomes. Consumed as-is by `mcp_server.get_paper` and `cli.cmd_get` (neither needs a code change for this — both already just forward `result["status"]`/`result["error"]` generically; only their docstrings/help text change).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_get.py`:

```python
def test_returns_invalid_content_status_without_writing_any_file(tmp_path):
    from paper_rag.acquire.download import InvalidPdfContentError

    with patch(
        "paper_rag.acquire.get.download.fetch_pdf_bytes",
        side_effect=InvalidPdfContentError("Response is not a PDF (Content-Type: text/html)"),
    ):
        result = get.download_candidate(
            _hit(),
            contact_email="test@example.com",
            papers_dir=tmp_path / "papers",
            root=tmp_path,
            citation_key=None,
            fallback_title="query text",
        )

    assert result["status"] == "invalid_content"
    assert "not a PDF" in result["error"]
    assert not (tmp_path / "papers").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_get.py -v -k invalid_content`
Expected: FAIL — `result["status"]` is `"error"`, not `"invalid_content"` (the generic `except Exception` branch currently catches it)

- [ ] **Step 3: Handle `InvalidPdfContentError` before the generic download error**

In `src/paper_rag/acquire/get.py`, change the import line and the download `try`/`except`. Keep the existing `from . import download` submodule import as-is (don't replace it) — `download.fetch_pdf_bytes` is patched by full dotted path (`paper_rag.acquire.get.download.fetch_pdf_bytes`) in `tests/test_get.py`, `tests/test_cli_get.py`, and `tests/test_mcp_discover.py`, and switching to a direct `from .download import fetch_pdf_bytes` import would silently break every one of those patch targets. Only add the new exception import alongside it:

Replace:
```python
from . import download, metadata, unpaywall
```
with:
```python
from . import download, metadata, unpaywall
from .download import InvalidPdfContentError
```

Replace:
```python
    try:
        pdf_content = download.fetch_pdf_bytes(pdf_url)
    except Exception as e:
        return {"status": "error", "error": f"Download failed: {e!r}"}
```
with:
```python
    try:
        pdf_content = download.fetch_pdf_bytes(pdf_url)
    except InvalidPdfContentError as e:
        return {"status": "invalid_content", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": f"Download failed: {e!r}"}
```

Also update the module/function docstring in the same file — replace:
```python
    """Resolve (if needed) + download one discover() candidate.

    Returns {"status": "ok", "citation_key", "pdf_path", "source"} on
    success, or {"status": "error", "error"} on failure — never raises, so
    a batch of ids (cli.py's `get`, mcp_server.py's `get_paper`) can report
    per-item results without one failure aborting the rest.
    """
```
with:
```python
    """Resolve (if needed) + download one discover() candidate.

    Returns {"status": "ok", "citation_key", "pdf_path", "source"} on
    success; {"status": "invalid_content", "error"} if the downloaded
    bytes aren't a real PDF (e.g. an anti-bot/cookie-wall page served with
    HTTP 200 — see acquire/download.py); or {"status": "error", "error"}
    on any other failure. Never raises, so a batch of ids (cli.py's `get`,
    mcp_server.py's `get_paper`) can report per-item results without one
    failure aborting the rest.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_get.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Update `get_paper`'s docstring in `mcp_server.py`**

In `src/paper_rag/mcp_server.py`, replace:
```python
    """Download one or more discover_papers() candidates by id.

    citation_key is only honored for a single id. Returns one dict per
    requested id: {id, status: "ok"|"error", citation_key, pdf_path,
    source, error}.
    """
```
with:
```python
    """Download one or more discover_papers() candidates by id.

    citation_key is only honored for a single id. Returns one dict per
    requested id: {id, status: "ok"|"error"|"invalid_content", citation_key,
    pdf_path, source, error}. "invalid_content" means the download
    succeeded but the response wasn't a real PDF (e.g. an anti-bot
    challenge page or cookie-wall) — no file was written for that id.
    """
```

- [ ] **Step 6: Update the CLI `get` subcommand help text**

In `src/paper_rag/cli.py`, replace:
```python
    p_get = sub.add_parser("get", help="Download one or more candidates from the last `discover` by id")
```
with:
```python
    p_get = sub.add_parser(
        "get",
        help="Download one or more candidates from the discover cache by id "
        "(fails per-id, with a reason, on non-PDF/anti-bot responses)",
    )
```

- [ ] **Step 7: Run the full get/cache-adjacent suite**

Run: `pytest tests/test_get.py tests/test_cli_get.py tests/test_download.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/paper_rag/acquire/get.py src/paper_rag/mcp_server.py src/paper_rag/cli.py tests/test_get.py
git commit -m "Surface invalid_content as its own get_paper/get status"
```

---

## Task 5: Wire `mcp_server.discover_papers`/`get_paper` to the new cache API

**Files:**
- Modify: `src/paper_rag/mcp_server.py:70-125`
- Modify: `tests/test_mcp_discover.py` (full rewrite)

**Interfaces:**
- Consumes: `cache.append_cache` (Task 2), `cache.get_result` returning hits with a `"query"` key (Task 2).
- Produces: `discover_papers` and `get_paper` behavior as described in their new docstrings below — no new public functions.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_mcp_discover.py` entirely with:

```python
from unittest.mock import patch

from paper_rag import mcp_server


def _write_config(tmp_path):
    config_path = tmp_path / ".paper-rag.toml"
    config_path.write_text(
        """
[corpus]
papers_dir = "papers"

[index]
dir = ".rag_index"

[acquire]
contact_email = "test@example.com"
"""
    )
    return config_path


def test_discover_papers_returns_ids_and_writes_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    results = [
        {
            "title": "Paper One",
            "authors": ["Jane"],
            "year": 2024,
            "doi": "10.1/a",
            "source": "semantic_scholar",
            "relevance": 0.9,
            "has_pdf": True,
        }
    ]

    with patch("paper_rag.acquire.discover.discover", return_value=results):
        out = mcp_server.discover_papers("some query")

    assert out[0]["id"] == 1
    assert out[0]["title"] == "Paper One"
    assert (tmp_path / ".rag_index" / "discover_cache.json").exists()


def test_discover_papers_ids_stay_valid_across_later_calls(tmp_path, monkeypatch):
    # Regression test for the real failure mode: a long MCP session makes
    # many discover_papers() calls across different topical axes, and each
    # one used to invalidate every earlier call's ids.
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    with patch(
        "paper_rag.acquire.discover.discover",
        return_value=[{"title": "Axis A Paper", "doi": "10.1/a", "authors": [], "year": 2020, "source": "semantic_scholar", "relevance": 0.8, "has_pdf": True}],
    ):
        first = mcp_server.discover_papers("axis A query")

    with patch(
        "paper_rag.acquire.discover.discover",
        return_value=[{"title": "Axis B Paper", "doi": "10.1/b", "authors": [], "year": 2021, "source": "openalex", "relevance": 0.7, "has_pdf": True}],
    ):
        mcp_server.discover_papers("axis B query")

    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"):
        out = mcp_server.get_paper([first[0]["id"]])

    assert out[0]["status"] == "ok"


def test_discover_papers_compacts_a_candidate_already_seen_in_an_earlier_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    shared_hit = {
        "title": "Shared Paper",
        "doi": "10.1/shared",
        "authors": ["Jane"],
        "year": 2022,
        "source": "semantic_scholar",
        "relevance": 0.6,
        "has_pdf": True,
        "abstract": "a long abstract that should not be repeated",
    }
    with patch("paper_rag.acquire.discover.discover", return_value=[shared_hit]):
        first = mcp_server.discover_papers("axis A query")

    # Build a genuinely separate dict for the second call (not the same
    # object kept alive), so this exercises real cross-call comparison
    # rather than something that would also pass if dedup were keyed by
    # object identity.
    shared_hit_again = dict(shared_hit)
    with patch("paper_rag.acquire.discover.discover", return_value=[shared_hit_again]):
        second = mcp_server.discover_papers("axis B query")

    assert second == [{"id": first[0]["id"], "title": "Shared Paper", "duplicate_of_id": first[0]["id"]}]


def test_get_paper_downloads_by_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    from paper_rag.acquire import cache as cache_mod

    cache_mod.append_cache(
        tmp_path / ".rag_index",
        "some query",
        [
            {
                "title": "Paper One",
                "authors": ["Jane"],
                "year": 2024,
                "doi": "10.1/a",
                "pdf_url": "https://ex.com/a.pdf",
                "source": "semantic_scholar",
                "abstract": "",
            }
        ],
    )

    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"):
        out = mcp_server.get_paper([1])

    assert out[0]["status"] == "ok"
    assert (tmp_path / "papers" / f"{out[0]['citation_key']}.pdf").exists()


def test_get_paper_dedupes_duplicate_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    from paper_rag.acquire import cache as cache_mod

    cache_mod.append_cache(
        tmp_path / ".rag_index",
        "some query",
        [
            {
                "title": "Paper One",
                "authors": ["Jane"],
                "year": 2024,
                "doi": "10.1/a",
                "pdf_url": "https://ex.com/a.pdf",
                "source": "semantic_scholar",
                "abstract": "",
            }
        ],
    )

    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4") as fetch_mock:
        out = mcp_server.get_paper([1, 1])

    assert len(out) == 1
    assert fetch_mock.call_count == 1


def test_get_paper_reports_invalid_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    from paper_rag.acquire import cache as cache_mod
    from paper_rag.acquire.download import InvalidPdfContentError

    cache_mod.append_cache(
        tmp_path / ".rag_index",
        "some query",
        [{"title": "Paper One", "authors": [], "year": 2024, "doi": "10.1/a", "pdf_url": "https://ex.com/a.pdf", "source": "semantic_scholar", "abstract": ""}],
    )

    with patch(
        "paper_rag.acquire.get.download.fetch_pdf_bytes",
        side_effect=InvalidPdfContentError("Response is not a PDF (Content-Type: text/html)"),
    ):
        out = mcp_server.get_paper([1])

    assert out[0]["status"] == "invalid_content"


def test_get_paper_rejects_citation_key_with_multiple_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    out = mcp_server.get_paper([1, 2], citation_key="mykey")

    assert all(r["status"] == "error" for r in out)


def test_get_paper_errors_when_no_cache_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    out = mcp_server.get_paper([1])

    assert out[0]["status"] == "error"
    assert "paper-rag discover" in out[0]["error"]
```

- [ ] **Step 2: Run tests to verify the new/changed ones fail**

Run: `pytest tests/test_mcp_discover.py -v`
Expected: FAIL — `discover_papers` still calls `cache.write_cache` (removed in Task 2) and builds ids manually, so every test in this file errors with `AttributeError: module 'paper_rag.acquire.cache' has no attribute 'write_cache'`.

- [ ] **Step 3: Wire `discover_papers` and `get_paper` to `append_cache`**

In `src/paper_rag/mcp_server.py`, replace the whole `discover_papers` function:

```python
@mcp.tool()
def discover_papers(query: str, limit: int = 10) -> list[dict]:
    """Topical search across Semantic Scholar + OpenAlex (not a title/DOI match).

    Returns up to `limit` ranked candidates, each with title, authors,
    year, doi, source, relevance, has_pdf, and id. Results are cached
    locally — call get_paper(ids=[...]) to download chosen ones.
    """
    cfg = load_config()
    from .acquire import cache, discover

    results = discover.discover(query, cfg.acquire.contact_email, cfg.acquire.semantic_scholar_api_key, limit=limit)
    index_dir = cfg.root / cfg.index.dir
    cache.write_cache(index_dir, query, results)
    return [{**hit, "id": i} for i, hit in enumerate(results, start=1)]
```
with:
```python
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
```

Then, in `get_paper`, replace:
```python
        result = get_mod.download_candidate(
            hit,
            contact_email=cfg.acquire.contact_email,
            papers_dir=papers_dir,
            root=cfg.root,
            citation_key=citation_key,
            fallback_title=cached.get("query", ""),
        )
```
with:
```python
        result = get_mod.download_candidate(
            hit,
            contact_email=cfg.acquire.contact_email,
            papers_dir=papers_dir,
            root=cfg.root,
            citation_key=citation_key,
            fallback_title=hit.get("query", ""),
        )
```
(`cached["query"]` no longer exists — the per-query provenance now lives on each stored hit, set by `cache.append_cache` in Task 2.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_discover.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: PASS everywhere except `tests/test_cli_discover.py` (still uses `cache.write_cache` indirectly via `cmd_discover` — fixed in Task 6).

- [ ] **Step 6: Commit**

```bash
git add src/paper_rag/mcp_server.py tests/test_mcp_discover.py
git commit -m "Wire discover_papers/get_paper to the cumulative cache API"
```

---

## Task 6: Wire `cli.cmd_discover` to the new cache API, with duplicate-aware printing

**Files:**
- Modify: `src/paper_rag/cli.py:237-271`
- Modify: `tests/test_cli_discover.py` (append new test)

**Interfaces:**
- Consumes: `cache.append_cache` (Task 2).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_discover.py`:

```python
def test_discover_prints_duplicate_line_for_a_candidate_seen_in_an_earlier_run(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    shared = {
        "title": "Shared Paper",
        "authors": ["Kim"],
        "year": 2021,
        "doi": "10.1/shared",
        "source": "openalex",
        "relevance": 0.6,
        "has_pdf": True,
    }

    with patch("paper_rag.acquire.discover.discover", return_value=[shared]):
        cmd_discover(argparse.Namespace(config=str(config_path), query="axis A", limit=10))
    capsys.readouterr()  # discard first run's output

    with patch("paper_rag.acquire.discover.discover", return_value=[dict(shared)]):
        cmd_discover(argparse.Namespace(config=str(config_path), query="axis B", limit=10))

    out = capsys.readouterr().out
    assert "DUPLICATE" in out
    assert "already seen as [1]" in out
    assert "Shared Paper" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_discover.py -v -k duplicate`
Expected: FAIL — `cmd_discover` still calls `cache.write_cache` (removed in Task 2), so this errors with `AttributeError`.

- [ ] **Step 3: Rewrite `cmd_discover`**

In `src/paper_rag/cli.py`, replace the whole function:

```python
def cmd_discover(args):
    """Topical search across Semantic Scholar + OpenAlex via `discover()`.
    Prints a numbered, ranked candidate list (title, authors, year, source,
    relevance, OA availability, abstract snippet) and writes it to
    `discover_cache.json` so `paper-rag get <id>` can resolve it later —
    does not download anything itself."""
    cfg = load_config(args.config)
    from .acquire import cache, discover

    results = discover.discover(
        args.query, cfg.acquire.contact_email, cfg.acquire.semantic_scholar_api_key, limit=args.limit
    )
    index_dir = cfg.root / cfg.index.dir
    cache.write_cache(index_dir, args.query, results)
    if not results:
        print("No results found across Semantic Scholar / OpenAlex for this query.", file=sys.stderr)
        return

    for i, hit in enumerate(results, start=1):
        oa = "yes" if hit["has_pdf"] else "no"
        authors = ", ".join(hit.get("authors") or []) or "unknown authors"
        print(f"[{i}] (relevance={hit['relevance']:.2f}, OA: {oa})  {hit.get('title') or '(no title)'}")
        print(f"    {authors}, {hit.get('year') or 'n.d.'} — {hit['source']} — doi: {hit.get('doi') or 'n/a'}")
        abstract = (hit.get("abstract") or "").strip()
        if abstract:
            snippet = abstract[:240] + ("..." if len(abstract) > 240 else "")
            print(f"    {snippet}")

    cache_path = index_dir / "discover_cache.json"
    print(f"\nCached {len(results)} result(s) -> {cache_path.relative_to(cfg.root)}", file=sys.stderr)
    print(
        "Run `paper-rag get <id> [<id> ...]` to download one or more "
        '(only "OA: yes" is guaranteed downloadable; others are resolved on demand).',
        file=sys.stderr,
    )
```
with:
```python
def cmd_discover(args):
    """Topical search across Semantic Scholar + OpenAlex via `discover()`.
    Prints a numbered, ranked candidate list (title, authors, year, source,
    relevance, OA availability, abstract snippet) and merges it into
    `discover_cache.json` so `paper-rag get <id>` can resolve it later.
    Ids persist across `discover` runs — a candidate already seen in an
    earlier run prints as a DUPLICATE line pointing at its original id
    instead of its full entry. Re-running the same query can still change
    the ranking/order of results between runs: that reflects live upstream
    API state (Semantic Scholar/OpenAlex), not a local bug. Does not
    download anything itself."""
    cfg = load_config(args.config)
    from .acquire import cache, discover

    results = discover.discover(
        args.query, cfg.acquire.contact_email, cfg.acquire.semantic_scholar_api_key, limit=args.limit
    )
    index_dir = cfg.root / cfg.index.dir
    annotated = cache.append_cache(index_dir, args.query, results)
    if not annotated:
        print("No results found across Semantic Scholar / OpenAlex for this query.", file=sys.stderr)
        return

    for hit in annotated:
        if "duplicate_of_id" in hit:
            print(f"[{hit['id']}] DUPLICATE — already seen as [{hit['duplicate_of_id']}]: {hit.get('title') or '(no title)'}")
            continue
        oa = "yes" if hit["has_pdf"] else "no"
        authors = ", ".join(hit.get("authors") or []) or "unknown authors"
        print(f"[{hit['id']}] (relevance={hit['relevance']:.2f}, OA: {oa})  {hit.get('title') or '(no title)'}")
        print(f"    {authors}, {hit.get('year') or 'n.d.'} — {hit['source']} — doi: {hit.get('doi') or 'n/a'}")
        abstract = (hit.get("abstract") or "").strip()
        if abstract:
            snippet = abstract[:240] + ("..." if len(abstract) > 240 else "")
            print(f"    {snippet}")

    cache_path = index_dir / "discover_cache.json"
    print(f"\nCached {len(annotated)} result(s) -> {cache_path.relative_to(cfg.root)}", file=sys.stderr)
    print(
        "Run `paper-rag get <id> [<id> ...]` to download one or more "
        '(only "OA: yes" is guaranteed downloadable; others are resolved on demand).',
        file=sys.stderr,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_discover.py -v`
Expected: PASS (all tests, including the pre-existing ones — ids still start at 1 for a fresh cache file per test's `tmp_path`, so their exact-string assertions on `[1] (relevance=...` are unaffected)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: PASS everywhere.

- [ ] **Step 6: Commit**

```bash
git add src/paper_rag/cli.py tests/test_cli_discover.py
git commit -m "Wire cmd_discover to the cumulative cache API with duplicate-aware printing"
```

---

## Task 7: Refresh the LanceDB table handle before every index read (`mcp_server.py`)

**Files:**
- Modify: `src/paper_rag/mcp_server.py:26-35`
- Test: `tests/test_mcp_index_refresh.py` (new)

**Interfaces:**
- No new public interfaces — `_get_index()`'s return signature (`(backend, index, table)`) is unchanged; only its freshness guarantee changes.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_index_refresh.py`:

```python
from paper_rag import mcp_server
from paper_rag.ingest.index import PaperIndex


class _FakeBackend:
    name = "fake-test-model"
    dim = 4

    def embed(self, texts, is_query=False):
        return [[0.0, 0.0, 0.0, 0.0] for _ in texts]


def _write_config(tmp_path):
    config_path = tmp_path / ".paper-rag.toml"
    config_path.write_text(
        """
[corpus]
papers_dir = "papers"

[index]
dir = ".rag_index"

[acquire]
contact_email = "test@example.com"
"""
    )
    return config_path


def _row(citation_key):
    return {
        "chunk_id": f"{citation_key}::0",
        "citation_key": citation_key,
        "section": "Abstract",
        "text": "some text",
        "token_count": 3,
        "pdf_path": f"{citation_key}.pdf",
        "embedding_model": "fake-test-model",
        "vector": [0.0, 0.0, 0.0, 0.0],
    }


def test_list_indexed_papers_sees_rows_added_by_a_separate_build_process(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(mcp_server, "build_backend", lambda *a, **k: _FakeBackend())
    mcp_server._state.clear()

    assert mcp_server.list_indexed_papers() == []

    # Simulate a separate `paper-rag build` (CLI) process writing to the
    # same on-disk index after the MCP server already opened this table
    # handle — a second PaperIndex instance, not the one cached in
    # mcp_server._state.
    external_index = PaperIndex(tmp_path / ".rag_index", "chunks", 4, "fake-test-model")
    external_table = external_index.open_or_create()
    external_index.add(external_table, [_row("newpaper2026")])

    assert mcp_server.list_indexed_papers() == ["newpaper2026"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_index_refresh.py -v`
Expected: FAIL — second `list_indexed_papers()` call still returns `[]` (the cached table handle doesn't see the externally added row).

- [ ] **Step 3: Refresh the table handle in `_get_index()`**

In `src/paper_rag/mcp_server.py`, replace:
```python
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
```
with:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_index_refresh.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: PASS everywhere.

- [ ] **Step 6: Commit**

```bash
git add src/paper_rag/mcp_server.py tests/test_mcp_index_refresh.py
git commit -m "Refresh the MCP server's LanceDB table handle before every index read"
```

---

## Final check

- [ ] Run `pytest -v` one more time from the repo root and confirm every test passes.
- [ ] Re-read `docs/superpowers/specs/2026-07-08-mcp-discover-get-hardening-design.md`'s Goals section against the final diff — each of the five original failure modes (unstable ids, undocumented ranking drift, false-positive PDF downloads, stale `list_indexed_papers`, no cross-call dedup) should have a corresponding code change and test.
