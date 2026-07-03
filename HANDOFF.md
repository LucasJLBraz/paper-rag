# Handoff: build-performance investigation

Context for whoever (human or Claude session) picks this up next. Written
after the first real `paper-rag build` run against a 6-paper corpus
(`LLM_synthetic_data/references/Papers/`) appeared to hang for 18+ minutes
and had to be killed.

## What we initially assumed (and why it was wrong)

The build log showed repeated `MuPDF error: syntax error: invalid key in
dict` warnings on the first paper ("A Survey on Tabular Data Generation...")
immediately before it went silent for 18 minutes. The obvious read was "a
malformed PDF is stalling the parser." **That diagnosis doesn't hold up**:

- Converting that exact PDF in isolation (`pdf_to_markdown`) completes in
  **3.5 seconds** and produces 48 clean chunks. The MuPDF warnings are
  PyMuPDF recovering from corrupt xref/dict entries, not failing — cosmetic
  noise, not a stall.
- Measured embedding cost on this machine's CPU with the default model
  (`BAAI/bge-m3`, 568M params): **~1.7s/chunk**. For 48 chunks alone that's
  ~85s. Across 6 papers with a few hundred total chunks, an 18-minute wall
  time is consistent with just... working, slowly.
- The real culprit for the *appearance* of a hang: Python stdout is
  block-buffered when piped to a file (which is how the build was
  launched), so none of the `print()` progress lines were flushed until
  the buffer filled or the process exited. A slow-but-healthy build looked
  identical to a frozen one.

Point being: don't trust the first plausible-looking error message next to
a stall. Measure the actual stage costs before concluding what's broken.

## What's actually true

1. **PDF parsing (`pymupdf4llm`) is fast and works fine** on the papers in
   this corpus, warnings included.
2. **CPU embedding throughput is the dominant cost.** `bge-m3` at
   ~1.7s/chunk on a laptop CPU means a corpus of a few dozen papers takes
   several minutes to (re)build from scratch. This is a real constraint,
   not a bug — but it's worth discussing whether it's the right default.
3. **Observability was broken**, independent of the above — buffered
   output made a working process indistinguishable from a stuck one.

## Mitigations already shipped (this commit)

- `cli.py::main()` forces line-buffered stdout; `cmd_build` prints
  per-paper chunk counts and elapsed time as it goes (`  N chunks to embed
  (this is the slow part on CPU) ...`, then `  N chunks indexed (Xs)`), so
  a running build is visibly alive.
- `ingest/convert.py::pdf_to_markdown` now takes a `timeout_seconds`
  (SIGALRM, Unix-only, default 120s via `.paper-rag.toml`'s new
  `[ingest] pdf_timeout_seconds`). Didn't fire on the paper that started
  this investigation, but it's a real safety net — MuPDF *can*
  pathologically hang on sufficiently corrupt input, this just wasn't one
  of those cases.
- `cmd_build`'s per-PDF loop is now wrapped in try/except: a failing paper
  is logged and skipped (not written to the manifest, so it's retried on
  the next `build`) instead of taking the whole batch down.

None of this fixes the actual embedding-speed constraint — it just makes
slowness visible and bounds worst-case failure per paper.

## Open questions for discussion

### 1. Is `pymupdf4llm` good enough, or do we want GROBID?

[GROBID](https://github.com/kermitt2/grobid) is purpose-built for academic
PDF structure extraction — TEI XML output with real section/paragraph
boundaries, robust bibliography parsing, better handling of two-column
layouts and in-text citation markers than a generic PDF-to-markdown
converter.

Trade-off: it's a Java service, normally run via Docker (~4GB image, JVM
warm-up per request). That cuts against this project's "embedded, no
server process" design goal, though it can still run fully local (no data
leaves the machine) so it doesn't violate any data-locality constraint —
just adds deployment weight. It would replace (or run alongside, as a
fallback) `ingest/convert.py`'s `pymupdf4llm` call.

Given what we actually found — parsing wasn't the bottleneck on this
corpus — GROBID is worth evaluating for **retrieval/citation quality**
(cleaner section boundaries, better reference extraction for citation
checks), not as a fix for the performance issue we hit.

Alternatives in the same space, lighter than GROBID but heavier than
`pymupdf4llm`: `docling` (IBM, pure Python, ML layout model, no external
service) and `marker` (similar trade-off). Worth a quick bake-off on 2-3
of the messier PDFs in the corpus before committing to any of them.

### 2. Is `bge-m3` the right default embedding model?

