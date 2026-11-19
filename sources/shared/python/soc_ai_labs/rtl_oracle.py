"""Bit-stable numeric contract shared by RTL tests and scalar software.

The public functions in this module are the seam between semantic floating-point
models and the deliberately small synthesizable datapaths used by P1--P3.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
import struct

import numpy as np

from .numeric import as_bfloat16


Q11_SCALE = 1 << 11
Q15_SCALE = 1 << 15
Q5_11_MIN = -16 * Q11_SCALE
Q5_11_MAX = 16 * Q11_SCALE - 1
Q6_SCALE = 1 << 6
Q11_TO_Q6 = Q11_SCALE // Q6_SCALE


def validate_positive_scale(scale: float) -> float:
    """Return a finite positive FP32-compatible scale or reject it."""
    value = float(scale)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("scale must be finite and positive")
    return value


def fp32_bits(value: float) -> int:
    """Return the little-endian IEEE-754 binary32 encoding."""
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


def bf16_rne_bits(value: float) -> int:
    """Pack a value to BF16 with round-to-nearest-even."""
    bits = fp32_bits(value)
    upper = bits >> 16
    lower = bits & 0xFFFF
    if lower > 0x8000 or (lower == 0x8000 and upper & 1):
        upper = (upper + 1) & 0xFFFF
    return upper


def int32_scale_to_q5_11(value: int, scale: float) -> int:
    """Bit-exact model of ``int32_scale_to_q5_11.sv``."""
    if not -(1 << 31) <= int(value) < (1 << 31):
        raise ValueError("value must fit signed INT32")
    scale32 = np.float32(scale)
    checked = _contract_scale(float(scale32))
    bits = fp32_bits(float(checked))
    exponent = (bits >> 23) & 0xFF
    significand = (1 << 23) | (bits & 0x7FFFFF)
    product = abs(int(value)) * significand
    shift = exponent - 139
    magnitude = product << shift if shift >= 0 else _round_divide_even(product, 1 << -shift)
    if value < 0:
        return -min(magnitude, 32768)
    return min(magnitude, 32767)


def _round_divide_even(numerator: int, denominator: int) -> int:
    """Integer division rounded to nearest, ties to even."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    sign = -1 if numerator < 0 else 1
    quotient, remainder = divmod(abs(numerator), denominator)
    twice = remainder * 2
    if twice > denominator or (twice == denominator and quotient & 1):
        quotient += 1
    return sign * quotient


def q5_11_delta(value: float) -> int:
    """Quantize a softmax delta to signed Q5.11, saturating to [-16, 0]."""
    if not math.isfinite(float(value)):
        raise ValueError("score delta must be finite")
    clipped = min(0.0, max(-16.0, float(value)))
    return max(Q5_11_MIN, min(0, int(round(clipped * Q11_SCALE))))


def q5_11_value(value: float) -> int:
    """Quantize a finite scalar to the full signed Q5.11 project range."""
    if not math.isfinite(float(value)):
        raise ValueError("Q5.11 input must be finite")
    return max(Q5_11_MIN, min(Q5_11_MAX, int(round(float(value) * Q11_SCALE))))


@lru_cache(maxsize=1)
def exp_q15_lut() -> tuple[int, ...]:
    """The 1025-entry Q5.6-addressed exponential ROM contents."""
    return tuple(
        max(0, min(Q15_SCALE, int(round(math.exp(index / Q6_SCALE) * Q15_SCALE))))
        for index in range(-16 * Q6_SCALE, 1)
    )


def exp_neg_q15(delta_q5_11: int) -> int:
    """RNE Q5.11 to Q5.6, then return the unsigned Q1.15 ROM value."""
    clipped = max(Q5_11_MIN, min(0, int(delta_q5_11)))
    index_q6 = _round_divide_even(clipped, Q11_TO_Q6)
    return exp_q15_lut()[index_q6 + 16 * Q6_SCALE]


