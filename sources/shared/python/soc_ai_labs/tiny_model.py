"""Deterministic host-trained tiny MoE models for the LiteX system path.

This is a scaled learning model, not a claim about unpublished DeepSeek
weights.  Training and export run on the host; the SoC consumes INT8 weights.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np

from .litex_contract import TinyModelProfile
from .numeric import as_bfloat16
from .dsa import stable_topk
from .rtl_oracle import (
    Q11_SCALE,
    attention_rtl_oracle,
    int32_scale_to_q5_11,
    moe_expert_rtl_oracle,
    q5_11_value,
    quantize_int8_rne,
    silu_q11,
)


NANO_PROMPT = [68, 101, 101, 112, 83, 101, 101, 107]
NANO_RUNTIME_SEMANTICS = "p1-p2-native-kv-cache-v2"
LEGACY_NANO_GOLDEN_TOKENS_SHA256 = (
    "d0dfbeb22dc42305fd82dd5f06c4c161595c7ce8bef4c16a4378bde577f4b7ea"
)
NANO_P3_INTERMEDIATE_SCALE = 2.0**-6


def _silu(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, -30.0, 30.0)
    return value / (1.0 + np.exp(-clipped))


class TinyMoELanguageModel:
    """Small causal attention + top-k MoE model with a tied LM head."""

    def __init__(self, profile: TinyModelProfile, *, seed: int = 1) -> None:
        self.profile = profile
        rng = np.random.default_rng(seed)
        h = profile.hidden
        scale = np.float32(1.0 / np.sqrt(h))
        self.weights: dict[str, np.ndarray] = {
            "embedding": rng.normal(0, scale, (profile.vocab, h)).astype(np.float32),
            "attention_q_nope": rng.normal(
                0, scale, (profile.layers, profile.heads, h, 8)
            ).astype(np.float32),
            "attention_q_pe": rng.normal(
                0, scale, (profile.layers, profile.heads, h, 4)
            ).astype(np.float32),
            "attention_index_q": rng.normal(
                0, scale, (profile.layers, profile.heads, h, 8)
            ).astype(np.float32),
            "attention_ckv": rng.normal(0, scale, (profile.layers, h, 8)).astype(np.float32),
            "attention_kpe": rng.normal(0, scale, (profile.layers, h, 4)).astype(np.float32),
            "attention_index_k": rng.normal(
                0, scale, (profile.layers, h, 8)
            ).astype(np.float32),
            "attention_out": rng.normal(
                0, scale, (profile.layers, profile.heads * 8, h)
            ).astype(np.float32),
            "router": rng.normal(0, scale, (profile.layers, h, profile.experts)).astype(np.float32),
            "gate": rng.normal(
                0, scale, (profile.layers, profile.experts, h, profile.intermediate)
            ).astype(np.float32),
            "up": rng.normal(
                0, scale, (profile.layers, profile.experts, h, profile.intermediate)
            ).astype(np.float32),
            "down": rng.normal(
                0, 1.0 / np.sqrt(profile.intermediate),
                (profile.layers, profile.experts, profile.intermediate, h),
            ).astype(np.float32),
            "shared_gate": rng.normal(
                0, scale, (profile.layers, h, profile.intermediate)
            ).astype(np.float32),
            "shared_up": rng.normal(
                0, scale, (profile.layers, h, profile.intermediate)
            ).astype(np.float32),
            "shared_down": rng.normal(
                0, 1.0 / np.sqrt(profile.intermediate),
                (profile.layers, profile.intermediate, h),
            ).astype(np.float32),
        }

    def _hidden(self, prefix: list[int]) -> np.ndarray:
        if not prefix or len(prefix) > self.profile.context:
            raise ValueError("prefix length must be within the configured context")
        tokens = np.asarray(prefix, dtype=np.int64)
        if np.any(tokens < 0) or np.any(tokens >= self.profile.vocab):
            raise ValueError("token id outside the configured vocabulary")
        history = self.weights["embedding"][tokens]
        x = history[-1].copy()
        for layer in range(self.profile.layers):
            ckv = history @ self.weights["attention_ckv"][layer]
            kpe = history @ self.weights["attention_kpe"][layer]
            index_k = history @ self.weights["attention_index_k"][layer]
            head_values: list[np.ndarray] = []
            for head in range(self.profile.heads):
                q_nope = x @ self.weights["attention_q_nope"][layer, head]
                q_pe = x @ self.weights["attention_q_pe"][layer, head]
                index_q = x @ self.weights["attention_index_q"][layer, head]
                index_scores = index_k @ index_q
                selected = stable_topk(
                    index_scores.astype(np.float32), min(32, len(index_scores))
                )
                scores = (
                    ckv[selected] @ q_nope + kpe[selected] @ q_pe
                ) / np.sqrt(12.0)
                probabilities = np.exp(scores - np.max(scores))
                probabilities /= probabilities.sum()
                head_values.append(probabilities @ ckv[selected])
            attention_value = np.concatenate(head_values)
            x = x + attention_value @ self.weights["attention_out"][layer]

            route_logits = x @ self.weights["router"][layer]
            order = np.lexsort((np.arange(self.profile.experts), -route_logits))
            selected = order[: self.profile.active_experts]
            selected_logits = route_logits[selected].astype(np.float64)
            selected_weights = np.exp(selected_logits - np.max(selected_logits))
            selected_weights /= selected_weights.sum()
            moe = np.zeros_like(x)
            for route_weight, expert in zip(selected_weights, selected, strict=True):
                gate_value = x @ self.weights["gate"][layer, expert]
                up_value = x @ self.weights["up"][layer, expert]
                expert_value = (_silu(gate_value) * up_value) @ self.weights["down"][layer, expert]
                moe += np.float32(route_weight) * expert_value
            shared_gate = x @ self.weights["shared_gate"][layer]
            shared_up = x @ self.weights["shared_up"][layer]
            moe += (_silu(shared_gate) * shared_up) @ self.weights["shared_down"][layer]
            x = x + moe
            norm = np.sqrt(np.mean(x.astype(np.float64) ** 2) + 1e-6)
            x = (x / np.float32(norm)).astype(np.float32)
        return x

    def logits(self, prefix: list[int]) -> np.ndarray:
        return self._hidden(prefix) @ self.weights["embedding"].T

    def loss(self, tokens: list[int]) -> float:
        if len(tokens) < 2:
            raise ValueError("training corpus needs at least two tokens")
        losses: list[float] = []
        for index in range(1, len(tokens)):
            begin = max(0, index - self.profile.context)
            logits = self.logits(tokens[begin:index]).astype(np.float64)
            logits -= np.max(logits)
            logsumexp = np.log(np.exp(logits).sum())
            losses.append(float(logsumexp - logits[tokens[index]]))
        return float(np.mean(losses))

    def train_lm_head(self, tokens: list[int], *, epochs: int = 4, learning_rate: float = 0.05) -> list[float]:
        """Deterministically train the tied embedding/LM head on local tokens."""
        if epochs < 1 or learning_rate <= 0:
            raise ValueError("epochs and learning_rate must be positive")
        history = [self.loss(tokens)]
        for _ in range(epochs):
            gradients = np.zeros_like(self.weights["embedding"])
            for index in range(1, len(tokens)):
                begin = max(0, index - self.profile.context)
                hidden = self._hidden(tokens[begin:index])
                logits = hidden @ self.weights["embedding"].T
                logits = logits.astype(np.float64)
                probabilities = np.exp(logits - np.max(logits))
                probabilities /= probabilities.sum()
                probabilities[tokens[index]] -= 1.0
                gradients += np.outer(probabilities.astype(np.float32), hidden)
            gradients /= np.float32(len(tokens) - 1)
            np.clip(gradients, -1.0, 1.0, out=gradients)
            self.weights["embedding"] -= np.float32(learning_rate) * gradients
            history.append(self.loss(tokens))
        return history

    def generate(self, prompt: list[int], *, count: int | None = None) -> list[int]:
        count = self.profile.max_generated_tokens if count is None else count
        if count < 0:
            raise ValueError("generation count cannot be negative")
        tokens = list(prompt)
        for _ in range(count):
            prefix = tokens[-self.profile.context :]
            tokens.append(int(np.argmax(self.logits(prefix))))
        return tokens

    def state_hash(self) -> str:
        digest = hashlib.sha256()
        digest.update(json.dumps(asdict(self.profile), sort_keys=True).encode("utf-8"))
        for name in sorted(self.weights):
            value = np.ascontiguousarray(self.weights[name])
            digest.update(name.encode("ascii"))
            digest.update(str(value.shape).encode("ascii"))
            digest.update(value.tobytes())
        return digest.hexdigest()

    def export_quantized(self, destination: Path) -> dict[str, object]:
        arrays: dict[str, np.ndarray] = {}
        scales: dict[str, float] = {}
        for name, value in self.weights.items():
            peak = float(np.max(np.abs(value)))
            scale = peak / 127.0 if peak else 1.0
            arrays[name] = np.clip(np.rint(value / scale), -128, 127).astype(np.int8)
            scales[name] = scale
        runtime = QuantizedTinyRuntime(self.profile, arrays=arrays, scales=scales)
        generated = runtime.generate(NANO_PROMPT)
        generated_only = generated[-self.profile.max_generated_tokens :]
        token_bytes = np.asarray(generated_only, dtype="<u4").tobytes()
        metadata = {
            "profile": asdict(self.profile),
            "source_state_sha256": self.state_hash(),
            "quantization": "symmetric-int8-rne-per-tensor",
            "scales": scales,
            "golden_prompt": NANO_PROMPT,
            "golden_tokens": generated_only,
            "golden_tokens_sha256": hashlib.sha256(token_bytes).hexdigest(),
            "runtime_semantics": NANO_RUNTIME_SEMANTICS,
            "legacy_golden_tokens_sha256": LEGACY_NANO_GOLDEN_TOKENS_SHA256,
            "p3_intermediate_scale": NANO_P3_INTERMEDIATE_SCALE,
        }
        arrays["metadata_utf8"] = np.frombuffer(
            json.dumps(metadata, sort_keys=True).encode("utf-8"), dtype=np.uint8
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(destination, **arrays)
        return metadata


class QuantizedTinyRuntime:
    """Deterministic INT8 checkpoint runtime used as the nano SoC oracle.

    Matrix products accumulate INT8 products in INT32. Activations are
    dynamically quantized with RNE/saturation and architectural boundaries are
    rounded to BF16. ``operation_trace`` exposes which accelerator opcode the
    firmware must issue; it is not a substitute for RTL cycle evidence.
    """

    def __init__(
        self,
        profile: TinyModelProfile,
        *,
        arrays: dict[str, np.ndarray],
        scales: dict[str, float],
    ) -> None:
        self.profile = profile
        self.arrays = {name: np.asarray(value, dtype=np.int8) for name, value in arrays.items()}
        self.scales = {name: float(value) for name, value in scales.items()}
        self.operation_trace: list[str] = []

    @classmethod
    def from_npz(cls, checkpoint: Path) -> "QuantizedTinyRuntime":
        with np.load(checkpoint) as archive:
            metadata = json.loads(bytes(archive["metadata_utf8"]).decode("utf-8"))
            profile = TinyModelProfile(**metadata["profile"])
            arrays = {
                name: archive[name].copy()
                for name in archive.files
                if name != "metadata_utf8"
            }
        return cls(profile, arrays=arrays, scales=metadata["scales"])

    @staticmethod
    def _activation(value: np.ndarray) -> tuple[np.ndarray, float]:
        source = np.asarray(value, dtype=np.float32)
        peak = float(np.max(np.abs(source))) if source.size else 0.0
        scale = peak / 127.0 if peak else 1.0
        return quantize_int8_rne(source, scale=scale), scale

    def _matmul(self, value: np.ndarray, weight_name: str, weight: np.ndarray) -> np.ndarray:
        activation, activation_scale = self._activation(value)
        result = activation.astype(np.int32) @ np.asarray(weight, dtype=np.int8).astype(np.int32)
        scaled = result.astype(np.float32) * np.float32(activation_scale * self.scales[weight_name])
        return as_bfloat16(scaled)

    @staticmethod
    def _fixed_silu(value: np.ndarray) -> np.ndarray:
        """Evaluate the same Q5.11 -> Q5.6 LUT path used by B0 RTL."""
        source = np.asarray(value, dtype=np.float32)
        flattened = source.reshape(-1)
        result = np.asarray(
            [silu_q11(q5_11_value(float(item))) for item in flattened],
            dtype=np.float32,
        )
        return (result.reshape(source.shape) / np.float32(Q11_SCALE)).astype(np.float32)

    def _embedding(self, tokens: np.ndarray) -> np.ndarray:
        values = self.arrays["embedding"][tokens].astype(np.float32)
        return as_bfloat16(values * np.float32(self.scales["embedding"]))

    def _p1_p2_attention(
        self, history: np.ndarray, x: np.ndarray, layer: int, *, prefill: bool
    ) -> np.ndarray:
        """Run the frozen INT8 P1/P2 attention seam used by nano firmware.

        Nano deliberately uses one query row per layer.  P1 scans the visible
        prompt, applies the deterministic indexer Top-K contract and then MLA;
        P2 scans the whole decode cache with split=1.  Both paths share the
        bit-stable online-softmax oracle and BF16 boundary.
        """
        # KV projection is token-local: once a token enters the paged cache its
        # BF16 cKV/kPE/Indexer record remains stable across later decode steps.
        # This is essential for the firmware and P1/P2 to share a real cache,
        # rather than silently recomputing old keys with a changing batch scale.
        ckv = np.stack([
            self._matmul(row, "attention_ckv", self.arrays["attention_ckv"][layer])
            for row in history
        ])
        kpe = np.stack([
            self._matmul(row, "attention_kpe", self.arrays["attention_kpe"][layer])
            for row in history
        ])
        index_k = np.stack([
            self._matmul(row, "attention_index_k", self.arrays["attention_index_k"][layer])
            for row in history
        ])
        ckv_i8, value_scale = self._activation(ckv)
        q_nope_all = [
            self._matmul(
                x, "attention_q_nope", self.arrays["attention_q_nope"][layer, head]
            )
            for head in range(self.profile.heads)
        ]
        q_pe_all = [
            self._matmul(
                x, "attention_q_pe", self.arrays["attention_q_pe"][layer, head]
            )
            for head in range(self.profile.heads)
        ]
        index_q_all = [
            self._matmul(
                x, "attention_index_q", self.arrays["attention_index_q"][layer, head]
            )
            for head in range(self.profile.heads)
        ]
        # P1's descriptor carries one Indexer scale and one MLA score scale.
        # Quantize the four compiled heads as one tensor so the host oracle and
        # the single hardware command share exactly that frozen seam.
        q_mla_all_i8, q_mla_scale = self._activation(
            np.concatenate(
                [np.concatenate((q_nope, q_pe)) for q_nope, q_pe in zip(q_nope_all, q_pe_all, strict=True)]
            )
        )
        index_q_all_i8, index_q_scale = self._activation(np.concatenate(index_q_all))
        head_values: list[np.ndarray] = []
        for head in range(self.profile.heads):
            q_mla_i8 = q_mla_all_i8[head * 12 : (head + 1) * 12]
            k_mla_i8, k_mla_scale = self._activation(
                np.concatenate((ckv, kpe), axis=1)
            )
            index_q_i8 = index_q_all_i8[head * 8 : (head + 1) * 8]
            index_k_i8, index_k_scale = self._activation(index_k)
            visible = np.arange(len(history), dtype=np.int64)
            if prefill:
                index_scores_i32 = index_k_i8.astype(np.int32) @ index_q_i8.astype(np.int32)
                index_multiplier = max(
                    2.0**-16, min(2.0**16, index_q_scale * index_k_scale)
                )
                index_scores = np.asarray(
                    [
                        int32_scale_to_q5_11(int(score), index_multiplier)
                        for score in index_scores_i32
                    ],
                    dtype=np.int16,
                )
                selected = stable_topk(
                    index_scores.astype(np.float32), min(32, len(index_scores))
                )
                # P1 emits the stable Top-K stream in score order and the
                # fixed-point online-softmax state consumes that same stream.
                # Re-sorting by token id here would be a different rounding
                # order from the hardware even though real-valued softmax is
                # mathematically permutation-invariant.
                visible = selected.astype(np.int64)
            score_scale = max(
                2.0**-16,
                min(2.0**16, q_mla_scale * k_mla_scale / np.sqrt(12.0)),
            )
            if prefill:
                head_value = attention_rtl_oracle(
                    q_mla_i8, k_mla_i8[visible], ckv_i8[visible],
                    score_scale=score_scale,
                    value_scale=max(2.0**-16, min(2.0**16, value_scale)),
                )
            else:
                # P2's frozen interface emits one BF16 value.  Calling the
                # same scalar contract for all eight cKV lanes is equivalent
                # to a vector softmax while preserving the real hardware seam.
                head_value = np.concatenate([
                    attention_rtl_oracle(
                        q_mla_i8, k_mla_i8,
                        ckv_i8[:, lane : lane + 1],
                        score_scale=score_scale,
                        value_scale=max(2.0**-16, min(2.0**16, value_scale)),
                    )
                    for lane in range(8)
                ])
            # Keep the separately quantized indexer scale live in the model
            # contract even though only its integer ordering selects Top-K.
            _ = index_q_scale * index_k_scale
            head_values.append(head_value)
        attended = np.concatenate(head_values)
        return self._matmul(
            attended, "attention_out", self.arrays["attention_out"][layer]
        )

    def _hidden(self, prefix: list[int], *, prefill: bool) -> np.ndarray:
        if not prefix or len(prefix) > self.profile.context:
            raise ValueError("prefix length must be within the configured context")
        tokens = np.asarray(prefix, dtype=np.int64)
        if np.any(tokens < 0) or np.any(tokens >= self.profile.vocab):
            raise ValueError("token id outside the configured vocabulary")
        history = self._embedding(tokens)
        x = history[-1].copy()
        for layer in range(self.profile.layers):
            self.operation_trace.append("P1_PREFILL" if prefill else "P2_DECODE")
            projected = self._p1_p2_attention(history, x, layer, prefill=prefill)
            x = as_bfloat16(x + projected)

            route_logits = self._matmul(x, "router", self.arrays["router"][layer])
            order = np.lexsort((np.arange(self.profile.experts), -route_logits))
            selected = order[: self.profile.active_experts]
            route_weights = np.full(
                len(selected), 1.0 / len(selected), dtype=np.float32
            )
            moe = np.zeros_like(x)
            activation_i8, activation_scale = self._activation(x)
            for route_weight, expert in zip(route_weights, selected, strict=True):
                self.operation_trace.append(f"P3_ROUTED:{layer}:{int(expert)}")
                expert_value = moe_expert_rtl_oracle(
                    activation_i8[None, :],
                    self.arrays["gate"][layer, expert].T[None, :, :],
                    self.arrays["up"][layer, expert].T[None, :, :],
                    self.arrays["down"][layer, expert].T[None, :, :],
                    np.asarray([0], dtype=np.int32),
                    np.asarray([route_weight], dtype=np.float32),
                    input_scale=activation_scale,
                    gate_scale=self.scales["gate"],
                    up_scale=self.scales["up"],
                    intermediate_scale=NANO_P3_INTERMEDIATE_SCALE,
                    down_scale=self.scales["down"],
                )[0]
                moe += expert_value

            self.operation_trace.append(f"P3_SHARED:{layer}:{self.profile.experts}")
            moe += moe_expert_rtl_oracle(
                activation_i8[None, :],
                self.arrays["shared_gate"][layer].T[None, :, :],
                self.arrays["shared_up"][layer].T[None, :, :],
                self.arrays["shared_down"][layer].T[None, :, :],
                np.asarray([0], dtype=np.int32),
                np.asarray([1.0], dtype=np.float32),
                input_scale=activation_scale,
                gate_scale=self.scales["shared_gate"],
                up_scale=self.scales["shared_up"],
                intermediate_scale=NANO_P3_INTERMEDIATE_SCALE,
                down_scale=self.scales["shared_down"],
            )[0]
            x = as_bfloat16(x + moe)
            norm = np.sqrt(np.mean(x.astype(np.float64) ** 2) + 1e-6)
            x = as_bfloat16(x / np.float32(norm))
        return x

    def logits(self, prefix: list[int], *, prefill: bool) -> np.ndarray:
        hidden = self._hidden(prefix, prefill=prefill)
        embedding = self.arrays["embedding"].T
        return self._matmul(hidden, "embedding", embedding)

    def generate(self, prompt: list[int], *, count: int | None = None) -> list[int]:
        count = self.profile.max_generated_tokens if count is None else count
        if count < 0:
            raise ValueError("generation count cannot be negative")
        self.operation_trace.clear()
        tokens = list(prompt)
        for step in range(count):
            prefix = tokens[-self.profile.context :]
            tokens.append(int(np.argmax(self.logits(prefix, prefill=step == 0))))
        return tokens