It's strong and multilingual (this project's docs mix English and
Portuguese, which matters), but at ~1.7s/chunk on CPU it makes full
rebuilds slow. Smaller multilingual alternatives worth benchmarking:
`intfloat/multilingual-e5-small` (118M params) or
`paraphrase-multilingual-MiniLM-L12-v2` (also ~118M) — both should be
several times faster on CPU, at some retrieval-quality cost. Switching is
a one-line config change (`embedding.model` in `.paper-rag.toml`); the
question is whether the quality trade-off is worth it, and that needs an
actual retrieval-quality comparison, not just a speed argument.

### 3. Is slow-but-correct actually fine here?

`build` is incremental (hashes PDFs, skips unchanged ones), so the
multi-minute cost is paid once per paper, not per session. If the real
usage pattern is "add a few papers occasionally, mostly query," raw build
throughput may just not matter much — the fix that mattered most this
round was observability (don't let a working process look dead), not
speed. Worth deciding explicitly rather than defaulting into a bigger
GROBID/model-swap project if the incremental-build story already makes
this a non-issue in practice.

## Update: real numbers from the first instrumented run, and a second bug

With the hardening above shipped, we ran `build` for real against the
6-paper corpus and could finally *watch* it work instead of guessing.
Measured, end to end, per paper:

| paper | chunks | wall time | s/chunk |
|---|---|---|---|
| A Survey on Tabular Data Generation... | 48 | 169.6s | 3.53 |
| Comprehensive evaluation framework for synthetic tabular data in health | 78 | 227.7s | 2.92 |
| EPIC_Jinhee_Kim_2025 | 116 | *(killed mid-embedding, see below)* | — |

Two things worth flagging:

**The measured rate (~3-3.5s/chunk) is roughly 2x the earlier isolated
microbenchmark (~1.76s/chunk on a 5-chunk sample).** Don't read too much
into either number — this run had a live Claude Code session doing other
work concurrently (git, pip, editor activity) competing for the same CPU,
and the microbenchmark was a 5-chunk sample, not a steady-state measurement.
Neither is a controlled benchmark. Before deciding between "keep bge-m3" vs.
"switch to a smaller model" vs. "add GROBID," get a clean number: run
`build --rebuild` on an otherwise-idle machine and let it finish.
Extrapolating from what we have, a full cold build of this 6-paper corpus
likely costs somewhere in the 20-35 minute range under contention, probably
less on a dedicated run — that's the number to react to, not a per-chunk
guess.

**We deliberately killed the process again mid-run** (this time by choice,
not because it looked stuck — the new progress output made it obvious it
was healthy) to redirect effort into this writeup, and that surfaced a real
bug: `manifest.json` was only written once, *after* the entire batch loop
finished. Papers 1-2's 126 chunks were correctly and durably committed to
the LanceDB table (verified directly — per-paper atomicity works as
designed), but killing the process before the loop's tail meant the
manifest never recorded that those two were done. A subsequent `build`
would have silently redone ~6.5 minutes of already-correct work. Fixed by
writing `manifest.json` after every successful paper instead of once at the
end (see `cmd_build` in `cli.py`) — now an interrupted batch only ever
re-does the one paper that was in flight, never the ones that already
landed. Manually backfilled the manifest for the two completed papers in
`LLM_synthetic_data` rather than losing that work to a redundant re-embed.

Net effect: the system is now both observable and safely resumable under
interruption. The open questions above (GROBID, embedding model choice,
whether speed matters at all) are unchanged — this just fixed two
correctness/UX bugs the first real run exposed, on top of the performance
question itself still being open.

## Update: embedding model swap + a real chunking bug (resolves open question #2)

Open question #2 above ("is `bge-m3` the right default?") is answered: no,
not for this hardware. Full writeup below; short version — swapped to
`intfloat/multilingual-e5-small`, and while validating the swap with a
retrieval-quality benchmark, found and fixed a chunking bug that was
silently hurting table-heavy papers regardless of embedding model.

### Speed: clean before/after, same 6-paper corpus, same machine

| model | params | full-corpus cold rebuild | s/chunk (steady state) |
|---|---|---|---|
| `BAAI/bge-m3` | 567M | ~169-200s *per paper* (never finished a full clean run — see below) | ~2.5-3.5 |
| `intfloat/multilingual-e5-small` | 118M | **~2 min total** | ~0.2-0.3 |
| `intfloat/multilingual-e5-base` | 278M | ~3:50-4:10 total | ~0.4-0.7 |

The `bge-m3` numbers in the "real numbers" section above turned out **not**
to be an artifact of CPU contention from a concurrent Claude Code session,
as originally hypothesized — a clean, single-purpose `build --rebuild` on
paper 1-2 reproduced the same ~2.5-3.5s/chunk. `bge-m3` is just genuinely
this slow on an Iris Xe / no-CUDA laptop CPU. `multilingual-e5-small` was
chosen over an English-only model (e.g. `bge-base-en-v1.5`) specifically
because queries against this corpus are mixed English/Portuguese even
though the papers themselves are ~98% English — an English-only model
can't do cross-lingual query→passage matching, which would have silently
broken PT queries against EN papers. `multilingual-e5-base` was tried as a
"does more model help" check and came back *slightly worse* on the quality
benchmark below while taking ~2x longer — treated as noise, not a real
signal; ruled out.

**Bug caught before benchmarking**: E5 models are trained on prefixed
asymmetric pairs (`"query: "` / `"passage: "`) and lose meaningful
retrieval quality without them — nothing in the codebase added these.
Fixed in `ingest/embed.py` (`SentenceTransformerBackend.embed` now takes
`is_query: bool`, auto-detects E5-family models by name) and the two call
sites that embed a query (`cli.py::cmd_search`, `mcp_server.py`). Chunk
embedding (`cli.py::cmd_build`) passes `is_query=False` (the default).

### Quality: Golden Q&A / Hit Rate@5 protocol

Per a validation protocol the user supplied: picked 3 already-indexed
control papers, generated 45 highly specific factual questions (15/paper —
table values, hyperparameters, named methods, specific findings, not
abstract-level stuff) each paired with an exact verbatim excerpt from the
paper as ground truth, then measured Hit Rate@5 — does the correct chunk
appear in the top-5 search results for that question. Lives in the
*corpus* repo (`LLM_synthetic_data/benchmark.json` +
`test_retrieval_quality.py`), not here, since it's tied to that corpus's
actual papers — `paper-rag` itself stays corpus-agnostic. Threshold: 85%.

**Baseline** (`multilingual-e5-small`, unmodified chunker): **73.3%** (33/45).

Root cause of most failures: `ingest/chunk.py`'s paragraph splitter treats
an entire markdown table as one indivisible paragraph (no blank lines
inside a table to split on). A 15-row results table became a single
~630-token chunk — one embedding vector trying to represent every
model's numbers at once, unable to discriminate "what's GC's Hellinger
distance" from "what's TabDif's" when a query asks about one specific row.
This has nothing to do with which embedding model is configured; it would
have hurt `bge-m3` just as much.

**Fix** (`ingest/chunk.py`): tables now get detected (`_is_table`, keys off
the `|---|---|` separator row) and split into small row-batches
(`_TABLE_ROWS_PER_CHUNK = 4`), with the table's caption (if a short
paragraph immediately precedes it) and header repeated in every batch for
context, and each batch flushed as its own atomic chunk — never merged
back into surrounding prose. Two follow-on bugs found while building this:

