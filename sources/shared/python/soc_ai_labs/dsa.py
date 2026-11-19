"""Deterministic DeepSeek Sparse Attention teaching primitives."""

from __future__ import annotations

import numpy as np


def stable_topk(scores: np.ndarray, k: int, *, valid_length: int | None = None) -> np.ndarray:
    """Select descending scores; equal scores prefer the smaller token id."""
    values = np.asarray(scores)
    if values.ndim not in (1, 2):
        raise ValueError("scores must be one- or two-dimensional")
    if k <= 0 or not np.all(np.isfinite(values)):
        raise ValueError("k must be positive and scores finite")
    length = values.shape[-1] if valid_length is None else int(valid_length)
    if not 0 <= length <= values.shape[-1]:
        raise ValueError("valid_length out of range")
    count = min(k, length)

    def select(row: np.ndarray) -> np.ndarray:
        token_ids = np.arange(length, dtype=np.int64)
        return np.lexsort((token_ids, -row[:length]))[:count]

    if values.ndim == 1:
        return select(values)
    return np.stack([select(row) for row in values], axis=0)


def gather_selected_pages(
    selected_tokens: np.ndarray,
    addresses: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Translate selected logical token ids without inspecting padding entries."""
    result: list[tuple[int, int]] = []
    for token in np.asarray(selected_tokens, dtype=np.int64).ravel():
        if not 0 <= int(token) < len(addresses):
            raise ValueError("selected token outside valid sequence")
        result.append(addresses[int(token)])
    return result
