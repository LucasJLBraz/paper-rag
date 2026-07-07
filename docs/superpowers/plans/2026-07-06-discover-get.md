# Discover + Get (topical paper search & multi-download) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user run a free-text topical query, see a ranked/deduplicated list of candidate papers from Semantic Scholar + OpenAlex, and download one or more chosen candidates by id — both from the CLI and from Claude Code via MCP tools.

**Architecture:** Two new commands/tools sit alongside the existing `acquire` (title/DOI match, auto-download) without touching it. `discover()` queries both sources, dedups, scores by keyword-overlap relevance, and returns a ranked list; a local JSON cache (in the same disposable index directory as `manifest.json`) pins down exactly what was shown so a later `get <id> [<id> ...]` downloads precisely those items — resolving via Unpaywall lazily, only for the ids actually requested. A shared `get.download_candidate()` function holds the one-candidate download+metadata-write logic so the CLI `get` command and the MCP `get_paper` tool don't duplicate it.

**Tech Stack:** Python 3.10+, `requests`, stdlib `json`, pytest + `unittest.mock`, existing `paper_rag.acquire.{semantic_scholar,openalex,unpaywall,download,metadata}` modules, `mcp.server.fastmcp.FastMCP`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-06-discover-get-design.md` — follow it exactly; this plan implements it task-by-task.
- `acquire` (CLI command, `resolve.py`, `find_oa_pdf`/`find_oa_pdf_candidates`) is out of scope — do not modify its behavior, only its docstrings/help text where it should now point at `discover`.
- No interactive terminal prompts anywhere in `discover`/`get` — both must work identically when called by the MCP tools (no stdin).
- `discover` never calls Unpaywall; only `get`/`get_paper` do, and only for the specific id(s) requested.
- Every new module/function needs a failing test written first (TDD), per this repo's existing test style (`unittest.mock.patch` on the *source* module's attribute, e.g. `paper_rag.acquire.discover.discover`, not on the importing module's local alias — mirrors how `tests/test_acquire_fallback.py` patches `paper_rag.acquire.resolve.find_oa_pdf_candidates`).
- Run tests with: `cd /home/apo-pc/Documents/Github/paper-rag && pytest -q` (matches `.github/workflows/ci.yml`). A venv with the project installed is assumed; if `pytest` isn't found, run `pip install -e ".[dev]"` first.

---

### Task 1: Extract shared relevance scoring into `acquire/relevance.py`

**Files:**
- Create: `src/paper_rag/acquire/relevance.py`
- Modify: `src/paper_rag/acquire/resolve.py`
- Test: `tests/test_relevance.py`

**Interfaces:**
- Produces: `relevance(query: str, hit: dict) -> float` in `paper_rag.acquire.relevance` — fraction (0.0–1.0) of the query's meaningful (3+ alphanumeric char) terms found in `hit["title"] + hit["abstract"]`, case-insensitive. Used by `resolve.py` (existing, re-exported as `_relevance`) and by `discover.py` (Task 2).

- [ ] **Step 1: Write the failing test**

Create `tests/test_relevance.py`:

```python
from paper_rag.acquire.relevance import relevance


def test_relevance_is_high_for_matching_title_and_low_for_unrelated_match():
    query = "permutation feature importance guided LLM tabular augmentation"
    good_hit = {"title": "Permutation feature importance for tabular LLM augmentation", "abstract": ""}
    bad_hit = {"title": "Accurate predictions with a tabular foundation model", "abstract": "permutation invariant"}

    assert relevance(query, good_hit) > 0.5
    assert relevance(query, bad_hit) < 0.5


def test_relevance_is_one_for_empty_query():
    assert relevance("", {"title": "anything", "abstract": ""}) == 1.0


def test_relevance_handles_missing_abstract_field():
    assert relevance("some query terms", {"title": "some query terms"}) == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_relevance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paper_rag.acquire.relevance'`

- [ ] **Step 3: Create `relevance.py` with the extracted logic**

Create `src/paper_rag/acquire/relevance.py`:

```python
"""Keyword-overlap relevance scoring shared by resolve.py (title/DOI match
confidence) and discover.py (topical search ranking).
"""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def relevance(query: str, hit: dict) -> float:
    """Fraction of the query's meaningful terms found in the hit's title + abstract."""
    query_terms = set(_TOKEN_RE.findall(query.lower()))
    if not query_terms:
        return 1.0
    haystack = f"{hit.get('title') or ''} {hit.get('abstract') or ''}".lower()
    haystack_terms = set(_TOKEN_RE.findall(haystack))
    return len(query_terms & haystack_terms) / len(query_terms)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_relevance.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Point `resolve.py` at the shared implementation**

In `src/paper_rag/acquire/resolve.py`, replace:

```python
import re
import sys

import requests

from . import openalex, semantic_scholar, unpaywall

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_MAX_CANDIDATES = 5
```

with:

```python
import sys

import requests

from . import openalex, semantic_scholar, unpaywall
from .relevance import relevance as _relevance

_MAX_CANDIDATES = 5
```

Then delete the now-duplicated function body (keep everything else unchanged):

```python
def _relevance(query: str, hit: dict) -> float:
    """Fraction of the query's meaningful terms found in the hit's title + abstract."""
    query_terms = set(_TOKEN_RE.findall(query.lower()))
    if not query_terms:
        return 1.0
    haystack = f"{hit.get('title') or ''} {hit.get('abstract') or ''}".lower()
    haystack_terms = set(_TOKEN_RE.findall(haystack))
    return len(query_terms & haystack_terms) / len(query_terms)
```

(i.e. remove this whole function — the `from .relevance import relevance as _relevance` line above already provides `_relevance` under the same name every existing call site and test uses.)

- [ ] **Step 6: Run the full existing resolve test suite to confirm no regression**

Run: `pytest tests/test_resolve.py -v`
Expected: PASS (all existing tests, unchanged — they call `resolve._relevance(...)` and `resolve.RELEVANCE_WARN_THRESHOLD`, both still present)

- [ ] **Step 7: Commit**

```bash
git add src/paper_rag/acquire/relevance.py src/paper_rag/acquire/resolve.py tests/test_relevance.py
git commit -m "$(cat <<'EOF'
Extract relevance scoring into its own module

