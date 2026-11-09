"""Embedders behind one small protocol (D-004). Only local, free models; never a paid API."""

import hashlib
import math
import re
from functools import cache
from typing import Protocol

from rag import config

DIM = 384
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_WORD = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Passages -> L2-normalised vectors."""

    def embed_query(self, text: str) -> list[float]:
        """A search query -> one L2-normalised vector (bge wants an instruction prefix here)."""

    def count_tokens(self, text: str) -> int: ...


class FakeEmbedder:
    """Deterministic hash-based vectors: same words -> similar vectors. No ML imports."""

    model_name = "fake"
    dim = DIM

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in _WORD.findall(text.lower()):
            h = hashlib.blake2b(word.encode(), digest_size=8).digest()
            n = int.from_bytes(h, "big")
            v[n % self.dim] += 1.0 if (n >> 40) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0:
            v[0], norm = 1.0, 1.0
        return [x / norm for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def count_tokens(self, text: str) -> int:
        return len(_WORD.findall(text.lower()))


class SentenceTransformerEmbedder:
    """BAAI/bge-small-en-v1.5 on CPU: 384 dims, L2-normalised, batch size 32."""

    dim = DIM
    batch_size = 32

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # heavy: import lazily

        self.model_name = model_name
        self._model = SentenceTransformer(model_name, device="cpu")
        self._tok = self._model.tokenizer

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = self._model.encode(
            texts, batch_size=self.batch_size, normalize_embeddings=True, show_progress_bar=False
        )
        return out.tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed([BGE_QUERY_PREFIX + text])[0]

    def count_tokens(self, text: str) -> int:
        return len(self._tok.encode(text, add_special_tokens=False))


@cache
def get_embedder(name: str | None = None) -> Embedder:
    """`name` defaults to rag.config.embedder_name(). Cached, so a real model loads once."""
    name = name or config.embedder_name()
    if name == "fake":
        return FakeEmbedder()
    return SentenceTransformerEmbedder(name)
