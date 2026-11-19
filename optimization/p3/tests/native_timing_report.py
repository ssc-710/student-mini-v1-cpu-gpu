"""Report measured diagnostic timing with explicit simulation/wall boundaries."""
import json
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
cpu=json.loads((BASE/'runs/native-cpu-comparison.json').read_text())
gpu=json.loads((BASE/'runs/native-gpu-comparison.json').read_text())
rows=[]
for variant,name in [('baseline','baseline'),('candidate','algorithm')]:
    cycles=cpu[variant]['generation_cycles'];seconds=cycles/1_000_000
    receipt=json.loads((BASE/f'runs/cpu-{name}-diagnostic.receipt.json').read_text())
    rows.append(dict(platform='CPU VexRiscv RTL',variant=variant,generation_cycles=cycles,
        p3_cycles=cpu[variant]['p3_cycles'],actual_simulation_clock_hz=1_000_000,
        simulated_generation_seconds=seconds,simulated_generation_tokens_per_second_including_eos=11/seconds,
        simulated_generation_tokens_per_second_excluding_eos=10/seconds,
        process_to_completion_wall_seconds=receipt['elapsed_seconds'],
        wall_boundary='Simulator startup through UART COMPLETE; boot and full hidden/logits diagnostics included.'))
for variant,receiptpath in [('baseline','gpu-baseline-driver-retry/receipt.json'),('candidate','gpu-algorithm-abs-fix/receipt.json')]:
    receipt=json.loads((BASE/'runs'/receiptpath).read_text());record=gpu[variant]
    seconds=record['kernel_sync_seconds']
    rows.append(dict(platform='GPU Vortex SimX',variant=variant,
        kernel_and_sync_wall_seconds=seconds,qa_compute_readback_wall_seconds=record['qa_compute_readback_seconds'],
        kernel_sync_wall_tokens_per_second_including_eos=11/seconds,
        kernel_sync_wall_tokens_per_second_excluding_eos=10/seconds,
        process_to_completion_wall_seconds=receipt.get('process_wall_seconds',receipt.get('wall_seconds')),
        aggregate_cycles=record['aggregate_cycles'],
        wall_boundary='Host steady_clock kernel launch to synchronize, may include JIT; not physical GPU token/s.'))
result=dict(status='SINGLE_DIAGNOSTIC_MEASUREMENT_NOT_FINAL_PERFORMANCE',answer='我无法获知实时天气。',
    token_ids=cpu['token_ids'],rows=rows,
    caveat='No controlled repeated five-run performance, layout ablation, new RTL qualification or physical clock signoff yet.')
(BASE/'runs/native-timing.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