Needed by the new discover.py (Task 2) as well as resolve.py — avoids
duplicating the keyword-overlap scoring logic.
EOF
)"
```

---

### Task 2: `discover()` — ranked, deduplicated topical search

**Files:**
- Create: `src/paper_rag/acquire/discover.py`
- Test: `tests/test_discover.py`

**Interfaces:**
- Consumes: `semantic_scholar.search(query, api_key="", limit=5) -> list[dict]`, `openalex.search(query, contact_email="", limit=5) -> list[dict]` (existing, unchanged), `relevance(query, hit) -> float` from Task 1.
- Produces: `discover(query: str, contact_email: str, s2_api_key: str = "", limit: int = 10) -> list[dict]` in `paper_rag.acquire.discover`. Each returned dict is the source hit's fields plus `source: str`, `relevance: float`, `has_pdf: bool` (true only if the source API already gave a direct `pdf_url`). Sorted by `relevance` descending, truncated to `limit`, deduplicated across sources (same normalized DOI, or same normalized title when DOI is missing — first occurrence wins). Consumed by Task 5 (CLI `discover` command) and Task 7 (MCP `discover_papers` tool).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_discover.py`:

```python
from unittest.mock import patch

import requests

from paper_rag.acquire import discover


def test_dedups_by_normalized_doi_keeping_first_source():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search",
        return_value=[
            {"title": "Paper A", "doi": "10.1000/Xyz", "pdf_url": "https://s2.example.com/a.pdf", "abstract": ""}
        ],
    ), patch(
        "paper_rag.acquire.discover.openalex.search",
        return_value=[
            {"title": "Paper A (OpenAlex copy)", "doi": "https://doi.org/10.1000/xyz", "pdf_url": None, "abstract": ""}
        ],
    ):
        results = discover.discover("paper a", contact_email="test@example.com")

    assert len(results) == 1
    assert results[0]["source"] == "semantic_scholar"


def test_dedups_by_normalized_title_when_doi_missing():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search",
        return_value=[{"title": "  Multilinear SVD for ECG  ", "doi": None, "pdf_url": "https://s2.example.com/a.pdf", "abstract": ""}],
    ), patch(
        "paper_rag.acquire.discover.openalex.search",
        return_value=[{"title": "multilinear svd for ecg", "doi": None, "pdf_url": None, "abstract": ""}],
    ):
        results = discover.discover("multilinear svd ecg", contact_email="test@example.com")

    assert len(results) == 1


def test_sorts_by_relevance_descending():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search",
        return_value=[
            {"title": "Totally unrelated paper", "doi": "10.1/a", "pdf_url": "https://s2.example.com/a.pdf", "abstract": ""},
            {
                "title": "tensor decomposition multilinear SVD ECG atrial fibrillation",
                "doi": "10.1/b",
                "pdf_url": "https://s2.example.com/b.pdf",
                "abstract": "",
            },
        ],
    ), patch("paper_rag.acquire.discover.openalex.search", return_value=[]):
        results = discover.discover(
            "tensor decomposition multilinear SVD ECG atrial fibrillation feature extraction",
            contact_email="test@example.com",
        )

    assert [r["doi"] for r in results] == ["10.1/b", "10.1/a"]


def test_truncates_to_limit():
    hits = [
        {"title": f"Paper {i}", "doi": f"10.1/{i}", "pdf_url": "https://s2.example.com/x.pdf", "abstract": ""}
        for i in range(5)
    ]
    with patch("paper_rag.acquire.discover.semantic_scholar.search", return_value=hits), patch(
        "paper_rag.acquire.discover.openalex.search", return_value=[]
    ):
        results = discover.discover("paper", contact_email="test@example.com", limit=2)

    assert len(results) == 2


def test_has_pdf_flag_reflects_direct_pdf_url_only():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search",
        return_value=[{"title": "With PDF", "doi": "10.1/a", "pdf_url": "https://s2.example.com/a.pdf", "abstract": ""}],
    ), patch(
        "paper_rag.acquire.discover.openalex.search",
        return_value=[{"title": "Without PDF", "doi": "10.1/b", "pdf_url": None, "abstract": ""}],
    ):
        results = discover.discover("paper", contact_email="test@example.com")

    by_doi = {r["doi"]: r["has_pdf"] for r in results}
    assert by_doi["10.1/a"] is True
    assert by_doi["10.1/b"] is False


def test_one_source_failing_does_not_abort_the_other():
    with patch(
        "paper_rag.acquire.discover.semantic_scholar.search", side_effect=requests.HTTPError("429 rate limited")
    ), patch(
        "paper_rag.acquire.discover.openalex.search",
        return_value=[{"title": "Found via OpenAlex", "doi": "10.1/a", "pdf_url": "https://oa.example.com/a.pdf", "abstract": ""}],
    ):
        results = discover.discover("some query", contact_email="test@example.com")

    assert len(results) == 1
    assert results[0]["source"] == "openalex"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_discover.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paper_rag.acquire.discover'`

- [ ] **Step 3: Implement `discover.py`**

Create `src/paper_rag/acquire/discover.py`:

