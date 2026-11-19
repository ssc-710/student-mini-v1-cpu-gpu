import math
from pathlib import Path

out = Path(__file__).resolve().parent.parent / 'sources/shared/rtl'
out.mkdir(parents=True, exist_ok=True)
q15 = 1 << 15
exp = [max(0, min(q15, int(round(math.exp(i / 64) * q15)))) for i in range(-16 * 64, 1)]
silu = []
for i in range(-16 * 64, 16 * 64 + 1):
    x = i / 64
    v = x / (1 + math.exp(-x))
    q = max(-16 * 2048, min(16 * 2048 - 1, int(round(v * 2048))))
    silu.append(q & 0xffff)
(out / 'exp_q15_q6.mem').write_text('\n'.join(f'{x:04x}' for x in exp) + '\n')
(out / 'silu_q11_q6.mem').write_text('\n'.join(f'{x:04x}' for x in silu) + '\n')
print(len(exp), len(silu))
