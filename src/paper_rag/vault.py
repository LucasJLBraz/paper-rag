"""One-way copy of a paper into an Obsidian vault for reading (#3).

<vault_dir>/<research>/<subtopic>/<key>.pdf plus <key>.md, the paper's one
note (metadata, reading skeleton, abstract), which ZotFlow adopts as its
reading note; annotations (`<key>.zf.json`) are ZotFlow's. Each subtopic gets
an index note with the folder's reading table.
Nothing is ever overwritten: a PDF or card already in the vault is left as
is, and sending twice is a no-op.
"""
from __future__ import annotations

import datetime
import shutil
from importlib import resources
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


def _card(citation_key: str, companion: Path, research: str, subtopic: str) -> str:
    """The paper's single vault note: companion frontmatter + vault fields, and
    the reading skeleton (data/nota_paper.md) with the abstract filled in.
    `zotflow-local-attachment` makes ZotFlow adopt this note for the PDF
    instead of creating `@<key>`; on re-render ZotFlow keeps the frontmatter
    and the text inside the ZF_PERSIST regions."""
    text = companion.read_text() if companion.exists() else ""
    if text.startswith("---\n") and "\n---\n" in text[4:]:
        end = text.index("\n---\n", 4)
        head, body = text[4:end], text[end + 5 :]
    else:
        head, body = f"citation_key: {citation_key}", text
    # The companion's `pdf:` is the repo path; in the vault the PDF sits next
    # to the note.
    lines = [l for l in head.splitlines() if not l.startswith("pdf:")]
    lines += [
        f'pdf: "[[{citation_key}.pdf]]"',
        "tipo: paper",
        f"pesquisa: {research}",
        f"subtopico: {subtopic}",
        f"data: {datetime.date.today().isoformat()}",
        "zotflow-locked: true",
        f'zotflow-local-attachment: "[[{citation_key}.pdf]]"',
        # Keshav's three reading passes, ticked in the vault's Leitura.base.
        "visao_geral: false",
        "conteudo: false",
        "a_fundo: false",
    ]
    abstract = body.split("## Abstract", 1)[-1].strip() if "## Abstract" in body else body.strip()
    note = (resources.files("paper_rag.data") / "nota_paper.md").read_text()
    for token, value in {
        "{{KEY}}": citation_key,
        "{{SOBRE}}": f"### Abstract\n\n{abstract}" if abstract else "",
        "{{FOCO}}": "", "{{FRASE}}": "", "{{IDEIAS}}": "", "{{GRIFOS}}": "",
    }.items():
        note = note.replace(token, value)
    return "---\n" + "\n".join(lines) + "\n---\n" + note


INDEX = """---
tipo: indice
---
# Papers desta pasta

Clique no paper para abrir a nota dele (frase, passagens, ideias e grifos). O 📎 no topo da nota abre o PDF. \
Marque as passagens aqui ou nas propriedades da nota.

![[Leitura.base#Desta pasta]]
"""


def _ensure_index(folder: Path) -> None:
    """One table of the folder's papers per subtopic, unless a note there
    already embeds it."""
    if any("Leitura.base#Desta pasta" in f.read_text() for f in folder.glob("*.md")):
        return
    (folder / "00 Papers.md").write_text(INDEX)


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
        vault_note.write_text(_card(citation_key, pdf.with_suffix(".md"), research, subtopic))
    _ensure_index(target)
    return out
