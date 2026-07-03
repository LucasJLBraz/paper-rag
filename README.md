# paper-rag

Local, embedded RAG over a folder of PDFs, built for Claude Code research
repos: retrieve the relevant chunks of a paper instead of re-reading whole
PDFs on every synthesis turn, and pull in new open-access papers without ad
hoc scraping.

- **Local-only embeddings** — `sentence-transformers` (default:
  `intfloat/multilingual-e5-small`) or Ollama. No hosted embedding API is
  ever called.
- **Embedded vector store** — [LanceDB](https://lancedb.github.io/lancedb/),
  file-based, no server process. Treated as a disposable build artifact,
  never committed — see [Why the index isn't portable](#why-the-index-isnt-portable).
- **Open-access acquisition** — chains Semantic Scholar -> OpenAlex ->
  Unpaywall-by-DOI, stops at the first legally open PDF.
- **Claude Code native** — an MCP server (`search_papers`,
  `list_indexed_papers`) plus a CLI, both installed by one `paper-rag init`
  run per project.

## Install

```bash
pipx install "paper-rag @ git+https://github.com/LucasJLBraz/paper-rag.git"
```

(or `pip install -e .` from a local clone for development). Requires
Python >= 3.10.

## Quickstart

```bash
cd your-research-repo
paper-rag init                 # writes .paper-rag.toml, .mcp.json, .claude/skills/paper-rag/
# edit .paper-rag.toml: set acquire.contact_email and corpus.papers_dir
paper-rag build                 # ingest every PDF under papers_dir
paper-rag search "your query"   # sanity-check retrieval from the shell
```

Inside Claude Code, `.mcp.json` registers the `paper-rag` MCP server so
`search_papers` / `list_indexed_papers` are called as native tools — no
shelling out needed. The bundled Claude Code skill (copied into
`.claude/skills/paper-rag/` by `init`) documents when to use retrieval vs.
a full PDF read vs. acquisition.

## How it works

```
PDF -> markdown (pymupdf4llm)
     -> section-aware chunks (heading-bounded, References dropped, token-capped with overlap)
     -> local embeddings (sentence-transformers / Ollama)
     -> LanceDB (embedded, file-based)
```

`paper-rag build` is incremental — it hashes each PDF and skips ones it's
already indexed (tracked in `<index_dir>/manifest.json`). Use `--rebuild`
to force full re-ingestion, e.g. after switching embedding models.

## Performance

Measured on the project's own dev corpus (7 papers, 625 chunks, Intel
i5-1135G7 laptop CPU, no GPU) — real numbers from this corpus, not
estimates. Full investigation, including what didn't work, in
[HANDOFF.md](HANDOFF.md).

**Token usage, vs. Claude reading the full paper directly:**

| | tokens |
|---|---|
| Full paper (markdown, as Claude would read it directly) | ~28,000 (avg, this corpus) |
| One `search` query (top-5 chunks) | ~1,250 |
| **Reduction** | **~22x** |

Even a research session running ~10 targeted queries against one paper —
a realistic upper bound for pulling out several specific facts — costs
~12,500 tokens: still well under a single full read, and each query
returns exactly the relevant passage instead of requiring Claude to
re-scan the whole paper's context on every turn.

**Latency:**

| operation | cost |
|---|---|
| `paper-rag build` (embedding) | ~0.2-0.3s/chunk — a 625-chunk/7-paper corpus rebuilds cold in ~2 min |
| `paper-rag search` (CLI, cold process) | ~10-13s, almost entirely one-time model load |
| `search_papers` via the MCP server (warm — the primary integration) | ~20ms/query after the one-time server-startup load |

The CLI pays the embedding model's load cost on every invocation since
each run is a fresh process; the MCP server (registered by `paper-rag
init`, the intended way to use this from Claude Code) loads it once at
startup and stays warm for the session, so query latency there is
effectively just the vector search itself.

## Why the index isn't portable

The vector index is deliberately **not** meant to be copied between
machines or committed to git. It's a deterministic, disposable build
artifact of the PDFs + config — regenerating it locally (`paper-rag build`)
is fast and avoids the two real failure modes of shipping a vector store as
a file: binary-blob git bloat, and silent staleness if it was built with a
different embedding model than the one currently configured (`PaperIndex`
refuses to open a mismatched index rather than returning garbage results —
see `ingest/index.py`).

What *is* portable, and what actually matters: the PDFs and their
companion `.md` metadata files, and this package itself.

## Configuration (`.paper-rag.toml`)

```toml
[corpus]
papers_dir = "references/Papers"

[index]
dir = ".rag_index"
table_name = "chunks"

[embedding]
backend = "sentence-transformers"   # or "ollama"
model = "intfloat/multilingual-e5-small"
ollama_host = "http://localhost:11434"

[chunking]
max_tokens = 400
overlap_tokens = 60

[acquire]
contact_email = "you@example.com"   # required by Unpaywall
semantic_scholar_api_key = ""       # optional, raises rate limit
```

`paper-rag` looks for `.paper-rag.toml` by walking up from the current
directory, so it works from any subdirectory of the repo.

## Companion metadata files

Every acquired/ingested paper is expected to have a `<citation_key>.md`
sitting next to its PDF with frontmatter:

```yaml
---
citation_key: kim2025epic
doi: 10.xxxx/yyyy
title: "..."
authors:
  - Jinhee Kim
published: 2025
source: semantic_scholar
source_url: https://...
pdf: references/Papers/kim2025epic.pdf
---

## Abstract

...
```

`paper-rag acquire` writes this automatically. If you're pulling in arXiv
papers, use a dedicated arXiv-fetch tool for those instead (this schema is
compatible with one) — `paper-rag acquire` is for everything Semantic
Scholar / OpenAlex / Unpaywall can resolve that arXiv-specific tooling
can't.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