@lru_cache(maxsize=1)
def silu_q11_lut() -> tuple[int, ...]:
    """2049-entry Q5.6-addressed SiLU table with signed Q5.11 values."""
    words: list[int] = []
    for index in range(-16 * Q6_SCALE, 16 * Q6_SCALE + 1):
        value = index / Q6_SCALE
        silu = value / (1.0 + math.exp(-value))
        words.append(q5_11_value(silu))
    return tuple(words)


def silu_q11(value_q5_11: int) -> int:
    """RNE Q5.11 to Q5.6, then evaluate the frozen SiLU table."""
    clipped = max(Q5_11_MIN, min(Q5_11_MAX, int(value_q5_11)))
    index_q6 = _round_divide_even(clipped, Q11_TO_Q6)
    index_q6 = max(-16 * Q6_SCALE, min(16 * Q6_SCALE, index_q6))
    return silu_q11_lut()[index_q6 + 16 * Q6_SCALE]


def quantize_int8_rne(value: np.ndarray, *, scale: float) -> np.ndarray:
    """Quantize using round-to-nearest-even and signed INT8 saturation."""
    divisor = validate_positive_scale(scale)
    array = np.asarray(value, dtype=np.float64)
    if not np.all(np.isfinite(array)):
        raise ValueError("quantized values must be finite")
    return np.clip(np.rint(array / divisor), -128, 127).astype(np.int8)


def q22_requantize_int8(value_q22: int, scale: float) -> int:
    """Bit-exact scalar model of ``q22_requantize_int8.sv``."""
    checked = _contract_scale(float(np.float32(scale)))
    bits = fp32_bits(float(checked))
    exponent = (bits >> 23) & 0xFF
    significand = (1 << 23) | (bits & 0x7FFFFF)
    magnitude = abs(int(value_q22))
    shift = 128 - exponent
    numerator = magnitude << shift if shift >= 0 else magnitude >> -shift
    rounded = _round_divide_even(numerator, significand)
    if value_q22 < 0:
        return -min(rounded, 128)
    return min(rounded, 127)


@dataclass
class FixedSoftmaxState:
    """Online softmax state with explicit Q formats and integer rescaling."""

    maximum_q11: int
    denominator_q15: int
    weighted_q15: np.ndarray
    valid: bool = False

    @classmethod
    def empty(cls, value_width: int) -> "FixedSoftmaxState":
        if value_width <= 0:
            raise ValueError("value width must be positive")
        return cls(0, 0, np.zeros(value_width, dtype=np.int64), False)

    def update(self, *, score_q5_11: int, value: np.ndarray) -> None:
        value_i8 = np.asarray(value)
        if value_i8.dtype != np.int8 or value_i8.shape != self.weighted_q15.shape:
            raise ValueError("softmax values must be an INT8 vector of fixed width")
        score = int(score_q5_11)
        if not self.valid:
            self.maximum_q11 = score
            self.denominator_q15 = Q15_SCALE
            self.weighted_q15 = value_i8.astype(np.int64) * Q15_SCALE
            self.valid = True
            return

        new_maximum = max(self.maximum_q11, score)
        old_delta = q5_11_delta((self.maximum_q11 - new_maximum) / Q11_SCALE)
        new_delta = q5_11_delta((score - new_maximum) / Q11_SCALE)
        old_scale = exp_neg_q15(old_delta)
        new_scale = exp_neg_q15(new_delta)
        self.denominator_q15 = (
            _round_divide_even(self.denominator_q15 * old_scale, Q15_SCALE) + new_scale
        )
        old_weighted = [
            _round_divide_even(int(item) * old_scale, Q15_SCALE)
            for item in self.weighted_q15
        ]
        self.weighted_q15 = np.asarray(old_weighted, dtype=np.int64) + value_i8.astype(np.int64) * new_scale
        self.maximum_q11 = new_maximum

    def value_bf16(self, *, value_scale: float) -> np.ndarray:
        scale = validate_positive_scale(value_scale)
        if not self.valid or self.denominator_q15 <= 0:
            raise ValueError("softmax state has no valid samples")
        # RTL first rounds each quotient through ``fixed_divider_rne`` to
        # signed Q16.  A direct floating-point division is not bit-exact and
        # can move a BF16 layer boundary even when the online state matches.
        q16 = np.asarray(
            [
                _round_divide_even(
                    int(weighted) << 16, self.denominator_q15
                )
                for weighted in self.weighted_q15
            ],
            dtype=np.int64,
        )
        value = q16.astype(np.float32) / np.float32(65536.0)
        return as_bfloat16(value * np.float32(scale))

    def merge(self, other: "FixedSoftmaxState") -> "FixedSoftmaxState":
        """Merge two split states with the same RNE rescaling as RTL."""
        if self.weighted_q15.shape != other.weighted_q15.shape:
            raise ValueError("softmax states must have the same value width")
        if not self.valid:
            return FixedSoftmaxState(
                other.maximum_q11, other.denominator_q15, other.weighted_q15.copy(), other.valid
            )
        if not other.valid:
            return FixedSoftmaxState(
                self.maximum_q11, self.denominator_q15, self.weighted_q15.copy(), self.valid
            )
        maximum = max(self.maximum_q11, other.maximum_q11)
        left_scale = exp_neg_q15(max(Q5_11_MIN, self.maximum_q11 - maximum))
        right_scale = exp_neg_q15(max(Q5_11_MIN, other.maximum_q11 - maximum))
        denominator = (
            _round_divide_even(self.denominator_q15 * left_scale, Q15_SCALE)
            + _round_divide_even(other.denominator_q15 * right_scale, Q15_SCALE)
        )
        weighted = np.asarray(
            [
                _round_divide_even(int(left) * left_scale, Q15_SCALE)
                + _round_divide_even(int(right) * right_scale, Q15_SCALE)
                for left, right in zip(self.weighted_q15, other.weighted_q15, strict=True)
            ],
            dtype=np.int64,
        )
        return FixedSoftmaxState(maximum, denominator, weighted, True)


