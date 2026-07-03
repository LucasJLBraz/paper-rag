"""CLI: paper-rag init | build | search | acquire

    paper-rag init
    paper-rag build [--rebuild]
    paper-rag search "<query>" [-k N] [--paper CITATION_KEY]
    paper-rag acquire "<query>" [--citation-key KEY]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from importlib import resources
from pathlib import Path

from .config import load_config
from .ingest.chunk import chunk_markdown
from .ingest.convert import pdf_to_markdown
from .ingest.embed import build_backend
from .ingest.index import PaperIndex


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _open_index(cfg):
    backend = build_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.ollama_host)
    index_dir = cfg.root / cfg.index.dir
    index = PaperIndex(index_dir, cfg.index.table_name, backend.dim, backend.name)
    return backend, index, index.open_or_create()


def cmd_init(args):
    repo_root = Path(args.dir).resolve() if args.dir else Path.cwd()
    data = resources.files("paper_rag.data")

    config_path = repo_root / ".paper-rag.toml"
    if config_path.exists():
        print(f"Skipping .paper-rag.toml — already exists at {config_path}")
    else:
        template = (data / "paper-rag.toml.example").read_text()
        if args.email:
            template = template.replace("you@example.com", args.email)
        config_path.write_text(template)
        print(f"Wrote {config_path}")

    skill_dir = repo_root / ".claude" / "skills" / "paper-rag"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text((data / "SKILL.md").read_text())
    print(f"Wrote {skill_path}")

    mcp_path = repo_root / ".mcp.json"
    mcp_config = json.loads(mcp_path.read_text()) if mcp_path.exists() else {}
    mcp_config.setdefault("mcpServers", {})
    mcp_config["mcpServers"]["paper-rag"] = {"command": "paper-rag-mcp"}
    mcp_path.write_text(json.dumps(mcp_config, indent=2) + "\n")
    print(f"Wrote {mcp_path} (paper-rag MCP server registered; other servers, if any, left untouched)")

    print("\nNext steps:")
    print(f"  1. Edit {config_path} — set acquire.contact_email and corpus.papers_dir")
    print("  2. Drop PDFs into the configured papers_dir")
    print("  3. Run `paper-rag build`")


def cmd_build(args):
    cfg = load_config(args.config)
    papers_dir = cfg.root / cfg.corpus.papers_dir
    index_dir = cfg.root / cfg.index.dir
    index_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = index_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    backend, index, table = _open_index(cfg)

    pdfs = sorted(papers_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {papers_dir}", file=sys.stderr)
        return

    for pdf_path in pdfs:
        citation_key = pdf_path.stem
        file_hash = _hash_file(pdf_path)
        if not args.rebuild and manifest.get(citation_key) == file_hash:
            continue

        print(f"Ingesting {citation_key} ...")
        markdown = pdf_to_markdown(pdf_path)
        chunks = chunk_markdown(markdown, cfg.chunking.max_tokens, cfg.chunking.overlap_tokens)
        if not chunks:
            print(f"  warning: no chunks extracted from {pdf_path.name}", file=sys.stderr)
            continue

        vectors = backend.embed([c.text for c in chunks])
        index.delete_citation_key(table, citation_key)
        rows = [
            {
                "chunk_id": f"{citation_key}::{i}",
                "citation_key": citation_key,
                "section": c.section,
                "text": c.text,
                "token_count": c.token_count,
                "pdf_path": str(pdf_path.relative_to(cfg.root)),
                "embedding_model": backend.name,
                "vector": vec,
            }
            for i, (c, vec) in enumerate(zip(chunks, vectors))
        ]
        index.add(table, rows)
        manifest[citation_key] = file_hash
        print(f"  {len(rows)} chunks indexed")

    manifest_path.write_text(json.dumps(manifest, indent=2))


def cmd_search(args):
    cfg = load_config(args.config)
    backend, index, table = _open_index(cfg)
    [vector] = backend.embed([args.query])
    results = index.search(table, vector, k=args.k, citation_key=args.paper)
    if not results:
        print("No results. Has `paper-rag build` been run yet?", file=sys.stderr)
        return
    for r in results:
        print(f"[{r['citation_key']} / {r['section']}]  (dist={r['_distance']:.3f})")
        print(r["text"][:400].strip())
        print()


def cmd_acquire(args):
    cfg = load_config(args.config)
    from .acquire import download, metadata, resolve

    hit = resolve.find_oa_pdf(args.query, cfg.acquire.contact_email, cfg.acquire.semantic_scholar_api_key)
    if not hit:
        print("No legally open-access PDF found via Semantic Scholar / OpenAlex / Unpaywall.", file=sys.stderr)
        sys.exit(1)

    citation_key = args.citation_key or metadata.make_citation_key(
        hit.get("title") or args.query, hit.get("authors", []), hit.get("year")
    )
    papers_dir = cfg.root / cfg.corpus.papers_dir
    papers_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = papers_dir / f"{citation_key}.pdf"
    md_path = papers_dir / f"{citation_key}.md"

    pdf_path.write_bytes(download.fetch_pdf_bytes(hit["pdf_url"]))
    metadata.write_metadata(
        md_path,
        citation_key,
        hit.get("title") or args.query,
        hit.get("authors", []),
        hit.get("year"),
        hit.get("doi"),
        hit["source"],
        hit["pdf_url"],
        pdf_path.relative_to(cfg.root),
        hit.get("abstract") or "",
    )
    print(f"Downloaded via {hit['source']}: {pdf_path.relative_to(cfg.root)}")
    print(f"Metadata: {md_path.relative_to(cfg.root)}")
    print(f"Citation key: {citation_key}")


def main():
    parser = argparse.ArgumentParser(description="Local RAG + open-access acquisition for a paper corpus")
    parser.add_argument("--config", default=None, help="Path to .paper-rag.toml (default: search upward from cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="One-shot configure the current repo: .paper-rag.toml, .mcp.json, SKILL.md")
    p_init.add_argument("--dir", default=None, help="Target repo root (default: cwd)")
    p_init.add_argument("--email", default=None, help="Pre-fill acquire.contact_email")
    p_init.set_defaults(func=cmd_init)

    p_build = sub.add_parser("build", help="Ingest new/changed PDFs into the local index")
    p_build.add_argument("--rebuild", action="store_true", help="Re-ingest all PDFs, ignoring the manifest cache")
    p_build.set_defaults(func=cmd_build)

    p_search = sub.add_parser("search", help="Query the local index")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=5)
    p_search.add_argument("--paper", default=None, help="Restrict results to one citation_key")
    p_search.set_defaults(func=cmd_search)

    p_acquire = sub.add_parser("acquire", help="Find + download a legally open-access paper")
    p_acquire.add_argument("query", help="Title or free-text query")
    p_acquire.add_argument("--citation-key", default=None, help="Override the auto-generated citation key")
    p_acquire.set_defaults(func=cmd_acquire)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
