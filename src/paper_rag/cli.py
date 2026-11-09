"""CLI: paper-rag init | build | search | discover | get | acquire | add | vault send

    paper-rag init
    paper-rag build [--rebuild]
    paper-rag search "<query>" [-k N] [--paper CITATION_KEY]
    paper-rag discover "<query>" [--limit N]
    paper-rag get <id> [<id> ...] [--citation-key KEY]
    paper-rag acquire "<title|DOI|arXiv id>" [--citation-key KEY] [--accept-low-confidence]
    paper-rag add <file.pdf> [--doi DOI] [--citation-key KEY]
    paper-rag vault send <citation-key|file.pdf> --subtopic NAME
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from importlib import resources
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

from .config import load_config
from .ingest.chunk import chunk_markdown
from .ingest.convert import pdf_to_markdown
from .ingest.embed import build_backend
from .ingest.index import PaperIndex
from .search import hybrid_search


def _get_version() -> str:
    try:
        return _pkg_version("paper-rag")
    except PackageNotFoundError:
        return "unknown (not installed as a package)"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _open_index(cfg):
    backend = build_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.ollama_host)
    index_dir = cfg.root / cfg.index.dir
    index = PaperIndex(index_dir, cfg.index.table_name, backend.dim, backend.name)
    return backend, index, index.open_or_create()


def cmd_init(args):
    """One-shot repo setup: writes `.paper-rag.toml` (only if absent), always
    refreshes `.claude/skills/paper-rag/SKILL.md` and the `paper-rag` entry
    in `.mcp.json` to the installed version, and adds the index dir to
    `.gitignore`. Safe to re-run any time — never overwrites the config."""
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
    new_skill_content = (data / "SKILL.md").read_text()
    if skill_path.exists() and skill_path.read_text() == new_skill_content:
        print(f"{skill_path} already up to date")
    else:
        was_present = skill_path.exists()
        skill_path.write_text(new_skill_content)
        if was_present:
            print(f"Updated {skill_path} (previous content differed — this file is package-owned "
                  "and always synced to the installed version; keep project-specific notes elsewhere)")
        else:
            print(f"Wrote {skill_path}")

    mcp_path = repo_root / ".mcp.json"
    mcp_config = json.loads(mcp_path.read_text()) if mcp_path.exists() else {}
    mcp_config.setdefault("mcpServers", {})
    mcp_config["mcpServers"]["paper-rag"] = {"command": "paper-rag-mcp"}
    mcp_path.write_text(json.dumps(mcp_config, indent=2) + "\n")
    print(f"Wrote {mcp_path} (paper-rag MCP server registered; other servers, if any, left untouched)")

    if shutil.which("paper-rag-mcp") is None:
        print(
            "  warning: `paper-rag-mcp` isn't on PATH in this shell, so Claude Code may not be able "
            "to launch the MCP server just registered in .mcp.json. If you installed with pipx, run "
            "`pipx ensurepath` and open a new terminal; if you're using a dev venv (`pip install -e .`), "
            "make sure it's active in whatever shell/environment launches Claude Code.",
            file=sys.stderr,
        )

    # The vector index is a disposable, deterministic build artifact (see
    # README's "Why the index isn't portable") — never let it get committed
    # by accident via a bare `git add .`.
    gitignore_path = repo_root / ".gitignore"
    index_dir = load_config(str(config_path)).index.dir
    entry = index_dir if index_dir.endswith("/") else f"{index_dir}/"
    existing_lines = gitignore_path.read_text().splitlines() if gitignore_path.exists() else []
    if entry not in existing_lines and index_dir not in existing_lines:
        with gitignore_path.open("a") as f:
            if existing_lines and existing_lines[-1] != "":
                f.write("\n")
            f.write(f"{entry}\n")
        print(f"Added {entry} to {gitignore_path} (disposable vector index — never commit it)")

    print("\nNext steps:")
    print(f"  1. Edit {config_path} — set acquire.contact_email and corpus.papers_dir")
    print("  2. Drop PDFs into the configured papers_dir")
    print("  3. Run `paper-rag build`")


def cmd_build(args):
    """Incremental ingest: hashes every PDF in `papers_dir`, skips ones
    already in the manifest (unless `--rebuild`), and prunes citation_keys
    whose PDF no longer exists from both the index and the manifest. A
    single paper's conversion/embedding failure is logged and skipped
    rather than aborting the whole batch."""
    cfg = load_config(args.config)
    papers_dir = cfg.root / cfg.corpus.papers_dir
    index_dir = cfg.root / cfg.index.dir
    index_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = index_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    backend, index, table = _open_index(cfg)

    pdfs = []
    for p in sorted(papers_dir.glob("*.pdf")):
        with p.open("rb") as f:
            magic = f.read(5)
        if magic == b"%PDF-":
            pdfs.append(p)
        else:
            # An acquire/get that saved an anti-bot or cookie-wall page under a
            # .pdf name (or an empty file) would otherwise be converted and
            # indexed as if it were the paper.
            print(f"Skipping {p.name}: not a PDF (starts with {magic!r}); replace it with the real file.", file=sys.stderr)

    # Prune entries for papers that no longer have a PDF on disk. Checks both
    # manifest.json and the live table's citation_keys, since a paper can end
    # up in one but not the other (e.g. a run interrupted after `index.add`
    # but before the manifest was flushed).
    present_keys = {p.stem for p in pdfs}
    known_keys = set(manifest.keys()) | index.distinct_citation_keys(table)
    orphaned_keys = known_keys - present_keys
    for citation_key in sorted(orphaned_keys):
        print(f"Pruning {citation_key} (PDF no longer present) ...", flush=True)
        index.delete_citation_key(table, citation_key)
        manifest.pop(citation_key, None)
    if orphaned_keys:
        manifest_path.write_text(json.dumps(manifest, indent=2))

    if not pdfs:
        print(f"No PDFs found in {papers_dir}", file=sys.stderr)
        return

    failures: list[tuple[str, str]] = []
    attempted = 0
    for pdf_path in pdfs:
        citation_key = pdf_path.stem
        file_hash = _hash_file(pdf_path)
        if not args.rebuild and manifest.get(citation_key) == file_hash:
            continue

        print(f"Ingesting {citation_key} ...", flush=True)
        attempted += 1
        paper_start = time.monotonic()
        try:
            markdown = pdf_to_markdown(pdf_path, timeout_seconds=cfg.ingest.pdf_timeout_seconds)
            chunks = chunk_markdown(markdown, cfg.chunking.max_tokens, cfg.chunking.overlap_tokens)
            if not chunks:
                print(f"  FAILED: no chunks extracted from {pdf_path.name}", file=sys.stderr)
                failures.append((citation_key, "no chunks extracted"))
                continue
            print(f"  {len(chunks)} chunks to embed (this is the slow part on CPU) ...", flush=True)

            vectors = backend.embed([c.text for c in chunks])
        except Exception as e:
            # A single bad PDF (corrupt xref/dict entries, non-text scans,
            # ...) must not take the whole batch down. Skipped papers are
            # NOT written to the manifest, so the next `build` retries them.
            print(f"  FAILED: {e!r} — skipping this paper, see HANDOFF.md", file=sys.stderr)
            failures.append((citation_key, repr(e)))
            continue

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
        # Flush after every paper, not just at the end of the loop — a
        # kill/crash mid-batch must not lose the manifest bookkeeping for
        # papers that already completed and are safely in the index.
        manifest_path.write_text(json.dumps(manifest, indent=2))
        elapsed = time.monotonic() - paper_start
        print(f"  {len(rows)} chunks indexed ({elapsed:.1f}s)", flush=True)

    if failures:
        # Exit non-zero: a "successful" build that silently left papers out
        # makes search look healthy while answering from a stale corpus (#4).
        print(f"\n{len(failures)} of {attempted} paper(s) failed to ingest and were skipped:", file=sys.stderr)
        for key, err in failures:
            print(f"  - {key}: {err}", file=sys.stderr)
        sys.exit(1)


def cmd_search(args):
    """Embed `args.query`, run `hybrid_search` against the local index, and
    print the top-k results with the fused score plus whichever raw
    per-method signal (vector_distance/bm25_score) each result matched on."""
    cfg = load_config(args.config)
    backend, index, table = _open_index(cfg)
    [vector] = backend.embed([args.query], is_query=True)
    results = hybrid_search(index, table, args.query, vector, k=args.k, citation_key=args.paper)
    if not results:
        print("No results. Has `paper-rag build` been run yet?", file=sys.stderr)
        return
    print(
        "(score is a rank-fusion artifact, not a similarity measure — most top-k results cluster near "
        "the same value regardless of match strength; lower vector_distance and higher bm25_score are "
        "the actual per-method confidence signals, where present)",
        file=sys.stderr,
    )
    for r in results:
        extras = []
        if "vector_distance" in r:
            extras.append(f"vector_distance={r['vector_distance']:.4f}")
        if "bm25_score" in r:
            extras.append(f"bm25_score={r['bm25_score']:.4f}")
        extra_str = f"  ({', '.join(extras)})" if extras else ""
        print(f"[{r['citation_key']} / {r['section']}]  (score={r['score']:.4f}){extra_str}")
        print(r["text"][:400].strip())
        print()


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


def cmd_get(args):
    """Download one or more candidates from the last `discover` call by id,
    reading `discover_cache.json` and resolving via Unpaywall on demand only
    for the ids actually requested. Exits non-zero if any requested id
    fails (missing from cache, or download error)."""
    cfg = load_config(args.config)
    from .acquire import cache, get as get_mod

    ids = list(dict.fromkeys(args.ids))

    if args.citation_key and len(ids) > 1:
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
    for result_id in ids:
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


def _save_paper(cfg, hit: dict, citation_key: str | None, source: str, source_url: str, pdf_content: bytes | None):
    """Write `<key>.pdf` (when pdf_content is given) and `<key>.md` into
    papers_dir. Returns (pdf_path, md_path, citation_key)."""
    from .acquire import metadata

    title = hit.get("title") or "untitled"
    citation_key = citation_key or metadata.make_citation_key(title, hit.get("authors", []), hit.get("year"))
    papers_dir = cfg.root / cfg.corpus.papers_dir
    papers_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = papers_dir / f"{citation_key}.pdf"
    md_path = papers_dir / f"{citation_key}.md"
    if pdf_content is not None:
        pdf_path.write_bytes(pdf_content)
    metadata.write_metadata(
        md_path, citation_key, title, hit.get("authors", []), hit.get("year"), hit.get("doi"),
        source, source_url, pdf_path.relative_to(cfg.root), hit.get("abstract") or "",
    )
    return pdf_path, md_path, citation_key


def cmd_acquire(args):
    """Resolver for a paper you can already name. A DOI or arXiv id
    (bare, prefixed or as a URL) is resolved exactly via Crossref + Unpaywall
    or the arXiv API, with no keyword search. A title goes through
    `find_oa_pdf_candidates` (Semantic Scholar -> OpenAlex -> Unpaywall), and
    candidates whose title matches the query poorly are rejected unless
    `--accept-low-confidence` is given. Writes the PDF and its companion `.md`
    into `papers_dir`. Not a topic search — use `discover`/`get` for that."""
    cfg = load_config(args.config)
    from .acquire import download, resolve

    accept_low = getattr(args, "accept_low_confidence", False)
    exact_meta = None
    identifier = resolve.parse_identifier(args.query)
    if identifier:
        kind, ident = identifier
        exact_meta, candidates = resolve.resolve_exact(kind, ident, cfg.acquire.contact_email)
        if exact_meta is None:
            print(f"{kind} {ident} not found. Nothing written.", file=sys.stderr)
            sys.exit(1)
    else:
        candidates = resolve.find_oa_pdf_candidates(
            args.query, cfg.acquire.contact_email, cfg.acquire.semantic_scholar_api_key
        )
        if not candidates:
            print("No legally open-access PDF found via Semantic Scholar / OpenAlex / Unpaywall.", file=sys.stderr)
            sys.exit(1)
        confident = [c for c in candidates if c.get("relevance", 1.0) >= resolve.ACQUIRE_MIN_RELEVANCE]
        if not confident and not accept_low:
            # A keyword search always returns something; writing it would put
            # a different paper into papers_dir (#5).
            print("No candidate's title matches the query closely enough. Nothing written. Candidates:", file=sys.stderr)
            for c in candidates:
                print(f"  - \"{c.get('title')}\" ({c.get('year') or 'n.d.'}) relevance={c['relevance']:.2f}", file=sys.stderr)
            print(
                "Pass the exact title or a DOI, use `paper-rag discover` for a topical search, "
                "or re-run with --accept-low-confidence if one of these is the paper.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not accept_low:
            candidates = confident

    hit = None
    pdf_content = None
    for candidate in candidates:
        try:
            pdf_content = download.fetch_pdf_bytes(candidate["pdf_url"])
            hit = candidate
            break
        except Exception as e:
            print(
                f"  ({candidate['source']} candidate {candidate['pdf_url']} failed to download: {e!r} "
                "— trying the next candidate)",
                file=sys.stderr,
            )

    papers_dir = cfg.root / cfg.corpus.papers_dir
    if hit is None:
        if exact_meta is not None:
            pdf_path, md_path, _ = _save_paper(cfg, exact_meta, args.citation_key, "crossref", "", None)
            print(
                f"No open PDF for \"{exact_meta.get('title')}\". Metadata written to {md_path.relative_to(cfg.root)}. "
                f"Download the PDF yourself and run: paper-rag add <file.pdf> --doi {exact_meta.get('doi')}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(
            f"Found {len(candidates)} candidate(s) but none downloaded successfully. "
            "The publisher(s) may be blocking scripted downloads even though the PDF is open-access. "
            "Download it manually and run `paper-rag add <file.pdf> --doi <doi>`, or place it in "
            f"{papers_dir}.",
            file=sys.stderr,
        )
        sys.exit(1)

    pdf_path, md_path, citation_key = _save_paper(
        cfg, {**hit, "title": hit.get("title") or args.query}, args.citation_key, hit["source"], hit["pdf_url"], pdf_content
    )
    print(f"Downloaded via {hit['source']}: {pdf_path.relative_to(cfg.root)}")
    print(f"Matched: \"{hit.get('title') or '(no title returned)'}\" ({hit.get('year') or 'n.d.'})")
    if hit.get("relevance", 1.0) < resolve.ACQUIRE_MIN_RELEVANCE:
        print(
            f"  WARNING: low title overlap (relevance={hit['relevance']:.2f}), accepted because of "
            "--accept-low-confidence. Verify this is the paper you meant before citing it.",
            file=sys.stderr,
        )
    print(f"Metadata: {md_path.relative_to(cfg.root)}")
    print(f"Citation key: {citation_key}")


def cmd_add(args):
    """Manual import: copy a PDF the user downloaded (for example a paywalled
    paper) into papers_dir, with its `.md` filled from Crossref when --doi is
    given."""
    cfg = load_config(args.config)
    from .acquire import crossref

    src = Path(args.pdf)
    with src.open("rb") as f:
        if f.read(5) != b"%PDF-":
            print(f"{src} is not a PDF. Nothing written.", file=sys.stderr)
            sys.exit(1)
    if args.doi:
        meta = crossref.lookup(args.doi, cfg.acquire.contact_email)
        if meta is None:
            print(f"DOI {args.doi} not found in Crossref. Nothing written.", file=sys.stderr)
            sys.exit(1)
    else:
        meta = {"title": src.stem}
    pdf_path, md_path, citation_key = _save_paper(cfg, meta, args.citation_key, "manual", "", src.read_bytes())
    print(f"Added: {pdf_path.relative_to(cfg.root)}")
    print(f"Metadata: {md_path.relative_to(cfg.root)}")
    print(f"Citation key: {citation_key}")


def cmd_vault_send(args):
    """Copy a paper (PDF + reading note) into the Obsidian vault."""
    from .vault import VaultError, send

    cfg = load_config(args.config)
    try:
        r = send(cfg, args.paper, args.subtopic)
    except VaultError as e:
        print(f"vault send: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"PDF ({r['pdf_status']}): {r['pdf']}")
    print(f"Note ({r['note_status']}): {r['note']}")


def main():
    # Piped/redirected stdout is block-buffered by default, which makes a
    # slow-but-working `build` (CPU embedding is the dominant cost — see
    # HANDOFF.md) look hung for minutes at a time. Force line buffering so
    # progress is visible as it happens.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="Local RAG + open-access acquisition for a paper corpus")
    parser.add_argument("--version", action="version", version=f"paper-rag {_get_version()}")
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

    p_discover = sub.add_parser(
        "discover", help="Topical search across Semantic Scholar/OpenAlex; lists candidates without downloading"
    )
    p_discover.add_argument("query", help="Free-text topic description")
    p_discover.add_argument("--limit", type=int, default=10)
    p_discover.set_defaults(func=cmd_discover)

    p_get = sub.add_parser("get", help="Download one or more candidates from the last `discover` by id")
    p_get.add_argument("ids", type=int, nargs="+")
    p_get.add_argument("--citation-key", default=None, help="Override the auto-generated citation key (single id only)")
    p_get.set_defaults(func=cmd_get)

    p_acquire = sub.add_parser("acquire", help="Find + download a legally open-access paper")
    p_acquire.add_argument("query", help="Exact title, DOI, or arXiv id/URL")
    p_acquire.add_argument("--citation-key", default=None, help="Override the auto-generated citation key")
    p_acquire.add_argument(
        "--accept-low-confidence", action="store_true", help="Download even when no title matches the query closely"
    )
    p_acquire.set_defaults(func=cmd_acquire)

    p_add = sub.add_parser("add", help="Import a PDF you downloaded yourself, with metadata from Crossref")
    p_add.add_argument("pdf")
    p_add.add_argument("--doi", default=None, help="Fill the .md metadata from Crossref")
    p_add.add_argument("--citation-key", default=None, help="Override the auto-generated citation key")
    p_add.set_defaults(func=cmd_add)

    p_vault = sub.add_parser("vault", help="Obsidian vault actions")
    vault_sub = p_vault.add_subparsers(dest="vault_command", required=True)
    p_send = vault_sub.add_parser("send", help="Copy a paper (PDF + reading note) to <vault_dir>/<research>/<subtopic>/")
    p_send.add_argument("paper", help="Citation key, or path to a PDF")
    p_send.add_argument("--subtopic", required=True, help="Folder under the research, for example features")
    p_send.set_defaults(func=cmd_vault_send)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
