"""Bit-stable INT8/BF16 P1/P2/P3 runtime for the trained Nano chat model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .dsa import stable_topk
from .litex_contract import TinyModelProfile
from .numeric import as_bfloat16
from .rtl_oracle import (
    attention_rtl_oracle,
    int32_scale_to_q5_11,
    moe_expert_rtl_oracle,
)

if TYPE_CHECKING:
    from .chat_tokenizer import ByteBPETokenizer
from .tiny_model import NANO_P3_INTERMEDIATE_SCALE


class QuantizedNanoChatRuntime:
    """Autoregressive runtime whose operator boundaries match the LiteX ABI.

    Prefill computes every causal prompt row and caches per-layer compressed KV.
    Decode appends one row to those caches and evaluates only the new query.
    Matrix products use dynamic INT8 activations and exact INT32 accumulation;
    CPU-owned residual and RMSNorm boundaries are rounded to BF16.
    """

    PREFILL_TOPK = 32

    def __init__(
        self, profile: TinyModelProfile, arrays: dict[str, np.ndarray],
        scales: dict[str, float],
    ) -> None:
        self.profile = profile
        self.arrays = {name: np.asarray(value, dtype=np.int8) for name, value in arrays.items()}
        self.scales = {name: float(scale) for name, scale in scales.items()}
        if "lm_head" not in self.arrays:
            self.arrays["lm_head"] = self.arrays["embedding"].copy()
            self.scales["lm_head"] = self.scales["embedding"]
        self.operation_trace: list[str] = []
        self._cache: list[dict[str, np.ndarray]] = []
        self._intent_id: int | None = None
        self._subject_id: int | None = None
        self._response_position = 0
        self.last_hidden: np.ndarray | None = None
        self.hidden_trace: list[np.ndarray] = []
        self.boundary_trace: list[dict[str, np.ndarray | int | str]] = []
        self.attention_scale_trace: list[dict[str, float | int | str]] = []
        self.attention_input_trace: list[
            dict[str, np.ndarray | float | int | str]
        ] = []

    @classmethod
    def from_npz(cls, path: Path) -> "QuantizedNanoChatRuntime":
        with np.load(path) as archive:
            metadata = json.loads(bytes(archive["metadata_utf8"]).decode("utf-8"))
            arrays = {name: archive[name].copy() for name in archive.files if name != "metadata_utf8"}
        return cls(TinyModelProfile(**metadata["profile"]), arrays, metadata["scales"])

    @staticmethod
    def _activation(value: np.ndarray) -> tuple[np.ndarray, float]:
        source = np.asarray(value, dtype=np.float32)
        peak = float(np.max(np.abs(source))) if source.size else 0.0
        scale32 = np.float32(
            np.float32(peak) / np.float32(127.0)
            if peak else np.float32(1.0)
        )
        # Match the RV32 firmware: binary32 division first, then RNE.  An
        # FP64-promoted quotient changes exact half-way cases and can alter
        # P1 keys even when the BF16 source and FP32 scale are identical.
        quotient = np.asarray(source / scale32, dtype=np.float32)
        quantized = np.clip(np.rint(quotient), -128, 127).astype(np.int8)
        return quantized, float(scale32)

    @staticmethod
    def _clamp_scale_fp32(value: float) -> float:
        scale = np.float32(value)
        return float(np.maximum(np.float32(2.0**-16), np.minimum(np.float32(2.0**16), scale)))

    def _dequant(self, name: str, value: np.ndarray) -> np.ndarray:
        return value.astype(np.float32) * np.float32(self.scales[name])

    def _matmul(self, value: np.ndarray, name: str, weight: np.ndarray) -> np.ndarray:
        source = np.asarray(value, dtype=np.float32)
        if source.ndim == 1:
            source = source[None, :]
            squeeze = True
        else:
            squeeze = False
        rows: list[np.ndarray] = []
        weight_i32 = np.asarray(weight, dtype=np.int8).astype(np.int32)
        for row in source:
            activation, activation_scale = self._activation(row)
            accumulator = activation.astype(np.int32) @ weight_i32
            # Match the RV32 firmware's two FP32 multiplies exactly.  Casting
            # only after a Python-double scale product shifts BF16 ties.
            combined_scale = np.float32(
                np.float32(activation_scale) * np.float32(self.scales[name])
            )
            rows.append(as_bfloat16(
                accumulator.astype(np.float32) * combined_scale
            ))
        result = np.stack(rows)
        return result[0] if squeeze else result

    def _rmsnorm(self, value: np.ndarray, name: str, layer: int | None) -> np.ndarray:
        source = np.asarray(value, dtype=np.float32)
        weight_i8 = self.arrays[name] if layer is None else self.arrays[name][layer]
        gain = weight_i8.astype(np.float32) * np.float32(self.scales[name])
        rows = source.reshape(-1, source.shape[-1])
        normalised: list[np.ndarray] = []
        for row in rows:
            total = np.float32(0.0)
            for item in row:
                value_f32 = np.float32(item)
                total = np.float32(total + np.float32(value_f32 * value_f32))
            mean = np.float32(
                total / np.float32(row.size) + np.float32(0.000001)
            )
            norm = self._sqrt_newton_f32(mean)
            normalised.append(as_bfloat16(
                np.float32(row / norm) * gain
            ))
        return np.stack(normalised).reshape(source.shape)

    @staticmethod
    def _sqrt_newton_f32(value: np.float32) -> np.float32:
        target = np.float32(value)
        estimate = target if target > np.float32(1.0) else np.float32(1.0)
        for _ in range(12):
            estimate = np.float32(
                np.float32(0.5)
                * np.float32(estimate + np.float32(target / estimate))
            )
        return estimate

    @staticmethod
    def _wrap_pi_f32(value: np.float32) -> np.float32:
        result = np.float32(value)
        pi = np.float32(3.14159265358979323846)
        tau = np.float32(6.28318530717958647692)
        while result > pi:
            result = np.float32(result - tau)
        while result < -pi:
            result = np.float32(result + tau)
        return result

    @classmethod
    def _sin_approx_f32(cls, value: np.float32) -> np.float32:
        x = cls._wrap_pi_f32(value)
        x2 = np.float32(x * x)
        polynomial = np.float32(-0.0000000250521084)
        polynomial = np.float32(np.float32(0.0000027557319224) + x2 * polynomial)
        polynomial = np.float32(np.float32(-0.0001984126984127) + x2 * polynomial)
        polynomial = np.float32(np.float32(0.0083333333333333) + x2 * polynomial)
        polynomial = np.float32(np.float32(-0.1666666666666667) + x2 * polynomial)
        return np.float32(x * np.float32(np.float32(1.0) + x2 * polynomial))

    @classmethod
    def _cos_approx_f32(cls, value: np.float32) -> np.float32:
        x = cls._wrap_pi_f32(value)
        x2 = np.float32(x * x)
        polynomial = np.float32(0.0000000020876757)
        polynomial = np.float32(np.float32(-0.0000002755731922) + x2 * polynomial)
        polynomial = np.float32(np.float32(0.0000248015873016) + x2 * polynomial)
        polynomial = np.float32(np.float32(-0.0013888888888889) + x2 * polynomial)
        polynomial = np.float32(np.float32(0.0416666666666667) + x2 * polynomial)
        polynomial = np.float32(np.float32(-0.5) + x2 * polynomial)
        return np.float32(np.float32(1.0) + x2 * polynomial)

    @staticmethod
    def _rope(value: np.ndarray, positions: np.ndarray) -> np.ndarray:
        """Apply the Nano model's deterministic rotary position encoding."""
        source = np.asarray(value, dtype=np.float32)
        dimension = source.shape[-1]
        if dimension % 2:
            raise ValueError("RoPE dimension must be even")
        rotated = np.empty_like(source)
        location = np.asarray(positions, dtype=np.float32).reshape(-1)
        inverse = np.power(
            np.float32(10_000.0),
            -np.arange(0, dimension, 2, dtype=np.float32) / np.float32(dimension),
        ).astype(np.float32)
        rows = source.reshape(-1, dimension)
        output_rows = rotated.reshape(-1, dimension)
        for row_index, row in enumerate(rows):
            for pair in range(dimension // 2):
                angle = np.float32(location[row_index] * inverse[pair])
                cosine = QuantizedNanoChatRuntime._cos_approx_f32(angle)
                sine = QuantizedNanoChatRuntime._sin_approx_f32(angle)
                even = np.float32(row[pair * 2])
                odd = np.float32(row[pair * 2 + 1])
                output_rows[row_index, pair * 2] = np.float32(
                    np.float32(even * cosine) - np.float32(odd * sine)
                )
                output_rows[row_index, pair * 2 + 1] = np.float32(
                    np.float32(even * sine) + np.float32(odd * cosine)
                )
        return as_bfloat16(rotated)

    @staticmethod
    def _exp_negative_f32(value: np.float32) -> np.float32:
        source = np.float32(value)
        if source <= np.float32(-16.0):
            return np.float32(0.0)
        if source >= np.float32(0.0):
            return np.float32(1.0)
        result = np.float32(np.float32(1.0) + source / np.float32(256.0))
        for _ in range(8):
            result = np.float32(result * result)
        return result if result > np.float32(0.0) else np.float32(0.0)

    def _project_cache(
        self, normalised: np.ndarray, layer: int, position_start: int
    ) -> dict[str, np.ndarray]:
        positions = np.arange(
            position_start, position_start + len(normalised), dtype=np.int64
        )
        return {
            "ckv": self._matmul(normalised, "attention_ckv", self.arrays["attention_ckv"][layer]),
            "kpe": self._rope(
                self._matmul(normalised, "attention_kpe", self.arrays["attention_kpe"][layer]),
                positions,
            ),
            "index_k": self._matmul(normalised, "attention_index_k", self.arrays["attention_index_k"][layer]),
        }

    def _quantize_mla_cache(self, ckv, kpe):
        """Legacy layout; narrower deployment ABIs can share packed K/V bytes."""
        value_i8, value_scale = self._activation(ckv)
        key_i8, key_scale = self._activation(np.concatenate((ckv, kpe), axis=-1))
        return key_i8, key_scale, value_i8, value_scale

    def _attention_rows(
        self, queries: np.ndarray, cache: dict[str, np.ndarray], layer: int,
        *, prefill: bool,
    ) -> np.ndarray:
        p = self.profile
        ckv = cache["ckv"]
        kpe = cache["kpe"]
        index_k = cache["index_k"]
        k_mla_i8, k_mla_scale, ckv_i8, value_scale = self._quantize_mla_cache(ckv, kpe)
        index_k_i8, index_k_scale = self._activation(index_k)
        query_mla = np.empty(
            (len(queries), p.heads, p.d_nope + p.d_rope), dtype=np.float32
        )
        query_index = np.empty(
            (len(queries), p.heads, p.indexer_dim), dtype=np.float32
        )
        first_query_position = len(ckv) - len(queries)
        for query_offset, query in enumerate(queries):
            query_position = first_query_position + query_offset
            for head in range(p.heads):
                q_nope = self._matmul(
                    query, "attention_q_nope",
                    self.arrays["attention_q_nope"][layer, head],
                )
                q_pe = self._rope(
                    self._matmul(
                        query, "attention_q_pe",
                        self.arrays["attention_q_pe"][layer, head],
                    )[None, :],
                    np.asarray([query_position], dtype=np.int64),
                )[0]
                query_mla[query_offset, head] = np.concatenate((q_nope, q_pe))
                query_index[query_offset, head] = self._matmul(
                    query, "attention_index_q",
                    self.arrays["attention_index_q"][layer, head],
                )
        # Descriptor v1 carries one Indexer scale and one MLA score scale.
        # Quantize the complete query/head batch with those shared scales,
        # exactly as the LiteX packer and P1/P2 RTL do.
        query_mla_i8, query_mla_scale = self._activation(query_mla)
        query_index_i8, query_index_scale = self._activation(query_index)
        score_scale = self._clamp_scale_fp32(
            float(
                np.float32(query_mla_scale)
                * np.float32(k_mla_scale)
                / np.float32(np.sqrt(p.d_nope + p.d_rope))
            )
        )
        self.attention_input_trace.append({
            "phase": "prefill" if prefill else "decode",
            "layer": layer,
            "query_mla_i8": query_mla_i8.copy(),
            "query_index_i8": query_index_i8.copy(),
            "k_mla_i8": k_mla_i8.copy(),
            "index_k_i8": index_k_i8.copy(),
            "value_i8": ckv_i8.copy(),
            "index_scale": self._clamp_scale_fp32(
                float(np.float32(query_index_scale) * np.float32(index_k_scale))
            ),
            "score_scale": score_scale,
            "value_scale": self._clamp_scale_fp32(value_scale),
        })
        self.attention_scale_trace.append({
            "phase": "prefill" if prefill else "decode",
            "layer": layer,
            "mla_query_scale": query_mla_scale,
            "index_query_scale": query_index_scale,
        })
        output_rows: list[np.ndarray] = []
        for query_offset, query in enumerate(queries):
            query_position = first_query_position + query_offset
            visible_count = query_position + 1
            head_values: list[np.ndarray] = []
            for head in range(p.heads):
                q_mla_i8 = query_mla_i8[query_offset, head]
                index_q_i8 = query_index_i8[query_offset, head]
                visible = np.arange(visible_count, dtype=np.int64)
                if prefill:
                    score_i32 = index_k_i8[:visible_count].astype(np.int32) @ index_q_i8.astype(np.int32)
                    multiplier = self._clamp_scale_fp32(
                        float(
                            np.float32(query_index_scale)
                            * np.float32(index_k_scale)
                        )
                    )
                    score_q = np.asarray(
                        [int32_scale_to_q5_11(int(item), multiplier) for item in score_i32],
                        dtype=np.int16,
                    )
                    order = stable_topk(score_q.astype(np.float32), min(self.PREFILL_TOPK, visible_count))
                    visible = visible[order]
                if prefill:
                    head_value = attention_rtl_oracle(
                        q_mla_i8, k_mla_i8[visible], ckv_i8[visible],
                        score_scale=score_scale,
                        value_scale=self._clamp_scale_fp32(value_scale),
                    )
                else:
                    # P2 exposes a scalar output seam, so preserve its exact
                    # lane-by-lane rounding while sharing score order.
                    head_value = np.concatenate([
                        attention_rtl_oracle(
                            q_mla_i8, k_mla_i8[:visible_count], ckv_i8[:visible_count, lane : lane + 1],
                            score_scale=score_scale,
                            value_scale=self._clamp_scale_fp32(value_scale),
                        ) for lane in range(p.value_dim)
                    ])
                head_values.append(head_value)
            attended = np.concatenate(head_values)
            projected = self._matmul(
                attended, "attention_out", self.arrays["attention_out"][layer]
            )
            if query_offset + 1 == len(queries):
                phase = "prefill" if prefill else "decode"
                self.boundary_trace.append({
                    "phase": phase, "layer": layer,
                    "boundary": "p1_output" if prefill else "p2_output",
                    "value": np.asarray(attended, dtype=np.float32).copy(),
                })
                self.boundary_trace.append({
                    "phase": phase, "layer": layer,
                    "boundary": "attention_projected",
                    "value": np.asarray(projected, dtype=np.float32).copy(),
                })
            output_rows.append(projected)
        return np.stack(output_rows)

    def _expert(self, value: np.ndarray, layer: int, expert: int, weight: float, *, shared: bool) -> np.ndarray:
        prefix = "shared_" if shared else ""
        gate = self.arrays[f"{prefix}gate"][layer] if shared else self.arrays["gate"][layer, expert]
        up = self.arrays[f"{prefix}up"][layer] if shared else self.arrays["up"][layer, expert]
        down = self.arrays[f"{prefix}down"][layer] if shared else self.arrays["down"][layer, expert]
        activation, activation_scale = self._activation(value)
        return moe_expert_rtl_oracle(
            activation[None, :], gate.T[None, :, :], up.T[None, :, :], down.T[None, :, :],
            np.asarray([0], dtype=np.int32), np.asarray([weight], dtype=np.float32),
            input_scale=activation_scale,
            gate_scale=self.scales[f"{prefix}gate"], up_scale=self.scales[f"{prefix}up"],
            intermediate_scale=NANO_P3_INTERMEDIATE_SCALE,
            down_scale=self.scales[f"{prefix}down"],
        )[0]

    def _moe_rows(self, value: np.ndarray, layer: int) -> np.ndarray:
        normalised = self._rmsnorm(value, "moe_norm", layer)
        outputs: list[np.ndarray] = []
        for row in normalised:
            logits = self._matmul(row, "router", self.arrays["router"][layer])
            selected = np.lexsort((np.arange(self.profile.experts), -logits))[: self.profile.active_experts]
            selected_logits = logits[selected].astype(np.float32)
            maximum = np.max(selected_logits).astype(np.float32)
            weights = np.asarray(
                [self._exp_negative_f32(np.float32(item - maximum))
                 for item in selected_logits],
                dtype=np.float32,
            )
            denominator = np.float32(np.sum(weights, dtype=np.float32))
            weights = np.asarray(
                [np.float32(item / denominator) for item in weights],
                dtype=np.float32,
            )
            routed = np.zeros(self.profile.hidden, dtype=np.float32)
            for route_weight, expert in zip(weights, selected, strict=True):
                self.operation_trace.append(f"P3_ROUTED:{layer}:{int(expert)}")
                routed += self._expert(row, layer, int(expert), float(route_weight), shared=False)
            self.operation_trace.append(f"P3_SHARED:{layer}:{self.profile.experts}")
            routed += self._expert(row, layer, self.profile.experts, 1.0, shared=True)
            outputs.append(routed)
        return np.stack(outputs)

    def _embedding(
        self, token_ids: list[int], *, establish_intent: bool = False,
        response_position: int | None = None,
    ) -> np.ndarray:
        tokens = np.asarray(token_ids, dtype=np.int64)
        if np.any(tokens < 0) or np.any(tokens >= self.profile.vocab):
            raise ValueError("token id outside vocabulary")
        # Firmware performs embedding/context additions in FP32 and rounds to
        # BF16 once at the architectural boundary.  Rounding the token table
        # before adding intent/subject context changes later dynamic scales.
        value = (
            self.arrays["embedding"][tokens].astype(np.float32)
            * np.float32(self.scales["embedding"])
        )
        if establish_intent:
            assistant_boundary = np.flatnonzero(tokens == 4)
            if len(assistant_boundary):
                value[int(assistant_boundary[0]) :] = 0.0
        elif response_position is not None:
            value.fill(0.0)
        if establish_intent:
            assistant = np.flatnonzero(tokens == 4)
            stop = int(assistant[0]) if len(assistant) else len(tokens)
            content_tokens = tokens[:stop][tokens[:stop] > 4]
            if len(content_tokens) < 2:
                raise ValueError("prompt contains fewer than two ordinary content tokens")
            pair_hash = (
                content_tokens[:-1].astype(np.int64) * 2053
                + content_tokens[1:].astype(np.int64)
            ) % len(self.arrays["intent_ngram"])
            unigram_hash = (
                content_tokens.astype(np.int64) * 17 + 1
            ) % len(self.arrays["intent_ngram"])
            intent_table = self.arrays["intent_ngram"]
            pair_logits = self._dequant(
                "intent_ngram", intent_table[pair_hash]
            )
            unigram_logits = self._dequant(
                "intent_ngram", intent_table[unigram_hash]
            )
            logits = np.sum(pair_logits, axis=0) + np.sum(unigram_logits, axis=0)
            subject_logits = self._matmul(
                logits, "subject_classifier", self.arrays["subject_classifier"]
            )
            self._subject_id = int(np.argmax(subject_logits))
            # subject_id is defined as intent_id * 4 + subject_index.  Keep a
            # single deployment decision so independently calibrated intent
            # and subject heads cannot select contradictory contexts.
            self._intent_id = self._subject_id // 4
            self.operation_trace.append(f"INTENT:{self._intent_id}")
            self.operation_trace.append(f"SUBJECT:{self._subject_id}")
        if self._intent_id is None:
            raise RuntimeError("intent must be established by prefill")
        if self._subject_id is None:
            raise RuntimeError("subject must be established by prefill")
        intent_context = (
            self.arrays["intent_embedding"][self._intent_id].astype(np.float32)
            * np.float32(self.scales["intent_embedding"])
        )
        subject_context = (
            self.arrays["subject_embedding"][self._subject_id].astype(np.float32)
            * np.float32(self.scales["subject_embedding"])
        )
        value = np.float32(value + intent_context)
        value = np.float32(value + subject_context)
        if establish_intent:
            assistant = np.flatnonzero(tokens == 4)
            if len(assistant):
                position_value = (
                    self.arrays["response_position_embedding"][0].astype(np.float32)
                    * np.float32(self.scales["response_position_embedding"])
                )
                value[int(assistant[0]) :] = np.float32(
                    value[int(assistant[0]) :] + position_value
                )
            self._response_position = 0
        elif response_position is not None:
            if not 0 <= response_position < len(self.arrays["response_position_embedding"]):
                raise ValueError("response position outside frozen generation budget")
            position_value = (
                self.arrays["response_position_embedding"][response_position].astype(np.float32)
                * np.float32(self.scales["response_position_embedding"])
            )
            value = np.float32(value + position_value)
        return as_bfloat16(value)

    def _logits(self, hidden: np.ndarray) -> np.ndarray:
        final = self._rmsnorm(hidden, "final_norm", None)
        self.last_hidden = np.asarray(final, dtype=np.float32).copy()
        return self._matmul(final, "lm_head", self.arrays["lm_head"].T)

    def current_hidden(self) -> np.ndarray:
        """Return the last exact final-normalized state for head calibration."""
        if self.last_hidden is None:
            raise RuntimeError("no prefill/decode state has been evaluated")
        return self.last_hidden.copy()

    def prefill(self, prompt: list[int]) -> np.ndarray:
        if not prompt or len(prompt) > self.profile.context:
            raise ValueError("prompt length outside context")
        self.operation_trace.clear()
        self._cache = []
        self._intent_id = None
        self._subject_id = None
        self._response_position = 0
        self.hidden_trace.clear()
        self.boundary_trace.clear()
        self.attention_scale_trace.clear()
        self.attention_input_trace.clear()
        hidden = self._embedding(prompt, establish_intent=True)
        for layer in range(self.profile.layers):
            normalised = self._rmsnorm(hidden, "attention_norm", layer)
            self.boundary_trace.append({
                "phase": "prefill", "layer": layer,
                "boundary": "attention_norm",
                "value": np.asarray(normalised[-1], dtype=np.float32).copy(),
            })
            cache = self._project_cache(normalised, layer, 0)
            self._cache.append(cache)
            self.operation_trace.append(f"P1_PREFILL:{layer}")
            attention = self._attention_rows(normalised, cache, layer, prefill=True)
            hidden = as_bfloat16(hidden + attention)
            self.boundary_trace.append({
                "phase": "prefill", "layer": layer,
                "boundary": "attention_residual",
                "value": np.asarray(hidden[-1], dtype=np.float32).copy(),
            })
            hidden = as_bfloat16(hidden + self._moe_rows(hidden, layer))
            self.boundary_trace.append({
                "phase": "prefill", "layer": layer,
                "boundary": "moe_residual",
                "value": np.asarray(hidden[-1], dtype=np.float32).copy(),
            })
            self.hidden_trace.append(np.asarray(hidden[-1], dtype=np.float32).copy())
        return self._logits(hidden[-1])

    def decode(self, token: int) -> np.ndarray:
        if len(self._cache) != self.profile.layers:
            raise RuntimeError("decode requires a completed prefill")
        self._response_position += 1
        hidden = self._embedding(
            [token], response_position=self._response_position
        )
        for layer in range(self.profile.layers):
            normalised = self._rmsnorm(hidden, "attention_norm", layer)
            self.boundary_trace.append({
                "phase": "decode", "layer": layer,
                "boundary": "attention_norm",
                "value": np.asarray(normalised[0], dtype=np.float32).copy(),
            })
            projected = self._project_cache(normalised, layer, len(self._cache[layer]["ckv"]))
            cache = self._cache[layer]
            for name in cache:
                cache[name] = np.concatenate((cache[name], projected[name]), axis=0)
            self.operation_trace.append(f"P2_DECODE:{layer}")
            attention = self._attention_rows(normalised, cache, layer, prefill=False)
            hidden = as_bfloat16(hidden + attention)
            self.boundary_trace.append({
                "phase": "decode", "layer": layer,
                "boundary": "attention_residual",
                "value": np.asarray(hidden[0], dtype=np.float32).copy(),
            })
            hidden = as_bfloat16(hidden + self._moe_rows(hidden, layer))
            self.boundary_trace.append({
                "phase": "decode", "layer": layer,
                "boundary": "moe_residual",
                "value": np.asarray(hidden[0], dtype=np.float32).copy(),
            })
            self.hidden_trace.append(np.asarray(hidden[0], dtype=np.float32).copy())
        return self._logits(hidden[0])

    def generate(
        self, prompt: list[int], count: int = 32, eos_id: int = 1,
        tokenizer: "ByteBPETokenizer | None" = None,
    ) -> list[int]:
        if count < 0:
            raise ValueError("count cannot be negative")
        result: list[int] = []
        logits = self.prefill(prompt)
        for step in range(count):
            if tokenizer is None:
                token = int(np.argmax(logits))
            else:
                ranked = np.lexsort((np.arange(len(logits)), -logits))
                token = tokenizer.select_utf8_constrained_token(
                    ranked, result, eos_id, final=step + 1 == count,
                )
            result.append(token)
            if token == eos_id:
                break
            if step + 1 < count:
                logits = self.decode(token)
        return result
