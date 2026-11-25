"""Embedding interface plus a dependency-free deterministic default.

The default embedder is lexical (hashed words, bigrams, character n-grams).
It exists so the pipeline runs offline and tests stay hermetic. Swap in a
neural embedder behind the same protocol for semantic recall; the rest of the
system does not care which one is used.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Sequence
from itertools import pairwise
from typing import Protocol, runtime_checkable

import numpy as np

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
        "shall",
        "may",
        "not",
        "any",
        "all",
        "such",
        "other",
        "than",
    }
)


@runtime_checkable
class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


class HashingEmbedder:
    """Stable hashed bag of words, bigrams, and character 4-grams."""

    name = "hash-512"
    dim = 512

    def _features(self, text: str) -> dict[str, float]:
        tokens = [token for token in TOKEN_RE.findall(text.lower()) if token not in STOPWORDS]
        features: dict[str, float] = {}
        for token in tokens:
            features[f"w:{token}"] = 1.0
        for left, right in pairwise(tokens):
            features[f"b:{left}_{right}"] = 0.6
        for token in tokens:
            if len(token) >= 5:
                for index in range(len(token) - 3):
                    features[f"c:{token[index : index + 4]}"] = 0.25
        return features

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for feature, weight in self._features(text).items():
                digest = zlib.crc32(feature.encode("utf-8"))
                column = digest % self.dim
                sign = 1.0 if (digest >> 15) & 1 else -1.0
                matrix[row, column] += sign * weight
            norm = float(np.linalg.norm(matrix[row]))
            if norm > 0:
                matrix[row] /= norm
        return matrix


def get_embedder(name: str = "hash") -> Embedder:
    if name == "hash":
        return HashingEmbedder()
    raise ValueError(
        f"Unknown embedder {name!r}. Paperproof ships with 'hash'. "
        "Add a neural embedder behind the Embedder protocol for semantic recall."
    )
