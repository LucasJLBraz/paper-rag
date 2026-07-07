"""LanceDB-backed vector index — embedded, file-based, git-ignored, disposable.

The index is a build artifact, not a source of truth: it's fully
reconstructible from the PDFs + metadata under references/Papers/, so it's
never committed. See `paper-rag.toml.example` / repo `.gitignore`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa


class PaperIndex:
    """Thin wrapper around a single LanceDB table: opens/creates it with a
    fixed chunk schema, refuses to reopen a table built with a different
    embedding model (see `open_or_create`), and exposes the add/search/
    delete/list operations `cli.py` and `search.py` need."""

    def __init__(self, index_dir: Path, table_name: str, embedding_dim: int, embedding_model: str):
        self.index_dir = index_dir
        self.table_name = table_name
        self.embedding_dim = embedding_dim
        self.embedding_model = embedding_model
        self._db = lancedb.connect(str(index_dir))

    def _schema(self) -> pa.Schema:
        return pa.schema(
            [
                pa.field("chunk_id", pa.string()),
                pa.field("citation_key", pa.string()),
                pa.field("section", pa.string()),
                pa.field("text", pa.string()),
                pa.field("token_count", pa.int32()),
                pa.field("pdf_path", pa.string()),
                pa.field("embedding_model", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), self.embedding_dim)),
            ]
        )

    def open_or_create(self):
        if self.table_name in self._db.table_names():
            table = self._db.open_table(self.table_name)
            if table.count_rows() > 0:
                stored_model = table.to_pandas().iloc[0]["embedding_model"]
                if stored_model != self.embedding_model:
                    raise RuntimeError(
                        f"Index at {self.index_dir} was built with embedding model "
                        f"'{stored_model}', but the config now specifies "
                        f"'{self.embedding_model}'. Vectors from different models aren't "
                        "comparable — delete the index directory and run "
                        "`paper-rag build --rebuild`."
                    )
            return table
        return self._db.create_table(self.table_name, schema=self._schema())

    def delete_citation_key(self, table, citation_key: str) -> None:
        table.delete(f"citation_key = '{citation_key}'")

    def distinct_citation_keys(self, table) -> set[str]:
        if table.count_rows() == 0:
            return set()
        return set(table.to_pandas()["citation_key"].unique().tolist())

    def add(self, table, rows: list[dict[str, Any]]) -> None:
        table.add(rows)

    def search(self, table, query_vector: list[float], k: int = 5, citation_key: str | None = None):
        q = table.search(query_vector).limit(k)
        if citation_key:
            q = q.where(f"citation_key = '{citation_key}'")
        hits = q.to_list()
        for hit in hits:
            hit["vector_distance"] = hit.pop("_distance")
        return hits
