"""Cross-encoder rerankers. Local and free: BAAI/bge-reranker-base, or a fake for tests."""

import re
from functools import cache
from typing import Protocol

from rag import config

_WORD = re.compile(r"[a-z0-9]+")


class Reranker(Protocol):
    model_name: str

    def score(self, query: str, texts: list[str]) -> list[float]:
        """One relevance score per text (higher = more relevant); the scale is model-specific."""

    def count_tokens(self, query: str, texts: list[str]) -> int:
        """Tokens the model reads for this call (for cost_log)."""


class FakeReranker:
    """Deterministic: share of the query's words found in the text, plus a tiny length penalty."""

    model_name = "fake"

    def score(self, query: str, texts: list[str]) -> list[float]:
        q = set(_WORD.findall(query.lower()))
        out = []
        for t in texts:
            words = _WORD.findall(t.lower())
            overlap = len(q & set(words)) / len(q) if q else 0.0
            out.append(round(overlap - 0.0001 * len(words) / 100, 6))
        return out

    def count_tokens(self, query: str, texts: list[str]) -> int:
        return sum(len(_WORD.findall((query + " " + t).lower())) for t in texts)


class CrossEncoderReranker:
    """BAAI/bge-reranker-base: reads (query, passage) together; returns a raw relevance logit."""

    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder  # heavy: import lazily

        self.model_name = model_name
        self._model = CrossEncoder(model_name, device="cpu", max_length=512)

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        scores = self._model.predict(
            [(query, t) for t in texts], batch_size=16, show_progress_bar=False
        )
        return [float(s) for s in scores]

    def count_tokens(self, query: str, texts: list[str]) -> int:
        tok = self._model.tokenizer
        return sum(len(tok.encode(query, t, truncation=True, max_length=512)) for t in texts)


@cache
def get_reranker(name: str | None = None) -> Reranker:
    """`name` defaults to rag.config.reranker_name(); "fake" for tests. Loads once per process."""
    name = name or config.reranker_name()
    if name == "fake":
        return FakeReranker()
    return CrossEncoderReranker(name)
