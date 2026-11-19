"""Numerically stable BF16 and online-softmax reference operations."""

from __future__ import annotations

from dataclasses import dataclass
import math

import ml_dtypes
import numpy as np


def as_bfloat16(value: np.ndarray) -> np.ndarray:
    """Round through BF16 and return float32 values for portable comparisons."""
    return np.asarray(value, dtype=ml_dtypes.bfloat16).astype(np.float32)


@dataclass
class OnlineSoftmaxState:
    maximum: float
    denominator: float
    weighted: np.ndarray

    @classmethod
    def empty(cls, value_width: int) -> "OnlineSoftmaxState":
        return cls(-math.inf, 0.0, np.zeros(value_width, dtype=np.float64))

    def update(self, score: float, value: np.ndarray) -> None:
        value64 = np.asarray(value, dtype=np.float64)
        if value64.shape != self.weighted.shape:
            raise ValueError("value width changed within a stream")
        new_max = max(self.maximum, float(score))
        old_scale = 0.0 if self.denominator == 0.0 else math.exp(self.maximum - new_max)
        new_scale = math.exp(float(score) - new_max)
        self.weighted = self.weighted * old_scale + value64 * new_scale
        self.denominator = self.denominator * old_scale + new_scale
        self.maximum = new_max

    def value(self) -> np.ndarray:
        if self.denominator == 0.0:
            raise ValueError("softmax state has no valid samples")
        return (self.weighted / self.denominator).astype(np.float32)


def merge_softmax_states(left: OnlineSoftmaxState, right: OnlineSoftmaxState) -> OnlineSoftmaxState:
    """Merge independent partial states using a stable associative rule."""
    if left.weighted.shape != right.weighted.shape:
        raise ValueError("state widths differ")
    if left.denominator == 0.0:
        return OnlineSoftmaxState(right.maximum, right.denominator, right.weighted.copy())
    if right.denominator == 0.0:
        return OnlineSoftmaxState(left.maximum, left.denominator, left.weighted.copy())
    maximum = max(left.maximum, right.maximum)
    left_scale = math.exp(left.maximum - maximum)
    right_scale = math.exp(right.maximum - maximum)
    return OnlineSoftmaxState(
        maximum=maximum,
        denominator=left.denominator * left_scale + right.denominator * right_scale,
        weighted=left.weighted * left_scale + right.weighted * right_scale,
    )