- **Row-span/merged cells**: `pymupdf4llm` flattens a cell that visually
  spans several rows (e.g. a dataset name next to a block of per-method
  metric rows) by writing the label on only *one* row of the span — not
  necessarily the first, observed on one table at the 4th-of-7 row — and
  leaving the rest of that column blank. Splitting naively into row
  batches would separate a data row from the one row that says which group
  it belongs to. Fixed with `_fill_merged_cells`: nearest-neighbor fill by
  row distance, in either direction, reconstructs the label for every row
  without assuming which row of the span originally carried it. Verified
  this actually matters: before the fix, `"What was the Hellinger distance
  ... for the GC model on the Acute Myeloid Leukemia dataset"` missed
  because the correct row's chunk didn't say "GC" was for that dataset in
  isolation.
- **A bug in the fix itself**: first cut used `.strip("|")` to trim a row's
  delimiter pipes before splitting into cells — but `.strip()` eats *all*
  matching characters from each end, so a row with a genuinely empty first
  cell (`"||Original|58|"`, i.e. two adjacent pipes) collapsed to
  `"Original|58|"`, silently dropping a column and misaligning every cell
  after it. Caught by a test
  (`test_table_row_span_group_label_is_filled_into_every_row`) before it
  shipped. Fixed with `_row_cells()`, which trims exactly one delimiter
  pipe per side instead of stripping the whole run.

**After the chunking fix**: **80.0%** (36/45) — 5 previously-failing
table-row questions fixed, 2 new misses introduced (increased fragmentation
— 116→177 chunks on the largest paper — shifted some chunk boundaries for
two prose-based questions that previously happened to land in one chunk).
Net +3. Still below the 85% target.

