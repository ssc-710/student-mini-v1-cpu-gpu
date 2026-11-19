"""Mini CPU-reference inference; NumPy only, never target-platform evidence.

No intent classifier, answer table, or response-position decoder is present.
The generated token is fed back through P2 and P3 with real compressed KV.
"""
from dataclasses import asdict
import json
from pathlib import Path
import numpy as np
from .litex_contract import TinyModelProfile
from .nano_chat_runtime import QuantizedNanoChatRuntime
from .numeric import as_bfloat16

PROFILE = TinyModelProfile(name='student-mini-v1', layers=1, hidden=16, heads=1,
    kv_latent=12, experts=2, active_experts=1, intermediate=16, vocab=256,
    context=32, max_generated_tokens=12, d_nope=8, d_rope=4, indexer_dim=8, value_dim=8)
SHAPES = {
    'embedding': (256, 16), 'lm_head': (256, 16), 'final_norm': (16,),
    'attention_norm': (1, 16), 'moe_norm': (1, 16),
    'attention_q_nope': (1, 1, 16, 8), 'attention_q_pe': (1, 1, 16, 4),
    'attention_index_q': (1, 1, 16, 8), 'attention_ckv': (1, 16, 8),
    'attention_kpe': (1, 16, 4), 'attention_index_k': (1, 16, 8),
    'attention_out': (1, 8, 16), 'router': (1, 16, 2),
    **{name: (1, 2, 16, 16) for name in ('gate', 'up', 'down')},
    **{'shared_'+name: (1, 16, 16) for name in ('gate', 'up', 'down')},
}


class MiniNanoRuntime(QuantizedNanoChatRuntime):
    PREFILL_TOPK = 4

    def _quantize_mla_cache(self, ckv, kpe):
        key, scale = self._activation(np.concatenate((ckv, kpe), axis=-1))
        # P1's packed ABI reads both K.nope and V from the same eight bytes.
        return key, scale, key[:, :8].copy(), scale

    @staticmethod
    def _activation(value):
        source = np.asarray(value, dtype=np.float32)
        if not source.size or not np.isfinite(source).all():
            raise ValueError('activation must be nonempty and finite')
        peak = np.max(np.abs(source))
        scale = np.float32(np.clip(np.float32(peak/np.float32(127)), 2**-16, 2**16)) if peak else np.float32(1)
        return np.clip(np.rint(np.float32(source/scale)), -128, 127).astype(np.int8), float(scale)

    def __init__(self, arrays, scales):
        if set(arrays) != set(SHAPES) or set(scales) != set(SHAPES):
            raise ValueError('mini checkpoint has missing or unexpected tensors')
        for name, shape in SHAPES.items():
            value = np.asarray(arrays[name])
            if value.dtype != np.int8 or value.shape != shape:
                raise ValueError('invalid INT8 tensor: '+name)
            scale = scales[name]
            if not np.isfinite(scale) or not 2**-16 <= scale <= 2**16:
                raise ValueError('invalid FP32 scale: '+name)
        super().__init__(PROFILE, arrays, scales)

    @classmethod
    def from_npz(cls, path: Path):
        with np.load(path, allow_pickle=False) as archive:
            metadata = json.loads(bytes(archive['metadata_utf8']).decode('utf-8'))
            if (metadata.get('runtime_semantics') != 'student-mini-native-int8-bf16-v1'
                    or metadata.get('profile') != asdict(PROFILE)
                    or metadata.get('prefill_topk') != 4):
                raise ValueError('incompatible mini checkpoint semantics')
            arrays = {name: archive[name].copy() for name in archive.files if name != 'metadata_utf8'}
        return cls(arrays, metadata['scales'])

    def _embedding(self, token_ids, *, establish_intent=False, response_position=None):
        tokens = np.asarray(token_ids)
        if tokens.ndim != 1 or not np.issubdtype(tokens.dtype, np.integer) or np.any(tokens < 0) or np.any(tokens >= 256):
            raise ValueError('token id outside mini vocabulary')
        return as_bfloat16(self.arrays['embedding'][tokens].astype(np.float32)
                          * np.float32(self.scales['embedding']))

    def decode(self, token):
        if self._cache and len(self._cache[0]['ckv']) >= self.profile.context:
            raise ValueError('mini context exhausted')
        return super().decode(token)

    def generate(self, prompt, count=12, eos_id=4, tokenizer=None):
        if type(count) is not int or not 0 <= count <= 12:
            raise ValueError('mini generation limit is 12 tokens')
        if count == 0:
            return []
        return super().generate(prompt, count, eos_id, tokenizer)
