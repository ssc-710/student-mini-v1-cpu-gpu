"""Teacher-only native MLA/MoE mini model matching the deployment tensor layout."""
from dataclasses import asdict
import hashlib
import json
import numpy as np
import torch
from torch import nn
from .nano_chat_model import NanoChatBlock, RMSNorm, _qat_linear, _ste_bfloat16, _ste_symmetric_int8
from .student_mini_nano_runtime import PROFILE, SHAPES


class MiniNativeNano(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(256, 16)
        self.block = NanoChatBlock(PROFILE)
        self.final_norm = RMSNorm(16)
        self.head = nn.Linear(16, 256, bias=False)
        self.qat_enabled = False

    def forward(self, tokens):
        if tokens.ndim != 2 or not 1 <= tokens.shape[1] <= 32:
            raise ValueError('mini sequence outside context')
        b = self.block
        b.qat_enabled = self.qat_enabled
        weight = _ste_symmetric_int8(self.embedding.weight) if self.qat_enabled else self.embedding.weight
        x = torch.nn.functional.embedding(tokens, weight)
        if self.qat_enabled:
            x = _ste_bfloat16(x)
        h = b.attention_norm(x, qat=self.qat_enabled)
        linear = lambda module: _qat_linear(module, h, self.qat_enabled)
        q = torch.cat((linear(b.q_nope), b._rope(linear(b.q_pe))), -1)
        ckv = linear(b.ckv)
        k = torch.cat((ckv, b._rope(linear(b.kpe))), -1)
        iq, ik = linear(b.index_q), linear(b.index_k)
        if self.qat_enabled:
            # Causal training surrogate: a future answer must not change an
            # earlier row through sequence-wide quantization scales. Exact
            # deployment uses the real prompt/current cache scale separately.
            q = _ste_symmetric_int8(q, per_row=True)
            k = _ste_symmetric_int8(k, per_row=True)
            ckv = k[..., :8]
            iq = _ste_symmetric_int8(iq, per_row=True)
            ik = _ste_symmetric_int8(ik, per_row=True)
        scores = q @ k.transpose(-2, -1) / 12**.5
        index = iq @ ik.transpose(-2, -1)
        length = tokens.shape[1]
        causal = torch.ones(length, length, dtype=torch.bool, device=tokens.device).tril()
        # Stable sorting resolves exact ties by lower token index, without an
        # epsilon that could reorder unequal close scores.
        ids = index.masked_fill(~causal, float('-inf')).argsort(dim=-1, descending=True, stable=True)[..., :min(4, length)]
        selected = torch.zeros_like(scores, dtype=torch.bool).scatter_(-1, ids, True) & causal
        # ASSISTANT itself is the final prefill row; subsequent token identities
        # are genuinely autoregressive and use all visible KV via P2.
        assistant = tokens == 3
        decode = assistant.cumsum(dim=1) - assistant.long() > 0
        mask = torch.where(decode[..., None], causal[None], selected)
        if self.qat_enabled:
            fixed = torch.clamp(torch.round(scores * 2048), -32768, 32767) / 2048
            scores = scores + (fixed - scores).detach()
        probability = scores.masked_fill(~mask, float('-inf')).softmax(-1)
        attended = probability @ ckv
        x = x + _qat_linear(b.attention_out, attended, self.qat_enabled)
        if self.qat_enabled:
            x = _ste_bfloat16(x)
        x = x + b._moe(b.moe_norm(x, qat=self.qat_enabled))
        if self.qat_enabled:
            x = _ste_bfloat16(x)
        return _qat_linear(self.head, self.final_norm(x, qat=self.qat_enabled), self.qat_enabled)

    def runtime_arrays(self):
        b = self.block
        array = lambda tensor: tensor.detach().cpu().float().numpy()
        result = dict(embedding=array(self.embedding.weight), lm_head=array(self.head.weight),
                      final_norm=array(self.final_norm.weight),
                      attention_norm=array(b.attention_norm.weight)[None], moe_norm=array(b.moe_norm.weight)[None])
        for key, name in (('attention_q_nope', 'q_nope'), ('attention_q_pe', 'q_pe'), ('attention_index_q', 'index_q')):
            result[key] = array(getattr(b, name).weight).T[None, None]
        for key, name in (('attention_ckv', 'ckv'), ('attention_kpe', 'kpe'), ('attention_index_k', 'index_k'),
                          ('attention_out', 'attention_out'), ('router', 'router')):
            result[key] = array(getattr(b, name).weight).T[None]
        for name in ('gate', 'up', 'down'):
            result[name] = np.stack([array(getattr(e, name).weight).T for e in b.experts])[None]
            result['shared_'+name] = array(getattr(b.shared, name).weight).T[None]
        if {name: value.shape for name, value in result.items()} != SHAPES:
            raise ValueError('export shape mismatch')
        return result

    def export_int8(self, path, *, parent_checkpoint_sha256):
        source = self.runtime_arrays()
        arrays, scales = {}, {}
        for name, value in source.items():
            scale = np.float32(max(float(np.abs(value).max()) / 127, 2**-16))
            if not np.isfinite(scale) or scale > 2**16:
                raise ValueError('weight scale outside contract')
            arrays[name] = np.clip(np.rint(np.float32(value/scale)), -128, 127).astype(np.int8)
            scales[name] = float(scale)
        metadata = dict(profile=asdict(PROFILE), prefill_topk=4,
            runtime_semantics='student-mini-native-int8-bf16-v1', scales=scales,
            parent_checkpoint_sha256=parent_checkpoint_sha256,
            source_state_sha256=hashlib.sha256(b''.join(name.encode()+np.ascontiguousarray(source[name]).tobytes() for name in sorted(source))).hexdigest(),
            quantization='FP32 per-tensor max-abs / 127, floor 2^-16; FP32 division then RNE INT8; no calibration-set fitting',
            boundary='Training QAT is a surrogate; only exact runtime evaluation establishes deployed numerical quality. This is not target execution.')
        if path.exists():
            raise FileExistsError(path)
        np.savez_compressed(path, **arrays, metadata_utf8=np.frombuffer(json.dumps(metadata).encode(), dtype=np.uint8))
        return metadata
