"""Config loader: finds .paper-rag.toml by walking up from the current directory."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # stdlib on Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # Python 3.10 fallback


@dataclass
class CorpusConfig:
    papers_dir: str = "references/Papers"


@dataclass
class IndexConfig:
    dir: str = ".rag_index"
    table_name: str = "chunks"


@dataclass
class EmbeddingConfig:
    backend: str = "sentence-transformers"
    model: str = "intfloat/multilingual-e5-small"
    ollama_host: str = "http://localhost:11434"


@dataclass
class ChunkingConfig:
    max_tokens: int = 400
    overlap_tokens: int = 60


@dataclass
class IngestConfig:
    # Bounds a single PDF's conversion time (SIGALRM, Unix-only) so one
    # malformed PDF can't hang an entire batch build. See ingest/convert.py.
    pdf_timeout_seconds: int = 120


@dataclass
class AcquireConfig:
    contact_email: str = ""
    semantic_scholar_api_key: str = ""


@dataclass
class Config:
    root: Path
    corpus: CorpusConfig = field(default_factory=CorpusConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    acquire: AcquireConfig = field(default_factory=AcquireConfig)


def _find_config(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        f = candidate / ".paper-rag.toml"
        if f.exists():
            return f
    raise FileNotFoundError(
        "No .paper-rag.toml found in this or any parent directory. "
        "Copy tools/paper-rag/paper-rag.toml.example to your repo root as .paper-rag.toml."
    )


def load_config(path: str | None = None) -> Config:
    config_path = Path(path) if path else _find_config(Path.cwd())
    data = tomllib.loads(config_path.read_text())
    return Config(
        root=config_path.parent,
        corpus=CorpusConfig(**data.get("corpus", {})),
        index=IndexConfig(**data.get("index", {})),
        embedding=EmbeddingConfig(**data.get("embedding", {})),
        chunking=ChunkingConfig(**data.get("chunking", {})),
        ingest=IngestConfig(**data.get("ingest", {})),
        acquire=AcquireConfig(**data.get("acquire", {})),
    )