def merge_split_states_canonical(
    states: dict[int, FixedSoftmaxState], arrival_order: list[int] | tuple[int, ...]
) -> FixedSoftmaxState:
    """Buffer arbitrary arrivals, then merge strictly by ascending split id."""
    if set(arrival_order) != set(states) or len(arrival_order) != len(states):
        raise ValueError("arrival order must contain every split id exactly once")
    # Arrival affects only buffer fill order. Arithmetic order is the interface
    # contract and therefore deliberately ignores ``arrival_order`` here.
    ordered = [states[split_id] for split_id in sorted(states)]
    if not ordered:
        raise ValueError("at least one split state is required")
    merged = ordered[0]
    for state in ordered[1:]:
        merged = merged.merge(state)
    return merged


def attention_rtl_oracle(
    query: np.ndarray,
    keys: np.ndarray,
    values: np.ndarray,
    *,
    score_scale: float,
    value_scale: float,
) -> np.ndarray:
    """Compute one quantized attention row using the P1/P2 RTL contract."""
    q = np.asarray(query)
    k = np.asarray(keys)
    v = np.asarray(values)
    if q.dtype != np.int8 or k.dtype != np.int8 or v.dtype != np.int8:
        raise ValueError("attention RTL operands must be INT8")
    if q.ndim != 1 or k.ndim != 2 or v.ndim != 2 or k.shape[0] != v.shape[0] or k.shape[1] != q.shape[0]:
        raise ValueError("inconsistent attention shapes")
    if k.shape[0] == 0:
        raise ValueError("attention requires at least one visible token")
    score_multiplier = validate_positive_scale(score_scale)
    state = FixedSoftmaxState.empty(v.shape[1])
    query_i32 = q.astype(np.int32)
    for key, value in zip(k, v, strict=True):
        dot = int(query_i32 @ key.astype(np.int32))
        score_q11 = int32_scale_to_q5_11(dot, score_multiplier)
        state.update(score_q5_11=score_q11, value=value)
    return state.value_bf16(value_scale=value_scale)


def _contract_scale(scale: float) -> np.float32:
    value = validate_positive_scale(scale)
    if not 2**-16 <= value <= 2**16:
        raise ValueError("scale is outside the project contract [2^-16, 2^16]")
    return np.float32(value)


