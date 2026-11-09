"""One-way copy of a paper into an Obsidian vault for reading (#3).

<vault_dir>/<research>/<subtopic>/<key>.pdf plus <key>.md, a reading note
built from the companion metadata .md. Nothing is ever overwritten: a PDF or
note already in the vault is left as is, so annotations are safe and sending
twice is a no-op.
"""
from __future__ import annotations

import datetime
import shutil
from pathlib import Path


class VaultError(Exception):
    pass


def _safe_segment(name: str, what: str) -> str:
    # Subtopic can come from an MCP call: keep it a single folder name so it
    # can not write outside the vault.
    name = name.strip()
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        raise VaultError(f"invalid {what} {name!r}: use a plain folder name")
    return name


def _note(citation_key: str, companion: Path, research: str, subtopic: str) -> str:
    extra = (
        f"research: {research}\n"
        f"subtopic: {subtopic}\n"
        "status: to-read\n"
        f"sent: {datetime.date.today().isoformat()}\n"
    )
    text = companion.read_text() if companion.exists() else ""
    if text.startswith("---\n") and "\n---\n" in text[4:]:
        end = text.index("\n---\n", 4) + 1
        text = text[:end] + extra + text[end:]
    else:
        text = f"---\ncitation_key: {citation_key}\n{extra}---\n\n{text}"
    return f"{text.rstrip()}\n\n![[{citation_key}.pdf]]\n\n## Notes\n\n"


def send(cfg, paper: str, subtopic: str) -> dict:
    """Copy `paper` (a citation key or a path to a PDF) into the vault.
    Returns {citation_key, pdf, note, pdf_status, note_status}, each status
    "created" or "exists"."""
    if not cfg.obsidian.vault_dir:
        raise VaultError("set [obsidian] vault_dir in .paper-rag.toml")
    subtopic = _safe_segment(subtopic, "subtopic")
    research = _safe_segment(cfg.obsidian.research or cfg.root.resolve().name, "research")

    pdf = Path(paper)
    if pdf.suffix.lower() != ".pdf" or not pdf.is_file():
        pdf = cfg.root / cfg.corpus.papers_dir / f"{paper}.pdf"
    if not pdf.is_file():
        raise VaultError(f"no PDF for {paper!r} (looked for {pdf})")
    citation_key = pdf.stem

    target = cfg.root / Path(cfg.obsidian.vault_dir).expanduser() / research / subtopic
    target.mkdir(parents=True, exist_ok=True)
    out = {"citation_key": citation_key}

    vault_pdf = target / pdf.name
    out["pdf"] = str(vault_pdf)
    out["pdf_status"] = "exists" if vault_pdf.exists() else "created"
    if out["pdf_status"] == "created":
        shutil.copyfile(pdf, vault_pdf)

    vault_note = target / f"{citation_key}.md"
    out["note"] = str(vault_note)
    out["note_status"] = "exists" if vault_note.exists() else "created"
    if out["note_status"] == "created":
        vault_note.write_text(_note(citation_key, pdf.with_suffix(".md"), research, subtopic))
    return out
