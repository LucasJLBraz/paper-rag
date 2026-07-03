---
name: paper-rag
description: Local hybrid (dense + BM25) semantic search over this repo's configured paper corpus (retrieval instead of full-text PDF reads) plus open-access paper acquisition beyond arXiv (Semantic Scholar, OpenAlex, Unpaywall). Use this to find relevant passages across the paper corpus ("what do our papers say about X") instead of re-reading whole PDFs, and to download a non-arXiv paper (journal PDF, DOI) into the papers directory with a companion metadata file. If this project has an arxiv-paper-fetch skill, use that for arXiv papers specifically — this skill defers to it rather than duplicating it.
---

# paper-rag

Wraps a local, embedded RAG pipeline (the `paper-rag` package) so literature
synthesis pulls only the relevant chunks of a paper instead of the whole
PDF, and so non-arXiv open-access papers can be found and downloaded
without ad hoc curl/requests.

## When to use which tool

- **Retrieval** (cross-paper synthesis, "what does paper X say about Y"):
  prefer the `search_papers` / `list_indexed_papers` MCP tools (registered
  via this repo's `.mcp.json`) — call them directly, no shell-out needed.
- **Ingestion** (a new PDF landed in the papers directory, or the index is
  stale/missing): run `paper-rag build`.
- **Acquisition of a non-arXiv paper**: run `paper-rag acquire "<title or
  query>"`. If this repo has an `arxiv-paper-fetch` skill and the paper is
  on arXiv, use that instead — don't route arXiv papers through this tool.
- **Close reading of one specific paper** (verifying an exact quote,
  citation-integrity checks): still read the PDF directly. Retrieval is for
  synthesis across/within papers, not a replacement for checking a precise
  claim against source text.

## Setup (one-time per machine)

```bash
pipx install "paper-rag @ git+https://github.com/LucasJLBraz/paper-rag.git"
```

Then, from inside any repo you want to use it in:

```bash
paper-rag init
```

`init` writes `.paper-rag.toml` if missing, merges a `paper-rag` entry into
`.mcp.json` (without touching any other servers already registered there),
adds the configured index directory to `.gitignore` if it isn't covered
already, and copies this SKILL.md into `.claude/skills/paper-rag/` — this
file is package-owned and gets re-synced to the installed version on every
`init`, so don't hand-edit it. Edit `.paper-rag.toml`'s
`acquire.contact_email` before using `acquire` — Unpaywall requires it.

First run of `build` or the MCP server downloads the configured embedding
model's weights (default `intfloat/multilingual-e5-small`, ~470MB) from
Hugging Face — a one-time, machine-wide fetch (shared across every project
via the local HF cache), not project data leaving the machine.

If `init` warned that `paper-rag-mcp` isn't on PATH, the MCP server
registered in `.mcp.json` won't launch from inside Claude Code until that's
fixed — see the warning's own instructions (`pipx ensurepath`, or activate
the right venv) before assuming retrieval is broken.

## Workflow

### 1. Keep the index current

```bash
paper-rag build
```

Incremental by default (hashes each PDF, skips unchanged ones). Use
`--rebuild` to force full re-ingestion, e.g. after changing the embedding
model in `.paper-rag.toml`.

### 2. Retrieve

Prefer the MCP tools when working inside Claude Code. From a shell:

```bash
paper-rag search "how did KGSynX validate persona fidelity?" -k 5
```

### 3. Acquire a non-arXiv paper

```bash
paper-rag acquire "Comprehensive evaluation framework for synthetic tabular data in health"
```

Tries Semantic Scholar, then OpenAlex, then Unpaywall-by-DOI, and stops at
the first legally open-access PDF. If none is found, it says so — don't
fall back to scraping a paywalled source.

### 4. Tell the user what landed

Report the citation key and a one-line description, and if it's backing a
specific claim in a doc, say so explicitly — the metadata file doesn't
record *why* a paper was pulled in.

## Notes

- The vector index is git-ignored on purpose — it's a disposable build
  artifact of the git-tracked PDFs/metadata, regenerated locally with
  `build`. Never commit it.
- If `search` returns nothing, the index probably hasn't been built yet —
  run `build` first, don't assume the corpus is empty.
- Acquisition APIs (Semantic Scholar/OpenAlex/Unpaywall) only ever handle
  *public literature* — don't repurpose this tool for actual
  dataset/patient records in projects with data-locality constraints.