```python
"""Topical paper search across Semantic Scholar + OpenAlex.

Unlike resolve.py (title/DOI match, picks one candidate to auto-download),
this returns a ranked, deduplicated list of candidates for the caller to
choose from — see cli.py's `discover`/`get` commands and mcp_server.py's
`discover_papers`/`get_paper` tools.
"""
from __future__ import annotations

import re
import sys

import requests

from . import openalex, semantic_scholar
from .relevance import relevance as _relevance

_PER_SOURCE_LIMIT = 8
_DEFAULT_LIMIT = 10
_DOI_PREFIX_RE = re.compile(r"^https?://doi\.org/", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def _safe(fn, *args, default=None, **kwargs):
    # Same fallback philosophy as resolve.py's _safe: a single source's
    # 429/5xx/timeout must not take down the whole discover() call.
    try:
        return fn(*args, **kwargs)
    except requests.RequestException as e:
        source = fn.__module__.rsplit(".", 1)[-1]
        print(f"  ({source} lookup failed, skipping: {e})", file=sys.stderr)
        return default


def _dedup_key(hit: dict) -> str:
    doi = (hit.get("doi") or "").strip()
    if doi:
        return "doi:" + _DOI_PREFIX_RE.sub("", doi).lower()
    title = _WHITESPACE_RE.sub(" ", (hit.get("title") or "").strip().lower())
    return "title:" + title


def discover(query: str, contact_email: str, s2_api_key: str = "", limit: int = _DEFAULT_LIMIT) -> list[dict]:
    """Ranked, deduplicated topical search across sources.

    Each result carries `source`, `relevance`, and `has_pdf` (true only if
    the source API already returned a direct pdf_url — no Unpaywall lookup
    happens here; that's deferred to download time, see get.py).
    """
    hits: list[dict] = []
    seen: set[str] = set()

    def _collect(source_hits, source_name: str) -> None:
        for hit in source_hits:
            key = _dedup_key(hit)
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                {**hit, "source": source_name, "relevance": _relevance(query, hit), "has_pdf": bool(hit.get("pdf_url"))}
            )

    _collect(_safe(semantic_scholar.search, query, api_key=s2_api_key, limit=_PER_SOURCE_LIMIT, default=[]), "semantic_scholar")
    _collect(_safe(openalex.search, query, contact_email, limit=_PER_SOURCE_LIMIT, default=[]), "openalex")

    hits.sort(key=lambda h: h["relevance"], reverse=True)
    return hits[:limit]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_discover.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/paper_rag/acquire/discover.py tests/test_discover.py
git commit -m "$(cat <<'EOF'
Add discover() — ranked, deduplicated topical paper search

Complements resolve.py's title/DOI-match acquire flow with a genuine
topical search: queries Semantic Scholar + OpenAlex, dedups by DOI/title,
scores by keyword overlap, returns a ranked list instead of auto-picking
one candidate.
EOF
)"
```

---

### Task 3: Local discover-results cache

**Files:**
- Create: `src/paper_rag/acquire/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Produces (in `paper_rag.acquire.cache`):
  - `write_cache(index_dir: Path, query: str, results: list[dict]) -> None` — overwrites `<index_dir>/discover_cache.json` with `{"query": query, "results": {"1": results[0], "2": results[1], ...}}` (1-based sequential ids in list order).
  - `read_cache(index_dir: Path) -> dict` — returns that payload; raises `CacheMissError` (subclass of `Exception`) with a message telling the user to run `paper-rag discover` first if the file doesn't exist.
  - `get_result(cache: dict, result_id: int) -> dict | None` — looks up one entry by id, `None` if absent.
- Consumed by Task 5 (`cmd_discover`/`cmd_get`) and Task 7 (`discover_papers`/`get_paper`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cache.py`:

```python
import pytest

from paper_rag.acquire import cache


def test_write_then_read_round_trip(tmp_path):
    index_dir = tmp_path / ".rag_index"
    results = [
        {"title": "Paper One", "doi": "10.1/a", "relevance": 0.9},
        {"title": "Paper Two", "doi": "10.1/b", "relevance": 0.5},
    ]

    cache.write_cache(index_dir, "my query", results)
    cached = cache.read_cache(index_dir)

    assert cached["query"] == "my query"
    assert cache.get_result(cached, 1)["title"] == "Paper One"
    assert cache.get_result(cached, 2)["title"] == "Paper Two"


def test_get_result_returns_none_for_unknown_id(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.write_cache(index_dir, "q", [{"title": "Only One"}])
    cached = cache.read_cache(index_dir)

    assert cache.get_result(cached, 99) is None


def test_new_discover_overwrites_previous_cache(tmp_path):
    index_dir = tmp_path / ".rag_index"
    cache.write_cache(index_dir, "first query", [{"title": "Old Result"}])
    cache.write_cache(index_dir, "second query", [{"title": "New Result"}])

    cached = cache.read_cache(index_dir)

    assert cached["query"] == "second query"
    assert cache.get_result(cached, 1)["title"] == "New Result"


def test_read_cache_raises_clear_error_when_missing(tmp_path):
    index_dir = tmp_path / ".rag_index"

    with pytest.raises(cache.CacheMissError, match="paper-rag discover"):
        cache.read_cache(index_dir)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paper_rag.acquire.cache'`

- [ ] **Step 3: Implement `cache.py`**

Create `src/paper_rag/acquire/cache.py`:

```python
"""Local, disposable cache of the last `discover()` call's results.

Lets a later `get <id>` (CLI) or `get_paper(ids=[...])` (MCP) reference
exactly what was shown, without re-querying the upstream APIs or risking
the result list changing between the two calls. Lives in the same
disposable, gitignored index directory as manifest.json — each new
`discover` call fully overwrites it.
"""
from __future__ import annotations

import json
from pathlib import Path

_CACHE_FILENAME = "discover_cache.json"


class CacheMissError(Exception):
    pass


def _cache_path(index_dir: Path) -> Path:
    return index_dir / _CACHE_FILENAME


def write_cache(index_dir: Path, query: str, results: list[dict]) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    payload = {"query": query, "results": {str(i + 1): r for i, r in enumerate(results)}}
    _cache_path(index_dir).write_text(json.dumps(payload, indent=2))


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
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/paper_rag/acquire/cache.py tests/test_cache.py
git commit -m "$(cat <<'EOF'
Add discover-results cache keyed by sequential id

Lets a later `get <id>` download exactly the candidate that was shown by
`discover`, without re-querying Semantic Scholar/OpenAlex or risking a
changed result list between the two calls.
EOF
)"
```

---

### Task 4: Shared single-candidate download logic

**Files:**
- Create: `src/paper_rag/acquire/get.py`
- Test: `tests/test_get.py`

