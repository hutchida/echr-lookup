"""Schema, embeddings and BM25/vector indexes in Postgres. Owner: S3."""

from rag.index.cost import log_cost, price_usd
from rag.index.db import connect, migrate, reset
from rag.index.embedder import Embedder, get_embedder
from rag.index.store import record_ingest_run, replace_chunks, stored_hashes, upsert_document

__all__ = [
    "Embedder",
    "connect",
    "get_embedder",
    "log_cost",
    "migrate",
    "price_usd",
    "record_ingest_run",
    "replace_chunks",
    "reset",
    "stored_hashes",
    "upsert_document",
]
