"""Pluggable local embedding backends.

Both backends run entirely on-machine (sentence-transformers loads weights
once from the local HF cache; Ollama talks to a localhost server) — no
hosted embedding API is ever called, consistent with this project's
local-only-processing constraint.
"""
from __future__ import annotations

from typing import Protocol

import requests


class EmbeddingBackend(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]: ...


class SentenceTransformerBackend:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self._model = SentenceTransformer(model_name)
        get_dim = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dim = get_dim()
        # E5 family models are trained on prefixed asymmetric pairs and lose
        # meaningful retrieval quality without "query: " / "passage: " — see
        # https://huggingface.co/intfloat/multilingual-e5-small#faq
        self._e5_prefixes = "e5-" in model_name.lower()

    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        if self._e5_prefixes:
            prefix = "query: " if is_query else "passage: "
            texts = [prefix + t for t in texts]
        return self._model.encode(texts, normalize_embeddings=True).tolist()


class OllamaBackend:
    def __init__(self, model_name: str = "nomic-embed-text", host: str = "http://localhost:11434"):
        self.name = model_name
        self.host = host.rstrip("/")
        self.dim = len(self.embed(["dimension probe"])[0])

    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        out = []
        for t in texts:
            r = requests.post(
                f"{self.host}/api/embeddings",
                json={"model": self.name, "prompt": t},
                timeout=60,
            )
            r.raise_for_status()
            out.append(r.json()["embedding"])
        return out


def build_backend(backend: str, model: str, ollama_host: str = "http://localhost:11434") -> EmbeddingBackend:
    if backend == "sentence-transformers":
        return SentenceTransformerBackend(model)
    if backend == "ollama":
        return OllamaBackend(model, ollama_host)
    raise ValueError(f"Unknown embedding backend: {backend!r} (expected 'sentence-transformers' or 'ollama')")