**Interfaces:**
- Consumes: `download.fetch_pdf_bytes(pdf_url: str) -> bytes`, `metadata.make_citation_key(title, authors, year) -> str`, `metadata.write_metadata(md_path, citation_key, title, authors, year, doi, source, pdf_url, pdf_path, abstract="") -> None`, `unpaywall.resolve(doi, contact_email) -> dict | None` (all existing, unchanged).
- Produces: `download_candidate(hit: dict, contact_email: str, papers_dir: Path, root: Path, citation_key: str | None, fallback_title: str) -> dict` in `paper_rag.acquire.get`. Returns `{"status": "ok", "citation_key": str, "pdf_path": str, "source": str}` or `{"status": "error", "error": str}`. Consumed by Task 6 (CLI `get`) and Task 7 (MCP `get_paper`) — this is the one place the "resolve via Unpaywall if needed, then download, then write PDF + metadata" sequence lives.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_get.py`:

```python
from unittest.mock import patch

from paper_rag.acquire import get


def _hit(**overrides):
    base = {
        "title": "A Great Paper",
        "authors": ["Jane Smith"],
        "year": 2024,
        "doi": "10.1/xyz",
        "pdf_url": "https://example.com/a.pdf",
        "source": "semantic_scholar",
        "abstract": "some abstract",
    }
    base.update(overrides)
    return base


def test_downloads_directly_when_pdf_url_present(tmp_path):
    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"):
        result = get.download_candidate(
            _hit(),
            contact_email="test@example.com",
            papers_dir=tmp_path / "papers",
            root=tmp_path,
            citation_key=None,
            fallback_title="query text",
        )

    assert result["status"] == "ok"
    assert result["source"] == "semantic_scholar"
    assert (tmp_path / "papers" / f"{result['citation_key']}.pdf").exists()
    assert (tmp_path / "papers" / f"{result['citation_key']}.md").exists()


def test_lazily_resolves_via_unpaywall_when_no_direct_pdf_url(tmp_path):
    hit = _hit(pdf_url=None)
    with patch(
        "paper_rag.acquire.get.unpaywall.resolve",
        return_value={"pdf_url": "https://oa.example.com/a.pdf", "license": None},
    ), patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4") as fetch:
        result = get.download_candidate(
            hit,
            contact_email="test@example.com",
            papers_dir=tmp_path / "papers",
            root=tmp_path,
            citation_key=None,
            fallback_title="query text",
        )

    assert result["status"] == "ok"
    assert result["source"] == "unpaywall"
    fetch.assert_called_once_with("https://oa.example.com/a.pdf")


def test_errors_when_no_pdf_available_anywhere(tmp_path):
    hit = _hit(pdf_url=None, doi=None)

    result = get.download_candidate(
        hit,
        contact_email="test@example.com",
        papers_dir=tmp_path / "papers",
        root=tmp_path,
        citation_key=None,
        fallback_title="query text",
    )

    assert result["status"] == "error"
    assert "No open-access PDF" in result["error"]


def test_errors_when_download_fails(tmp_path):
    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", side_effect=Exception("403 Forbidden")):
        result = get.download_candidate(
            _hit(),
            contact_email="test@example.com",
            papers_dir=tmp_path / "papers",
            root=tmp_path,
            citation_key=None,
            fallback_title="query text",
        )

    assert result["status"] == "error"
    assert "Download failed" in result["error"]


def test_honors_citation_key_override(tmp_path):
    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"):
        result = get.download_candidate(
            _hit(),
            contact_email="test@example.com",
            papers_dir=tmp_path / "papers",
            root=tmp_path,
            citation_key="mykey2024",
            fallback_title="query text",
        )

    assert result["citation_key"] == "mykey2024"
    assert (tmp_path / "papers" / "mykey2024.pdf").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_get.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paper_rag.acquire.get'`

- [ ] **Step 3: Implement `get.py`**

Create `src/paper_rag/acquire/get.py`:

```python
"""Shared single-candidate download logic for a discover() result.

Used by both the CLI `get` command (cli.py) and the MCP `get_paper` tool
(mcp_server.py) so citation-key generation, lazy Unpaywall resolution, and
metadata writing only exist once.
"""
from __future__ import annotations

from pathlib import Path

from . import download, metadata, unpaywall


def download_candidate(
    hit: dict,
    contact_email: str,
    papers_dir: Path,
    root: Path,
    citation_key: str | None,
    fallback_title: str,
) -> dict:
    """Resolve (if needed) + download one discover() candidate.

    Returns {"status": "ok", "citation_key", "pdf_path", "source"} on
    success, or {"status": "error", "error"} on failure — never raises, so
    a batch of ids (cli.py's `get`, mcp_server.py's `get_paper`) can report
    per-item results without one failure aborting the rest.
    """
    pdf_url = hit.get("pdf_url")
    source = hit.get("source", "unknown")

    if not pdf_url and hit.get("doi"):
        try:
            oa = unpaywall.resolve(hit["doi"], contact_email)
        except Exception as e:
            return {"status": "error", "error": f"Unpaywall lookup failed: {e!r}"}
        if oa:
            pdf_url = oa["pdf_url"]
            source = "unpaywall"

    if not pdf_url:
        title = hit.get("title") or "(no title)"
        return {"status": "error", "error": f'No open-access PDF available for "{title}" — try downloading it manually.'}

    try:
        pdf_content = download.fetch_pdf_bytes(pdf_url)
    except Exception as e:
        return {"status": "error", "error": f"Download failed: {e!r}"}

    resolved_citation_key = citation_key or metadata.make_citation_key(
        hit.get("title") or fallback_title, hit.get("authors", []), hit.get("year")
    )
    papers_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = papers_dir / f"{resolved_citation_key}.pdf"
    md_path = papers_dir / f"{resolved_citation_key}.md"
    pdf_path.write_bytes(pdf_content)
    metadata.write_metadata(
        md_path,
        resolved_citation_key,
        hit.get("title") or fallback_title,
        hit.get("authors", []),
        hit.get("year"),
        hit.get("doi"),
        source,
        pdf_url,
        pdf_path.relative_to(root),
        hit.get("abstract") or "",
    )
    return {
        "status": "ok",
        "citation_key": resolved_citation_key,
        "pdf_path": str(pdf_path.relative_to(root)),
        "source": source,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_get.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/paper_rag/acquire/get.py tests/test_get.py
git commit -m "$(cat <<'EOF'
Add shared download_candidate() for the discover/get flow

One place for lazy Unpaywall resolution + citation-key generation +
PDF/metadata writing, reused by the CLI `get` command and the MCP
`get_paper` tool (Tasks 6-7) instead of duplicating cmd_acquire's logic.
EOF
)"
```

