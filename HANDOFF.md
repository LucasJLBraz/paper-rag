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
