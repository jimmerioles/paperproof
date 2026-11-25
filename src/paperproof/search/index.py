"""Persist chunk embeddings."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

import numpy as np

from paperproof.search.embed import Embedder


def index_chunks(
    conn: sqlite3.Connection,
    chunk_ids: Sequence[int],
    texts: Sequence[str],
    embedder: Embedder,
) -> int:
    if not chunk_ids:
        return 0
    vectors = embedder.embed(texts)
    rows = [
        (chunk_id, embedder.dim, vectors[index].astype(np.float32).tobytes())
        for index, chunk_id in enumerate(chunk_ids)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO embeddings (chunk_id, dim, vec) VALUES (?, ?, ?)",
        rows,
    )
    return len(rows)