---

### Task 5: CLI `discover` command

**Files:**
- Modify: `src/paper_rag/cli.py`
- Test: `tests/test_cli_discover.py`

**Interfaces:**
- Consumes: `discover.discover(query, contact_email, s2_api_key, limit) -> list[dict]` (Task 2), `cache.write_cache(index_dir, query, results) -> None` (Task 3).
- Produces: `cmd_discover(args)` where `args` has `.config`, `.query`, `.limit`; wired to `paper-rag discover "<query>" [--limit N]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_discover.py`:

```python
import argparse
from unittest.mock import patch

from paper_rag.cli import cmd_discover


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


def test_discover_prints_numbered_list_and_writes_cache(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    results = [
        {
            "title": "Multilinear SVD for ECG",
            "authors": ["Silva"],
            "year": 2019,
            "doi": "10.1/a",
            "source": "semantic_scholar",
            "relevance": 0.71,
            "has_pdf": True,
        },
        {
            "title": "Tensor decomposition in biomedical signals",
            "authors": ["Kim"],
            "year": 2021,
            "doi": "10.1/b",
            "source": "openalex",
            "relevance": 0.55,
            "has_pdf": False,
        },
    ]

    with patch("paper_rag.acquire.discover.discover", return_value=results):
        cmd_discover(argparse.Namespace(config=str(config_path), query="tensor ecg", limit=10))

    out = capsys.readouterr()
    assert "[1] (relevance=0.71, OA: yes)  Multilinear SVD for ECG" in out.out
    assert "[2] (relevance=0.55, OA: no)  Tensor decomposition in biomedical signals" in out.out
    assert "Silva, 2019" in out.out
    assert "paper-rag get" in out.err
    assert (tmp_path / ".rag_index" / "discover_cache.json").exists()


def test_discover_reports_no_results(tmp_path, capsys):
    config_path = _write_config(tmp_path)

    with patch("paper_rag.acquire.discover.discover", return_value=[]):
        cmd_discover(argparse.Namespace(config=str(config_path), query="nothing matches", limit=10))

    out = capsys.readouterr()
    assert "No results found" in out.err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_discover.py -v`
Expected: FAIL with `ImportError: cannot import name 'cmd_discover' from 'paper_rag.cli'`

- [ ] **Step 3: Implement `cmd_discover` in `cli.py`**

In `src/paper_rag/cli.py`, add this function right after `cmd_search` (before `cmd_acquire`):

```python
def cmd_discover(args):
    cfg = load_config(args.config)
    from .acquire import cache, discover

    results = discover.discover(
        args.query, cfg.acquire.contact_email, cfg.acquire.semantic_scholar_api_key, limit=args.limit
    )
    if not results:
        print("No results found across Semantic Scholar / OpenAlex for this query.", file=sys.stderr)
        return

    index_dir = cfg.root / cfg.index.dir
    cache.write_cache(index_dir, args.query, results)

    for i, hit in enumerate(results, start=1):
        oa = "yes" if hit["has_pdf"] else "no"
        authors = ", ".join(hit.get("authors") or []) or "unknown authors"
        print(f"[{i}] (relevance={hit['relevance']:.2f}, OA: {oa})  {hit.get('title') or '(no title)'}")
        print(f"    {authors}, {hit.get('year') or 'n.d.'} — {hit['source']} — doi: {hit.get('doi') or 'n/a'}")

    cache_path = index_dir / "discover_cache.json"
    print(f"\nCached {len(results)} result(s) -> {cache_path.relative_to(cfg.root)}", file=sys.stderr)
    print(
        "Run `paper-rag get <id> [<id> ...]` to download one or more "
        '(only "OA: yes" is guaranteed downloadable; others are resolved on demand).',
        file=sys.stderr,
    )
```

Then register the subcommand: in `main()`, add right after the `p_search` block and before the `p_acquire` block:

```python
    p_discover = sub.add_parser(
        "discover", help="Topical search across Semantic Scholar/OpenAlex; lists candidates without downloading"
    )
    p_discover.add_argument("query", help="Free-text topic description")
    p_discover.add_argument("--limit", type=int, default=10)
    p_discover.set_defaults(func=cmd_discover)
```

Also update the module docstring at the top of `cli.py`:

```python
"""CLI: paper-rag init | build | search | discover | get | acquire

    paper-rag init
    paper-rag build [--rebuild]
    paper-rag search "<query>" [-k N] [--paper CITATION_KEY]
    paper-rag discover "<query>" [--limit N]
    paper-rag get <id> [<id> ...] [--citation-key KEY]
    paper-rag acquire "<query>" [--citation-key KEY]
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_discover.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/paper_rag/cli.py tests/test_cli_discover.py
git commit -m "$(cat <<'EOF'
Add `paper-rag discover` — topical search with a numbered result list

Complements `acquire` (title/DOI match, auto-download) with a genuine
topic-search flow: lists ranked candidates and caches them for `get` to
download by id.
EOF
)"
```

---

### Task 6: CLI `get` command

**Files:**
- Modify: `src/paper_rag/cli.py`
- Test: `tests/test_cli_get.py`

**Interfaces:**
- Consumes: `cache.read_cache(index_dir) -> dict`, `cache.get_result(cache, id) -> dict | None` (Task 3), `get.download_candidate(...) -> dict` (Task 4).
- Produces: `cmd_get(args)` where `args` has `.config`, `.ids` (list[int]), `.citation_key`; wired to `paper-rag get <id> [<id> ...] [--citation-key KEY]`. Exits non-zero if any requested id failed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_get.py`:

```python
import argparse
from unittest.mock import patch