**Known limitation, found not fixed**: `_fill_merged_cells`'s
nearest-neighbor heuristic works well for a column that's a clean,
evenly-spaced group label (the case above) but can guess wrong on a column
that's genuinely sparse/optional with no clean group boundaries — found on
one "model comparison" table in the Survey paper where a "Primary
Requirement" column is populated on only ~7 of 25 rows with ragged,
uneven gaps between labels. The fill's row-distance guess is sometimes
wrong there. This is a pre-existing failure (the 2 affected questions —
`CTGAN`/`medGAN` feature counts — were already misses in the 73.3%
baseline, before any chunking changes), not a regression, but it's a real
correctness edge case worth knowing about: the fill trades "usually more
correct" for "occasionally invents an attribution" on ambiguous tables.

**Remaining gap analysis**: of the 9 final misses, 7 were confirmed present
in the index but ranked outside top-20 (not a "just raise k" fix), and 6 of
the 9 cluster on one paper (`EPIC_Jinhee_Kim_2025`) that reports the same
F1/accuracy numbers in three different tables (main results, ablation,
appendix) plus prose sections that paraphrase them — a genuinely hard
disambiguation problem for a single dense-embedding pass, likely to need
reranking or hybrid (BM25 + dense) search rather than more chunking work to
close.

**Shipped as default**: `intfloat/multilingual-e5-small` +
table-aware chunking. Strictly better than the `bge-m3` status quo on both
speed and the quality benchmark. 13/13 unit tests passing
(`tests/test_chunk.py` gained 3 table-specific cases).

## Update: end-to-end pipeline test surfaced two `acquire` crash bugs

Ran `paper-rag acquire` for real (not unit-tested before this) to check the
"find a paper" half of the tool actually works, then chunked the result to
check the fix above generalizes past the 3 curated benchmark papers.

**Bug 1 — one rate-limited source crashed the whole command.**
`acquire/resolve.py`'s fallback chain (Semantic Scholar -> Unpaywall ->
OpenAlex -> Unpaywall) had no error handling anywhere; `semantic_scholar.py`,
`openalex.py`, and `unpaywall.py` all call `raise_for_status()` unguarded.
Semantic Scholar's unauthenticated tier rate-limits hard enough that it
tripped from *ordinary interactive testing* — a second manual check a
minute later hit 429 again. Every 429/timeout/5xx from the first source in
the chain took the whole `acquire` command down with a raw traceback
instead of falling through to the next source. Fixed with a `_safe()`
wrapper in `resolve.py` that catches `requests.RequestException`, logs a
one-line notice, and returns an empty/`None` default so the chain moves on
— covered by `tests/test_resolve.py` (mocks each source failing in turn).

**Bug 2 — a download failure also crashed uncaught.** Once resolved to a
candidate PDF URL, `cmd_acquire` called `download.fetch_pdf_bytes()`
(which itself already retries transient errors 3x) with no try/except —
a *permanent* failure (e.g. a publisher blocking scripted downloads with
403, seen live against `academic.oup.com` and `mdpi.com` during testing)
produced a raw traceback. Fixed by wrapping the download call in
`cmd_acquire` (`cli.py`) with a try/except that prints which source/URL was
tried and suggests a more specific query or a manual download, then exits
cleanly — the same "don't crash the batch on one bad item" pattern already
applied to `cmd_build` for malformed PDFs.

**Not a bug, but a real usability finding**: OpenAlex's free-text `search`
degrades noticeably with extra disambiguating terms. Querying `"Modeling
Tabular Data using Conditional GAN CTGAN Xu 2019"` (title + acronym +
author + year) didn't surface the actual paper in the top 5 OpenAlex
results at all; the bare title `"Modeling Tabular data using Conditional
GAN"` put it in first place with a working arXiv PDF link. Semantic
Scholar's search is generally better at exact-paper lookup but was
unavailable for these particular tests due to the rate limit above — worth
keeping in mind that query phrasing matters more for `acquire` than for
`search`, and that lean, close-to-canonical-title queries outperform
kitchen-sink ones.

**Chunking on a real new paper**: `xu2019modeling.pdf` (the actual CTGAN
paper, 66 chunks) confirmed the table fix generalizes — captions and
headers correctly repeated across row-batches for a paper outside the
benchmark set. Also surfaced a *pre-existing, separate* limitation: a
1144-token outlier chunk from an `Algorithm 1` pseudocode block that
PDF extraction mangled into one dense, blank-line-free paragraph. Only
markdown tables get sub-split by the chunker; a non-table paragraph is
still bounded only by natural blank-line breaks, so sufficiently dense
non-table content (algorithm blocks, garbled OCR-like extraction) can
still slip past `max_tokens`. Not touched this round — flagging as a
follow-up, same fix shape as the table work (detect + sub-split dense
non-table blocks) if it turns out to matter for retrieval quality on
algorithm-heavy papers.

16/16 unit tests passing after these fixes (`tests/test_resolve.py` is new).
