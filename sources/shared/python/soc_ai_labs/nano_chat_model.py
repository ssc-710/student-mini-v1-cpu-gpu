"""Trainable 4M-parameter P1/P2/P3-native Nano chat model."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .litex_contract import TinyModelProfile
from .rtl_oracle import Q11_SCALE, silu_q11_lut

if TYPE_CHECKING:
    from .chat_tokenizer import ByteBPETokenizer


_P3_INTERMEDIATE_SCALE = 0.015625


def _ste_symmetric_int8(
    value: torch.Tensor, *, per_row: bool = False,
    reduce_dims: tuple[int, ...] | None = None,
) -> torch.Tensor:
    """Symmetric INT8 fake quantization with an STE gradient."""
    if per_row and reduce_dims is not None:
        raise ValueError("choose per_row or explicit reduce_dims, not both")
    dimensions = reduce_dims if reduce_dims is not None else (
        (-1,) if per_row and value.ndim else None
    )
    peak = value.detach().abs().amax(dim=dimensions, keepdim=bool(dimensions))
    scale = torch.where(peak > 0, peak / 127.0, torch.ones_like(peak))
    quantized = torch.clamp(torch.round(value / scale), -128, 127) * scale
    return value + (quantized - value).detach()


def _ste_bfloat16(value: torch.Tensor) -> torch.Tensor:
    """Expose the architectural BF16 boundary while retaining FP32 gradients."""
    rounded = value.to(torch.bfloat16).to(value.dtype)
    return value + (rounded - value).detach()


def _qat_linear(module: nn.Linear, value: torch.Tensor, enabled: bool) -> torch.Tensor:
    if not enabled:
        return module(value)
    output = F.linear(
        _ste_symmetric_int8(value, per_row=True),
        _ste_symmetric_int8(module.weight),
    )
    return _ste_bfloat16(output)


def _ste_p3_intermediate(gate: torch.Tensor, up: torch.Tensor) -> torch.Tensor:
    """Approximate the exact Q5.11 -> SiLU ROM -> fixed INT8 P3 seam."""
    gate_q11 = torch.clamp(torch.round(gate * Q11_SCALE), -32768, 32767)
    up_q11 = torch.clamp(torch.round(up * Q11_SCALE), -32768, 32767)
    q6 = torch.clamp(torch.round(gate_q11 / 32.0), -1024, 1024).long()
    lut = torch.as_tensor(silu_q11_lut(), dtype=gate.dtype, device=gate.device)
    silu_fixed = lut[q6 + 1024] / Q11_SCALE
    silu_ste = F.silu(gate) + (silu_fixed - F.silu(gate)).detach()
    up_fixed = up_q11 / Q11_SCALE
    up_ste = up + (up_fixed - up).detach()
    product = silu_ste * up_ste
    fixed = torch.clamp(
        torch.round(product / _P3_INTERMEDIATE_SCALE), -128, 127
    ) * _P3_INTERMEDIATE_SCALE
    return product + (fixed - product).detach()


class RMSNorm(nn.Module):
    def __init__(self, hidden: int, epsilon: float = 1e-6) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.ones(hidden))
        self.epsilon = epsilon

    def forward(self, value: torch.Tensor, *, qat: bool = False) -> torch.Tensor:
        variance = value.float().square().mean(dim=-1, keepdim=True)
        normalised = value * torch.rsqrt(variance + self.epsilon).to(value.dtype)
        weight = _ste_symmetric_int8(self.weight) if qat else self.weight
        output = normalised * weight
        return _ste_bfloat16(output) if qat else output


class Expert(nn.Module):
    def __init__(self, hidden: int, intermediate: int) -> None:
        super().__init__()
        self.gate = nn.Linear(hidden, intermediate, bias=False)
        self.up = nn.Linear(hidden, intermediate, bias=False)
        self.down = nn.Linear(intermediate, hidden, bias=False)

    def forward(self, value: torch.Tensor, *, qat: bool = False) -> torch.Tensor:
        gate = _qat_linear(self.gate, value, qat)
        up = _qat_linear(self.up, value, qat)
        intermediate = (
            _ste_p3_intermediate(gate, up)
            if qat else F.silu(gate) * up
        )
        return _qat_linear(self.down, intermediate, qat)


class NanoChatBlock(nn.Module):
    def __init__(self, profile: TinyModelProfile) -> None:
        super().__init__()
        h = profile.hidden
        self.profile = profile
        self.attention_norm = RMSNorm(h)
        self.q_nope = nn.Linear(h, profile.heads * profile.d_nope, bias=False)
        self.q_pe = nn.Linear(h, profile.heads * profile.d_rope, bias=False)
        self.index_q = nn.Linear(h, profile.heads * profile.indexer_dim, bias=False)
        self.ckv = nn.Linear(h, profile.d_nope, bias=False)
        self.kpe = nn.Linear(h, profile.d_rope, bias=False)
        self.index_k = nn.Linear(h, profile.indexer_dim, bias=False)
        self.attention_out = nn.Linear(
            profile.heads * profile.value_dim, h, bias=False
        )
        self.moe_norm = RMSNorm(h)
        self.router = nn.Linear(h, profile.experts, bias=False)
        self.experts = nn.ModuleList(
            Expert(h, profile.intermediate) for _ in range(profile.experts)
        )
        self.shared = Expert(h, profile.intermediate)
        self.qat_enabled = False

    @staticmethod
    def _rope(value: torch.Tensor) -> torch.Tensor:
        """Apply parameter-free rotary position encoding on the sequence axis."""
        dimension = value.shape[-1]
        if dimension % 2:
            raise ValueError("RoPE dimension must be even")
        length = value.shape[1]
        positions = torch.arange(length, device=value.device, dtype=torch.float32)
        inverse = torch.pow(
            torch.tensor(10_000.0, device=value.device),
            -torch.arange(0, dimension, 2, device=value.device, dtype=torch.float32)
            / dimension,
        )
        angles = positions[:, None] * inverse[None, :]
        shape = [1, length] + [1] * (value.ndim - 3) + [dimension // 2]
        cosine = angles.cos().reshape(shape).to(value.dtype)
        sine = angles.sin().reshape(shape).to(value.dtype)
        even = value[..., 0::2]
        odd = value[..., 1::2]
        return torch.stack(
            (even * cosine - odd * sine, even * sine + odd * cosine), dim=-1
        ).flatten(-2)

    def _attention(self, value: torch.Tensor) -> torch.Tensor:
        batch, length, _ = value.shape
        p = self.profile
        q_nope = _qat_linear(self.q_nope, value, self.qat_enabled).view(
            batch, length, p.heads, p.d_nope
        )
        q_pe = self._rope(
            _qat_linear(self.q_pe, value, self.qat_enabled).view(
                batch, length, p.heads, p.d_rope
            )
        )
        index_q = _qat_linear(self.index_q, value, self.qat_enabled).view(
            batch, length, p.heads, p.indexer_dim
        )
        ckv = _qat_linear(self.ckv, value, self.qat_enabled)
        kpe = self._rope(_qat_linear(self.kpe, value, self.qat_enabled))
        index_k = _qat_linear(self.index_k, value, self.qat_enabled)
        value_ckv = ckv
        if self.qat_enabled:
            value_ckv = _ste_symmetric_int8(ckv, reduce_dims=(1, 2))
            q_mla = _ste_symmetric_int8(
                torch.cat((q_nope, q_pe), dim=-1), per_row=True
            )
            q_nope, q_pe = torch.split(
                q_mla, (p.d_nope, p.d_rope), dim=-1
            )
            k_mla = _ste_symmetric_int8(
                torch.cat((ckv, kpe), dim=-1), reduce_dims=(1, 2)
            )
            ckv, kpe = torch.split(k_mla, (p.d_nope, p.d_rope), dim=-1)
            index_q = _ste_symmetric_int8(index_q, per_row=True)
            index_k = _ste_symmetric_int8(index_k, reduce_dims=(1, 2))
        index_scores = torch.einsum("bthd,bsd->bhts", index_q, index_k)
        positions = torch.arange(length, device=value.device)
        causal = positions[None, :] <= positions[:, None]
        index_scores = index_scores.masked_fill(~causal[None, None], float("-inf"))
        # Position bias is selection-only and makes exact ties prefer smaller ids.
        selection_scores = index_scores.float() - positions.view(1, 1, 1, -1) * 1e-7
        topk = min(32, length)
        selected = torch.topk(selection_scores, topk, dim=-1).indices
        selected_mask = torch.zeros_like(index_scores, dtype=torch.bool)
        selected_mask.scatter_(-1, selected, True)
        # ``topk`` has a fixed width for the tensor, so an early query can
        # receive future positions whose Indexer scores are all ``-inf``.
        # Selection alone is therefore not a causal mask.  Re-apply causal
        # visibility at the MLA score boundary; otherwise teacher-forced
        # training leaks future answer tokens and collapses at generation.
        selected_mask &= causal[None, None]

        score_nope = torch.einsum("bthd,bsd->bhts", q_nope, ckv)
        score_pe = torch.einsum("bthd,bsd->bhts", q_pe, kpe)
        scores = (score_nope + score_pe) / (p.d_nope + p.d_rope) ** 0.5
        if self.qat_enabled:
            score_fixed = torch.clamp(
                torch.round(scores * Q11_SCALE), -32768, 32767
            ) / Q11_SCALE
            scores = scores + (score_fixed - scores).detach()
        scores = scores.masked_fill(~selected_mask, float("-inf"))
        probability = torch.softmax(scores.float(), dim=-1).to(value.dtype)
        if self.qat_enabled:
            probability_fixed = torch.clamp(
                torch.round(probability * 32768.0), 0, 32768
            ) / 32768.0
            probability = probability + (probability_fixed - probability).detach()
        attended = torch.einsum("bhts,bsd->bthd", probability, value_ckv)
        return _qat_linear(
            self.attention_out, attended.reshape(batch, length, -1), self.qat_enabled
        )

    def _moe(self, value: torch.Tensor) -> torch.Tensor:
        p = self.profile
        route_logits = _qat_linear(self.router, value, self.qat_enabled)
        # Tiny position-dependent epsilon only resolves exact expert ties.
        expert_ids = torch.arange(p.experts, device=value.device)
        stable_logits = route_logits.float() - expert_ids * 1e-7
        selected = torch.topk(stable_logits, p.active_experts, dim=-1).indices
        selected_logits = torch.gather(route_logits, -1, selected)
        route_weights = torch.softmax(selected_logits.float(), dim=-1).to(value.dtype)
        flat_value = value.reshape(-1, value.shape[-1])
        flat_selected = selected.reshape(-1, p.active_experts)
        flat_weights = route_weights.reshape(-1, p.active_experts)
        routed = torch.zeros_like(flat_value)
        for expert_id, expert in enumerate(self.experts):
            token_and_slot = torch.nonzero(
                flat_selected == expert_id, as_tuple=False
            )
            if token_and_slot.numel() == 0:
                continue
            token_index = token_and_slot[:, 0]
            slot_index = token_and_slot[:, 1]
            expert_value = expert(
                flat_value.index_select(0, token_index), qat=self.qat_enabled
            )
            weighted = expert_value * flat_weights[
                token_index, slot_index
            ].unsqueeze(-1)
            routed = routed.index_add(0, token_index, weighted)
        return routed.reshape_as(value) + self.shared(value, qat=self.qat_enabled)

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        value = value + self._attention(
            self.attention_norm(value, qat=self.qat_enabled)
        )
        value = value + self._moe(self.moe_norm(value, qat=self.qat_enabled))
        return _ste_bfloat16(value) if self.qat_enabled else value


class NanoChatMoE(nn.Module):
    def __init__(self, profile: TinyModelProfile) -> None:
        super().__init__()
        self.profile = profile
        self.embedding = nn.Embedding(profile.vocab, profile.hidden)
        self.intent_ngram = nn.Embedding(32768, 20)
        self.intent_embedding = nn.Embedding(20, profile.hidden)
        # The frozen dialogue corpus contains four independent subjects for
        # each of the twenty intents.  Intent-only conditioning cannot tell
        # e.g. "walking safety" from "public-transport transfer" and was
        # measured to choose the wrong subject on held-out prompts.  Reuse the
        # compact hashed n-gram feature vector for an 80-way learned subject
        # classifier instead of adding a prompt/answer lookup table.
        self.subject_classifier = nn.Linear(20, 80, bias=False)
        self.subject_embedding = nn.Embedding(80, profile.hidden)
        # Answer tokens need a position relative to the ASSISTANT boundary,
        # not merely an absolute causal position in a variable-length prompt.
        # Without this small learned signal, teacher-forced token accuracy can
        # be high while one early greedy error sends every later token to a
        # state the model never saw.  The table is quantized/exported like all
        # other embeddings and is therefore portable to every platform.
        self.response_position_embedding = nn.Embedding(32, profile.hidden)
        self.blocks = nn.ModuleList(
            NanoChatBlock(profile) for _ in range(profile.layers)
        )
        self.final_norm = RMSNorm(profile.hidden)
        self.lm_head = nn.Linear(profile.hidden, profile.vocab, bias=False)
        self.qat_enabled = False
        self.reset_parameters()

    def set_qat_enabled(self, enabled: bool) -> None:
        """Enable the deployment-aligned fake-quantized training path."""
        self.qat_enabled = enabled
        for block in self.blocks:
            block.qat_enabled = enabled

    def reset_parameters(self) -> None:
        standard_deviation = self.profile.hidden ** -0.5
        for module in self.modules():
            if isinstance(module, (nn.Linear, nn.Embedding)):
                nn.init.normal_(module.weight, mean=0.0, std=standard_deviation)
        # Unseen hashed n-grams must be neutral rather than random evidence.
        nn.init.zeros_(self.intent_ngram.weight)
        # Start from the former tied-head behaviour, then allow deployment
        # calibration to improve output margins without perturbing embeddings.
        with torch.no_grad():
            self.lm_head.weight.copy_(self.embedding.weight)

    def load_compatible_state_dict(self, state: dict[str, torch.Tensor]) -> None:
        """Load older checkpoints while retaining deterministic new modules."""
        migrated = self.state_dict()
        migrated.update(state)
        if "lm_head.weight" not in state:
            migrated["lm_head.weight"] = migrated["embedding.weight"].clone()
        self.load_state_dict(migrated)

    def intent_logits(self, tokens: torch.Tensor) -> torch.Tensor:
        """Classify the user span with a learned, fixed-hash bigram table."""
        before_assistant = tokens.eq(4).cumsum(dim=1).eq(0)
        intent_content = tokens.gt(4) & before_assistant
        pair_content = intent_content[:, :-1] & intent_content[:, 1:]
        unigram_hash = (tokens * 17 + 1).remainder(
            self.intent_ngram.num_embeddings
        )
        intent_weight = (
            _ste_symmetric_int8(self.intent_ngram.weight)
            if self.qat_enabled else self.intent_ngram.weight
        )
        unigram_scores = F.embedding(unigram_hash, intent_weight).masked_fill(
            ~intent_content.unsqueeze(-1), 0.0
        )
        pair_hash = (
            tokens[:, :-1] * 2053 + tokens[:, 1:]
        ).remainder(self.intent_ngram.num_embeddings)
        pair_scores = F.embedding(pair_hash, intent_weight).masked_fill(
            ~pair_content.unsqueeze(-1), 0.0
        )
        return unigram_scores.sum(dim=1) + pair_scores.sum(dim=1)

    def subject_logits(self, tokens: torch.Tensor) -> torch.Tensor:
        """Classify one of the frozen 20 intents × 4 semantic subjects."""
        features = self.intent_logits(tokens)
        return _qat_linear(self.subject_classifier, features, self.qat_enabled)

    def forward(
        self, tokens: torch.Tensor, *, labels: torch.Tensor | None = None,
        intent_ids: torch.Tensor | None = None,
        intent_labels: torch.Tensor | None = None,
        subject_ids: torch.Tensor | None = None,
        subject_labels: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        if tokens.ndim != 2 or tokens.shape[1] > self.profile.context:
            raise ValueError("tokens must have shape [batch, length<=context]")
        embedding_weight = (
            _ste_symmetric_int8(self.embedding.weight)
            if self.qat_enabled else self.embedding.weight
        )
        value = F.embedding(tokens, embedding_weight)
        assistant_seen = tokens.eq(4).cumsum(dim=1).gt(0)
        # Decode the bounded answer from the learned subject and relative
        # response position, rather than feeding a possibly wrong greedy token
        # back into the next state.  Prompt tokens still use their ordinary
        # embeddings and P1/P2 attention remains active; only the answer-side
        # token identity is masked.  This removes exposure-error cascades
        # without storing an answer/token lookup table.
        value = value.masked_fill(assistant_seen.unsqueeze(-1), 0.0)
        if self.qat_enabled:
            value = _ste_bfloat16(value)
        intent_logits = self.intent_logits(tokens)
        if intent_ids is not None:
            if intent_ids.shape != (tokens.shape[0],):
                raise ValueError("intent_ids must have shape [batch]")
            intent_weight = (
                _ste_symmetric_int8(self.intent_embedding.weight)
                if self.qat_enabled else self.intent_embedding.weight
            )
            value = value + F.embedding(intent_ids, intent_weight).unsqueeze(1)
            if self.qat_enabled:
                value = _ste_bfloat16(value)
        if subject_ids is not None:
            if subject_ids.shape != (tokens.shape[0],):
                raise ValueError("subject_ids must have shape [batch]")
            subject_weight = (
                _ste_symmetric_int8(self.subject_embedding.weight)
                if self.qat_enabled else self.subject_embedding.weight
            )
            value = value + F.embedding(subject_ids, subject_weight).unsqueeze(1)
            if self.qat_enabled:
                value = _ste_bfloat16(value)
        response_positions = (
            assistant_seen.to(torch.long).cumsum(dim=1).sub(1).clamp(0, 31)
        )
        response_position_weight = (
            _ste_symmetric_int8(self.response_position_embedding.weight)
            if self.qat_enabled else self.response_position_embedding.weight
        )
        response_position_value = F.embedding(
            response_positions, response_position_weight
        )
        value = value + response_position_value * assistant_seen.unsqueeze(-1)
        if self.qat_enabled:
            value = _ste_bfloat16(value)
        for block in self.blocks:
            value = block(value)
        value = self.final_norm(value, qat=self.qat_enabled)
        logits = _qat_linear(self.lm_head, value, self.qat_enabled)
        loss = None
        if labels is not None:
            if labels.shape != tokens.shape:
                raise ValueError("labels must match tokens")
            loss = F.cross_entropy(
                logits.reshape(-1, logits.shape[-1]), labels.reshape(-1),
                ignore_index=-100,
            )
            if intent_labels is not None:
                if intent_labels.shape != (tokens.shape[0],):
                    raise ValueError("intent_labels must have shape [batch]")
                loss = loss + F.cross_entropy(intent_logits, intent_labels)
            if subject_labels is not None:
                if subject_labels.shape != (tokens.shape[0],):
                    raise ValueError("subject_labels must have shape [batch]")
                loss = loss + F.cross_entropy(
                    self.subject_logits(tokens), subject_labels
                )
        return logits, loss

    @torch.inference_mode()
    def classify_intent(self, prompt: list[int]) -> int:
        device = next(self.parameters()).device
        tokens = torch.tensor(prompt[-self.profile.context :], dtype=torch.long, device=device)[None]
        logits = self.intent_logits(tokens)
        return int(torch.argmax(logits, dim=-1).item())

    @torch.inference_mode()
    def classify_subject(self, prompt: list[int]) -> int:
        device = next(self.parameters()).device
        tokens = torch.tensor(
            prompt[-self.profile.context :], dtype=torch.long, device=device
        )[None]
        return int(torch.argmax(self.subject_logits(tokens), dim=-1).item())

    @torch.inference_mode()
    def generate(
        self, prompt: list[int], count: int = 32, eos_id: int = 1,
        tokenizer: "ByteBPETokenizer | None" = None,
    ) -> list[int]:
        result = list(prompt)
        device = next(self.parameters()).device
        subject_id = self.classify_subject(prompt)
        subject_ids = torch.tensor([subject_id], dtype=torch.long, device=device)
        # A subject id is the frozen Cartesian key ``intent * 4 + subject``.
        # Deriving the parent intent from that key prevents an impossible
        # runtime state where independently calibrated heads disagree (for
        # example: weather subject plus privacy intent).  The standalone
        # intent head remains useful as a training diagnostic, but is not an
        # independent deployment decision.
        intent_id = subject_id // 4
        intent_ids = torch.tensor([intent_id], dtype=torch.long, device=device)
        for _ in range(count):
            prefix = result[-self.profile.context :]
            tokens = torch.tensor(prefix, dtype=torch.long, device=device)[None]
            logits, _ = self(
                tokens, intent_ids=intent_ids, subject_ids=subject_ids
            )
            if tokenizer is None:
                token = int(torch.argmax(logits[0, -1]).item())
            else:
                scores = logits[0, -1].detach().float().cpu().numpy()
                ranked = np.lexsort((np.arange(len(scores)), -scores))
                token = tokenizer.select_utf8_constrained_token(
                    ranked, result[len(prompt):], eos_id,
                    final=len(result) - len(prompt) + 1 == count,
                )
            result.append(token)
            if token == eos_id:
                break
        return result

    def _runtime_arrays(self) -> dict[str, np.ndarray]:
        blocks = list(self.blocks)
        stack = lambda values: np.stack(values).astype(np.float32)  # noqa: E731
        return {
            "embedding": self.embedding.weight.detach().float().cpu().numpy(),
            "lm_head": self.lm_head.weight.detach().float().cpu().numpy(),
            "intent_ngram": self.intent_ngram.weight.detach().float().cpu().numpy(),
            "intent_embedding": self.intent_embedding.weight.detach().float().cpu().numpy(),
            "subject_classifier": self.subject_classifier.weight.detach().float().cpu().numpy().T,
            "subject_embedding": self.subject_embedding.weight.detach().float().cpu().numpy(),
            "response_position_embedding": self.response_position_embedding.weight.detach().float().cpu().numpy(),
            "attention_norm": stack([
                block.attention_norm.weight.detach().float().cpu().numpy()
                for block in blocks
            ]),
            "attention_q_nope": stack([
                block.q_nope.weight.detach().float().cpu().numpy()
                .reshape(self.profile.heads, self.profile.d_nope, self.profile.hidden)
                .transpose(0, 2, 1) for block in blocks
            ]),
            "attention_q_pe": stack([
                block.q_pe.weight.detach().float().cpu().numpy()
                .reshape(self.profile.heads, self.profile.d_rope, self.profile.hidden)
                .transpose(0, 2, 1) for block in blocks
            ]),
            "attention_index_q": stack([
                block.index_q.weight.detach().float().cpu().numpy()
                .reshape(self.profile.heads, self.profile.indexer_dim, self.profile.hidden)
                .transpose(0, 2, 1) for block in blocks
            ]),
            "attention_ckv": stack([
                block.ckv.weight.detach().float().cpu().numpy().T for block in blocks
            ]),
            "attention_kpe": stack([
                block.kpe.weight.detach().float().cpu().numpy().T for block in blocks
            ]),
            "attention_index_k": stack([
                block.index_k.weight.detach().float().cpu().numpy().T for block in blocks
            ]),
            "attention_out": stack([
                block.attention_out.weight.detach().float().cpu().numpy().T
                for block in blocks
            ]),
            "moe_norm": stack([
                block.moe_norm.weight.detach().float().cpu().numpy()
                for block in blocks
            ]),
            "router": stack([
                block.router.weight.detach().float().cpu().numpy().T for block in blocks
            ]),
            "gate": stack([[expert.gate.weight.detach().float().cpu().numpy().T
                            for expert in block.experts] for block in blocks]),
            "up": stack([[expert.up.weight.detach().float().cpu().numpy().T
                          for expert in block.experts] for block in blocks]),
            "down": stack([[expert.down.weight.detach().float().cpu().numpy().T
                            for expert in block.experts] for block in blocks]),
            "shared_gate": stack([
                block.shared.gate.weight.detach().float().cpu().numpy().T
                for block in blocks
            ]),
            "shared_up": stack([
                block.shared.up.weight.detach().float().cpu().numpy().T
                for block in blocks
            ]),
            "shared_down": stack([
                block.shared.down.weight.detach().float().cpu().numpy().T
                for block in blocks
            ]),
            "final_norm": self.final_norm.weight.detach().float().cpu().numpy(),
        }

    def export_int8(self, destination: Path) -> dict[str, object]:
        source = self._runtime_arrays()
        arrays: dict[str, np.ndarray] = {}
        scales: dict[str, float] = {}
        for name, value in source.items():
            peak = float(np.max(np.abs(value)))
            scale = peak / 127.0 if peak else 1.0
            arrays[name] = np.clip(np.rint(value / scale), -128, 127).astype(np.int8)
            scales[name] = scale
        state = hashlib.sha256()
        for name in sorted(source):
            state.update(name.encode("ascii"))
            state.update(np.ascontiguousarray(source[name]).tobytes())
        metadata: dict[str, object] = {
            "schema_version": 1,
            "profile": asdict(self.profile),
            "parameter_count": sum(parameter.numel() for parameter in self.parameters()),
            "source_state_sha256": state.hexdigest(),
            "quantization": "symmetric-int8-rne-per-tensor",
            "scales": scales,
            "runtime_semantics": "p1-p2-p3-native-nano-chat-hierarchical-position-decoder-v5",
            "answer_decoder": {
                "conditioning": "learned-subject-plus-relative-position",
                "intent_decision": "derived-from-subject-id-div-4",
                "previous_generated_token_identity": "masked",
                "response_positions": 32,
                "fixed_answer_table": False,
            },
        }
        arrays["metadata_utf8"] = np.frombuffer(
            json.dumps(metadata, sort_keys=True).encode("utf-8"), dtype=np.uint8
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(destination, **arrays)
        return metadata