def _silu(value: np.ndarray) -> np.ndarray:
    source = np.asarray(value, dtype=np.float32)
    positive = source >= 0
    result = np.empty_like(source)
    result[positive] = source[positive] / (np.float32(1.0) + np.exp(-source[positive]))
    exp_value = np.exp(source[~positive])
    result[~positive] = source[~positive] * exp_value / (np.float32(1.0) + exp_value)
    return result


def moe_expert_rtl_oracle(
    activations: np.ndarray,
    gate_weights: np.ndarray,
    up_weights: np.ndarray,
    down_weights: np.ndarray,
    expert_ids: np.ndarray,
    route_weights: np.ndarray,
    *,
    input_scale: float,
    gate_scale: float,
    up_scale: float,
    intermediate_scale: float,
    down_scale: float,
    rows_per_tile: int = 128,
) -> np.ndarray:
    """Bit-stable W8A8 gate/up/SiLU/requantize/down expert path."""
    operands = tuple(np.asarray(item) for item in (activations, gate_weights, up_weights, down_weights))
    if any(item.dtype != np.int8 for item in operands):
        raise ValueError("all matrix operands must be INT8")
    a, gate, up, down = operands
    if a.ndim != 2 or gate.ndim != 3 or up.shape != gate.shape or down.ndim != 3:
        raise ValueError("invalid MoE tensor ranks")
    rows, hidden = a.shape
    experts, intermediate, gate_hidden = gate.shape
    if gate_hidden != hidden or down.shape != (experts, hidden, intermediate):
        raise ValueError("inconsistent MoE tensor shapes")
    if rows_per_tile <= 0:
        raise ValueError("rows_per_tile must be positive")
    ids = np.asarray(expert_ids)
    routes = np.asarray(route_weights, dtype=np.float32)
    if ids.shape != ((rows + rows_per_tile - 1) // rows_per_tile,) or routes.shape != (rows,):
        raise ValueError("invalid routing metadata")
    if not np.all(np.isfinite(routes)) or np.any(routes < 0) or np.any(routes > 1):
        raise ValueError("route weights must be finite and in [0, 1]")

    input_s = _contract_scale(input_scale)
    gate_s = _contract_scale(gate_scale)
    up_s = _contract_scale(up_scale)
    intermediate_s = _contract_scale(intermediate_scale)
    down_s = _contract_scale(down_scale)
    output = np.empty((rows, hidden), dtype=np.float32)
    for row in range(rows):
        expert = int(ids[row // rows_per_tile])
        if not 0 <= expert < experts:
            raise ValueError("expert id out of range")
        source = a[row].astype(np.int32)
        gate_acc = gate[expert].astype(np.int32) @ source
        up_acc = up[expert].astype(np.int32) @ source
        gate_f = gate_acc.astype(np.float32) * np.float32(input_s * gate_s)
        up_f = up_acc.astype(np.float32) * np.float32(input_s * up_s)
        gate_q11 = np.asarray(
            [q5_11_value(float(item)) for item in gate_f], dtype=np.int32
        )
        up_q11 = np.asarray(
            [q5_11_value(float(item)) for item in up_f], dtype=np.int32
        )
        # The RTL rounds both gate and up accumulators to Q5.11 before the
        # SiLU/product stage.  Keeping up_f here would be a semantic model,
        # not the promised bit-exact rtl-oracle.
        gate_silu_q11 = np.asarray(
            [silu_q11(int(item)) for item in gate_q11], dtype=np.int32
        )
        activated_q22 = gate_silu_q11.astype(np.int64) * up_q11.astype(np.int64)
        quantized = np.asarray(
            [q22_requantize_int8(int(item), float(intermediate_s)) for item in activated_q22],
            dtype=np.int8,
        )
        down_acc = down[expert].astype(np.int32) @ quantized.astype(np.int32)
        if routes[row] == 0:
            # The RTL has an explicit route_weight==0 bypass and writes the
            # canonical +0 BF16 pattern, irrespective of the accumulator sign.
            output[row].fill(np.float32(0.0))
        else:
            combined_scale = np.float32(intermediate_s * down_s * routes[row])
            output[row] = down_acc.astype(np.float32) * combined_scale
    return as_bfloat16(output)