import pytest

from paper_rag.cli import cmd_get


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


def _seed_cache(tmp_path):
    from paper_rag.acquire import cache

    results = [
        {
            "title": "Paper One",
            "authors": ["Jane"],
            "year": 2024,
            "doi": "10.1/a",
            "pdf_url": "https://ex.com/a.pdf",
            "source": "semantic_scholar",
            "abstract": "",
        },
        {
            "title": "Paper Two",
            "authors": ["Jane"],
            "year": 2024,
            "doi": "10.1/b",
            "pdf_url": None,
            "source": "openalex",
            "abstract": "",
        },
    ]
    cache.write_cache(tmp_path / ".rag_index", "some query", results)


def test_get_downloads_multiple_ids_and_reports_summary(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    _seed_cache(tmp_path)

    with patch("paper_rag.acquire.get.download.fetch_pdf_bytes", return_value=b"%PDF-1.4"), patch(
        "paper_rag.acquire.get.unpaywall.resolve", return_value=None
    ):
        with pytest.raises(SystemExit):
            cmd_get(argparse.Namespace(config=str(config_path), ids=[1, 2], citation_key=None))

    out = capsys.readouterr()
    assert "[1] Downloaded via semantic_scholar" in out.out
    assert "1 downloaded, 1 failed" in out.err


def test_get_errors_on_unknown_id(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    _seed_cache(tmp_path)

    with pytest.raises(SystemExit):
        cmd_get(argparse.Namespace(config=str(config_path), ids=[99], citation_key=None))

    out = capsys.readouterr()
    assert "No such id in the discover cache" in out.err
    assert "0 downloaded, 1 failed" in out.err


def test_get_rejects_citation_key_with_multiple_ids(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    _seed_cache(tmp_path)

    with pytest.raises(SystemExit):
        cmd_get(argparse.Namespace(config=str(config_path), ids=[1, 2], citation_key="mykey"))

    out = capsys.readouterr()
    assert "single id" in out.err


def test_get_errors_when_no_cache_exists(tmp_path, capsys):
    config_path = _write_config(tmp_path)

    with pytest.raises(SystemExit):
        cmd_get(argparse.Namespace(config=str(config_path), ids=[1], citation_key=None))

    out = capsys.readouterr()
    assert "paper-rag discover" in out.err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_get.py -v`
Expected: FAIL with `ImportError: cannot import name 'cmd_get' from 'paper_rag.cli'`

- [ ] **Step 3: Implement `cmd_get` in `cli.py`**

In `src/paper_rag/cli.py`, add this function right after `cmd_discover` (before `cmd_acquire`):

```python
def cmd_get(args):
    cfg = load_config(args.config)
    from .acquire import cache, get as get_mod

    if args.citation_key and len(args.ids) > 1:
        print("--citation-key can only be used when downloading a single id.", file=sys.stderr)
        sys.exit(1)

    index_dir = cfg.root / cfg.index.dir
    try:
        cached = cache.read_cache(index_dir)
    except cache.CacheMissError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    papers_dir = cfg.root / cfg.corpus.papers_dir
    succeeded = 0
    failed = 0
    for result_id in args.ids:
        hit = cache.get_result(cached, result_id)
        if hit is None:
            print(f"[{result_id}] No such id in the discover cache — run `paper-rag discover` again.", file=sys.stderr)
            failed += 1
            continue

        result = get_mod.download_candidate(
            hit,
            contact_email=cfg.acquire.contact_email,
            papers_dir=papers_dir,
            root=cfg.root,
            citation_key=args.citation_key,
            fallback_title=cached.get("query", ""),
        )
        if result["status"] == "ok":
            print(f"[{result_id}] Downloaded via {result['source']}: {result['pdf_path']} (citation key: {result['citation_key']})")
            succeeded += 1
        else:
            print(f"[{result_id}] {result['error']}", file=sys.stderr)
            failed += 1

    print(f"\n{succeeded} downloaded, {failed} failed", file=sys.stderr)
    if failed:
        sys.exit(1)
```

Then register the subcommand: in `main()`, add right after the `p_discover` block and before the `p_acquire` block:

```python
    p_get = sub.add_parser("get", help="Download one or more candidates from the last `discover` by id")
    p_get.add_argument("ids", type=int, nargs="+")
    p_get.add_argument("--citation-key", default=None, help="Override the auto-generated citation key (single id only)")
    p_get.set_defaults(func=cmd_get)
```

Finally, update `cmd_acquire`'s stale-pointing warning so it directs users to the new command instead of an external tool. In `src/paper_rag/cli.py`, replace:

```python
    if hit.get("relevance", 1.0) < resolve.RELEVANCE_WARN_THRESHOLD:
        print(
            f"  WARNING: low keyword overlap (relevance={hit['relevance']:.2f}) between your query and "
            "the matched title/abstract. `acquire` matches by title/DOI, not topic — verify this is "
            "actually the paper you meant before citing it. For topical/discovery searches, prefer "
            "WebSearch or arxiv-paper-fetch instead.",
            file=sys.stderr,
        )
```

with:

```python
    if hit.get("relevance", 1.0) < resolve.RELEVANCE_WARN_THRESHOLD:
        print(
            f"  WARNING: low keyword overlap (relevance={hit['relevance']:.2f}) between your query and "
            "the matched title/abstract. `acquire` matches by title/DOI, not topic — verify this is "
            "actually the paper you meant before citing it. For topical/discovery searches, use "
            "`paper-rag discover` instead.",
            file=sys.stderr,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_get.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all tests pass (the `acquire` warning-text change touches `tests/test_acquire_fallback.py::test_acquire_warns_on_low_relevance_match`, which only asserts `"WARNING: low keyword overlap" in out.err` — still true)

- [ ] **Step 6: Commit**

```bash
git add src/paper_rag/cli.py tests/test_cli_get.py
git commit -m "$(cat <<'EOF'
Add `paper-rag get` — download one or more `discover` candidates by id

Reads the discover cache, resolves Unpaywall lazily per requested id, and
reports a per-item result plus a downloaded/failed summary. Also points
`acquire`'s low-relevance warning at `discover` instead of an external
tool, now that this repo has its own topical-search flow.
EOF
)"
```

---

### Task 7: MCP `discover_papers` + `get_paper` tools

**Files:**
- Modify: `src/paper_rag/mcp_server.py`
- Test: `tests/test_mcp_discover.py`

**Interfaces:**
- Consumes: `discover.discover(...)`, `cache.write_cache/read_cache/get_result(...)`, `get.download_candidate(...)` (Tasks 2-4).
- Produces: `discover_papers(query: str, limit: int = 10) -> list[dict]` (each dict = a Task 2 result plus `id: int`), `get_paper(ids: list[int], citation_key: str | None = None) -> list[dict]` (one `{"id", "status", ...}` dict per requested id, same shape as Task 4's `download_candidate` return, with `id` added).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_discover.py`:

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


def test_get_paper_downloads_by_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    from paper_rag.acquire import cache as cache_mod

    cache_mod.write_cache(
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

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_discover.py -v`
Expected: FAIL — `mcp` may not be importable in this environment; if so, run `pip install -e ".[dev]"` first (it's a declared dependency, see `pyproject.toml`). Once importable: FAIL with `AttributeError: module 'paper_rag.mcp_server' has no attribute 'discover_papers'`

- [ ] **Step 3: Implement the two tools in `mcp_server.py`**

In `src/paper_rag/mcp_server.py`, add these two functions right after `list_indexed_papers` (before `def main()`):

```python
@mcp.tool()
def discover_papers(query: str, limit: int = 10) -> list[dict]:
    """Topical search across Semantic Scholar + OpenAlex (not a title/DOI match).

    Returns up to `limit` ranked, deduplicated candidates, each with title,
    authors, year, doi, source, relevance, has_pdf, and id. Results are
    cached locally — call get_paper(ids=[...]) to download chosen ones.
    """
    cfg = load_config()
    from .acquire import cache, discover

    results = discover.discover(query, cfg.acquire.contact_email, cfg.acquire.semantic_scholar_api_key, limit=limit)
    index_dir = cfg.root / cfg.index.dir
    cache.write_cache(index_dir, query, results)
    return [{**hit, "id": i} for i, hit in enumerate(results, start=1)]


@mcp.tool()
def get_paper(ids: list[int], citation_key: str | None = None) -> list[dict]:
    """Download one or more discover_papers() candidates by id.

    citation_key is only honored for a single id. Returns one dict per
    requested id: {id, status: "ok"|"error", citation_key, pdf_path,
    source, error}.
    """
    cfg = load_config()
    from .acquire import cache, get as get_mod

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
            fallback_title=cached.get("query", ""),
        )
        out.append({"id": result_id, **result})
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_discover.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/paper_rag/mcp_server.py tests/test_mcp_discover.py
git commit -m "$(cat <<'EOF'
Expose discover/get as MCP tools

Lets Claude Code run the same topical-search + multi-download flow as the
CLI, sharing the same discover_cache.json so ids line up between the two
interfaces.
EOF
)"
```

---

### Task 8: Docs + changelog + version bump

**Files:**
- Modify: `README.md`
- Modify: `src/paper_rag/data/SKILL.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`

**Interfaces:** None (docs-only task).

- [ ] **Step 1: Update `README.md`'s "How it works" Acquisition section**

Replace the final sentence of the Acquisition paragraph. Find:

```markdown
**Acquisition** (`paper-rag acquire`) resolves a query to a downloadable
PDF via the same Semantic Scholar -> OpenAlex -> Unpaywall chain, but
matches by title/DOI, not topic — it has no semantic relevance ranking, so
a vague topical query can land on an unrelated paper that happens to share
a keyword. Two things guard against trusting a bad match silently: it
collects up to 5 ranked candidates instead of one, falling through to the
next if a candidate's PDF fails to download (a publisher blocking scripted
access doesn't necessarily mean every open-access copy is unreachable);
and it prints a low-confidence warning when the matched title/abstract
shares few terms with the query. For actual topic-level discovery ("find
papers about X"), prefer WebSearch or an arXiv-specific tool — `acquire` is
a resolver for a paper you can already name, not a literature search
engine.
```

Replace with:

```markdown
**Acquisition** (`paper-rag acquire`) resolves a query to a downloadable
PDF via the same Semantic Scholar -> OpenAlex -> Unpaywall chain, but
matches by title/DOI, not topic — it has no semantic relevance ranking, so
a vague topical query can land on an unrelated paper that happens to share
a keyword. Two things guard against trusting a bad match silently: it
collects up to 5 ranked candidates instead of one, falling through to the
next if a candidate's PDF fails to download (a publisher blocking scripted
access doesn't necessarily mean every open-access copy is unreachable);
and it prints a low-confidence warning when the matched title/abstract
shares few terms with the query. For actual topic-level discovery ("find
papers about X"), use `paper-rag discover` instead — `acquire` is a
resolver for a paper you can already name, not a literature search engine.

**Discovery** (`paper-rag discover` / the MCP `discover_papers` tool)
covers that other case: a free-text topical query returns a ranked,
deduplicated list of candidates from Semantic Scholar + OpenAlex (title,
authors, year, source, relevance, and whether a PDF is directly
available), cached locally by sequential id. `paper-rag get <id> [<id>
...]` (or the MCP `get_paper` tool) then downloads one or more chosen
candidates from that cache — resolving via Unpaywall on demand for
candidates that only have a DOI, so that lookup only happens for papers
actually requested, not every candidate shown.
```

- [ ] **Step 2: Update `README.md`'s "Companion metadata files" section**

Find:

```markdown
`paper-rag acquire` writes this automatically. If you're pulling in arXiv
papers, use a dedicated arXiv-fetch tool for those instead (this schema is
compatible with one) — `paper-rag acquire` is for everything Semantic
Scholar / OpenAlex / Unpaywall can resolve that arXiv-specific tooling
can't.
```

Replace with:

```markdown
`paper-rag acquire` and `paper-rag get` both write this automatically. If
you're pulling in arXiv papers, use a dedicated arXiv-fetch tool for those
instead (this schema is compatible with one) — `paper-rag acquire` /
`discover`+`get` are for everything Semantic Scholar / OpenAlex /
Unpaywall can resolve that arXiv-specific tooling can't.
```

- [ ] **Step 3: Update the bundled Claude Code skill (`src/paper_rag/data/SKILL.md`)**

Find the "When to use which tool" bullet:

```markdown
- **Topical/discovery search** ("find papers about X" with no specific
  title in mind): use WebSearch or `arxiv-paper-fetch`, not `acquire` —
  `acquire` is a title/DOI resolver, not a literature-discovery tool.
```

Replace with:

```markdown
- **Topical/discovery search** ("find papers about X" with no specific
  title in mind): call the `discover_papers` MCP tool (or `paper-rag
  discover "<topic>"` from a shell) — it returns a ranked, numbered list of
  candidates instead of guessing one. Show the list to the user, then call
  `get_paper(ids=[...])` (or `paper-rag get <id> [<id> ...]`) for the
  one(s) they pick. Don't use `acquire` for this — it's a title/DOI
  resolver with no topical ranking, and can silently match an unrelated
  paper that happens to share a keyword.
```

Then find the "Acquisition of a known non-arXiv paper" bullet:

```markdown
- **Acquisition of a known non-arXiv paper**: run `paper-rag acquire "<its
  title>"`. This matches by title/DOI — it has no real relevance ranking,
  so pass the actual title (or a DOI), not a topical description; a vague
  query can land on an unrelated paper that happens to share a keyword.
  `acquire` prints a `Matched: "..."` line and a low-confidence warning
  when its match shares few terms with your query — read both before
  trusting the result. If this repo has an `arxiv-paper-fetch` skill and
  the paper is on arXiv, use that instead — don't route arXiv papers
  through this tool.
```

Replace with:

```markdown
- **Acquisition of a known non-arXiv paper**: run `paper-rag acquire "<its
  title>"`. This matches by title/DOI — it has no real relevance ranking,
  so pass the actual title (or a DOI), not a topical description; a vague
  query can land on an unrelated paper that happens to share a keyword.
  `acquire` prints a `Matched: "..."` line and a low-confidence warning
  when its match shares few terms with your query — read both before
  trusting the result. If this repo has an `arxiv-paper-fetch` skill and
  the paper is on arXiv, use that instead — don't route arXiv papers
  through this tool. For a topical query where you don't already have one
  specific title in mind, use discovery (above) instead.
```

Finally, add `discover_papers` / `get_paper` to the tool list in the frontmatter `description` field at the top of the file. Find:

```yaml
description: Local hybrid (dense + BM25) semantic search over this repo's configured paper corpus (retrieval instead of full-text PDF reads) plus open-access paper acquisition beyond arXiv (Semantic Scholar, OpenAlex, Unpaywall). Use this to find relevant passages across the paper corpus ("what do our papers say about X") instead of re-reading whole PDFs, and to download a non-arXiv paper (journal PDF, DOI) into the papers directory with a companion metadata file. If this project has an arxiv-paper-fetch skill, use that for arXiv papers specifically — this skill defers to it rather than duplicating it.
```

Replace with:

```yaml
description: Local hybrid (dense + BM25) semantic search over this repo's configured paper corpus (retrieval instead of full-text PDF reads) plus open-access paper discovery and acquisition beyond arXiv (Semantic Scholar, OpenAlex, Unpaywall). Use this to find relevant passages across the paper corpus ("what do our papers say about X") instead of re-reading whole PDFs, to run a topical search that lists ranked candidate papers to choose from (discover_papers/get_paper, or `paper-rag discover`/`get`), and to download a specific known non-arXiv paper (journal PDF, DOI) into the papers directory with a companion metadata file (acquire). If this project has an arxiv-paper-fetch skill, use that for arXiv papers specifically — this skill defers to it rather than duplicating it.
```

- [ ] **Step 4: Add a `CHANGELOG.md` entry and bump the version**

In `pyproject.toml`, change:

```toml
version = "0.3.2"
```

to:

```toml
version = "0.4.0"
```

In `CHANGELOG.md`, add a new section right after the `# Changelog` header (before `## 0.3.2`):

```markdown
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
```

- [ ] **Step 5: Run the full test suite one last time**

Run: `pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add README.md src/paper_rag/data/SKILL.md CHANGELOG.md pyproject.toml
git commit -m "$(cat <<'EOF'
Document discover/get, bump to 0.4.0

Updates README/SKILL.md to route topical queries at the new
discover/get flow instead of WebSearch/arxiv-paper-fetch, per the
new feature added in this branch.
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-07-06-discover-get-design.md` maps to a task — `discover.py`/dedup/relevance (Task 2), `cache.py` (Task 3), CLI `discover`/`get` (Tasks 5-6), MCP tools (Task 7), error handling (Tasks 6-7 per-item error paths), docs (Task 8). The shared `download_candidate()` (Task 4) fulfills the spec's "same citation-key generation logic `acquire` already uses" requirement via extraction rather than duplication.
- **Type consistency:** `discover()` (Task 2) returns dicts with `has_pdf`/`relevance`/`source` — the same field names are read in Task 5 (`cmd_discover`), Task 3's cache (stored as-is), Task 6 (`cmd_get` reads `pdf_url`/`doi`/`title`/`authors`/`year`/`abstract`/`source` off the cached hit), and Task 7 (mirrors Task 6). `download_candidate()`'s return shape (`status`/`citation_key`/`pdf_path`/`source`/`error`) is used identically by Task 6 and Task 7.
- **No placeholders:** every step has complete, runnable code — no "similar to Task N" shortcuts.
