"""Hybrid retrieval: FTS5 BM25 plus embeddings, fused with reciprocal rank."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

import numpy as np

from paperproof.search.embed import STOPWORDS, get_embedder

TOKEN_RE = re.compile(r"[a-z0-9]+")
RRF_K = 60


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    doc_id: str
    filename: str
    title: str
    heading: str | None
    text: str
    page_start: int
    page_end: int
    score: float


def query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for token in TOKEN_RE.findall(query.lower()):
        if len(token) < 2 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def fts_query(query: str, max_terms: int = 16) -> str:
    terms = query_terms(query)[:max_terms]
    return " OR ".join(f"{term}*" for term in terms)


def _bm25_ids(conn: sqlite3.Connection, query: str, doc_id: str | None, limit: int) -> list[int]:
    match = fts_query(query)
    if not match:
        return []
    sql = (
        "SELECT chunks_fts.rowid AS chunk_id "
        "FROM chunks_fts JOIN chunks ON chunks.id = chunks_fts.rowid "
        "WHERE chunks_fts MATCH ?"
    )
    params: list[Any] = [match]
    if doc_id:
        sql += " AND chunks.doc_id = ?"
        params.append(doc_id)
    sql += " ORDER BY bm25(chunks_fts, 1.0, 0.4) LIMIT ?"
    params.append(limit)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [int(row["chunk_id"]) for row in rows]


def _vector_scores(
    conn: sqlite3.Connection,
    query: str,
    doc_id: str | None,
    limit: int,
    embedder_name: str,
) -> list[int]:
    sql = "SELECT e.chunk_id, e.vec FROM embeddings e JOIN chunks c ON c.id = e.chunk_id"
    params: list[Any] = []
    if doc_id:
        sql += " WHERE c.doc_id = ?"
        params.append(doc_id)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return []
    matrix = np.vstack([np.frombuffer(row["vec"], dtype=np.float32) for row in rows])
    query_vec = get_embedder(embedder_name).embed([query])[0]
    scores = matrix @ query_vec
    order = np.argsort(-scores)[:limit]
    return [int(rows[int(index)]["chunk_id"]) for index in order]


def _coverage(text: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    tokens = set(TOKEN_RE.findall(text.lower()))
    hits = sum(1 for term in terms if term in tokens)
    return hits / len(terms)


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    doc_id: str | None = None,
    limit: int = 6,
    candidate_k: int = 48,
    embedder_name: str = "hash",
) -> list[Hit]:
    if not query.strip():
        return []
    terms = query_terms(query)
    bm25 = _bm25_ids(conn, query, doc_id, candidate_k)
    vectors = _vector_scores(conn, query, doc_id, candidate_k, embedder_name)

    fused: dict[int, float] = {}
    for ranked in (bm25, vectors):
        for rank, chunk_id in enumerate(ranked):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    if not fused:
        return []

    placeholders = ",".join("?" for _ in fused)
    rows = conn.execute(
        "SELECT c.id, c.doc_id, c.heading, c.text, c.page_start, c.page_end, "  # noqa: S608
        "d.filename, d.title "
        "FROM chunks c JOIN documents d ON d.id = c.doc_id "
        f"WHERE c.id IN ({placeholders})",
        tuple(fused),
    ).fetchall()

    max_rrf = max(fused.values()) or 1.0
    scored: list[Hit] = []
    for row in rows:
        chunk_id = int(row["id"])
        heading = row["heading"] or ""
        heading_bonus = 1.0 if any(term in heading.lower() for term in terms) else 0.0
        score = (
            0.65 * (fused[chunk_id] / max_rrf)
            + 0.30 * _coverage(row["text"], terms)
            + 0.05 * heading_bonus
        )
        scored.append(
            Hit(
                chunk_id=chunk_id,
                doc_id=str(row["doc_id"]),
                filename=str(row["filename"]),
                title=str(row["title"]),
                heading=row["heading"],
                text=str(row["text"]),
                page_start=int(row["page_start"]),
                page_end=int(row["page_end"]),
                score=round(score, 6),
            )
        )

    scored.sort(key=lambda hit: (-hit.score, hit.chunk_id))
    return scored[:limit]


def make_snippet(text: str, terms: list[str], width: int = 300) -> str:
    lowered = text.lower()
    positions = [lowered.find(term) for term in terms if term and lowered.find(term) >= 0]
    if not positions:
        clipped = text[:width].strip()
        return clipped + ("…" if len(text) > width else "")
    position = min(positions)
    start = max(0, position - width // 3)
    end = min(len(text), start + width)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet
