"""Summarize executed evidence without promoting partial physical qualification."""
import hashlib
import json
from pathlib import Path
import re
BASE=Path(__file__).resolve().parents[1]
inputs=[]
def read(path):
    path=BASE/path;inputs.append(path);return path.read_text()
ablation=json.loads(read('runs/cpu-ablation-retry/comparison.json'))
rtl=json.loads(read('runs/gpu-rtl-native-matched-config/comparison.json'))
receipt=json.loads(read('runs/gpu-rtl-native-matched-config/receipt.json'))
log=read('runs/gpu-rtl-native-matched-config/execute.log')
timing=re.search(r'P3_HOST_TIMING kernel_sync_seconds=([\d.]+) qa_compute_readback_seconds=([\d.]+)',log)
assert timing
physical=[]
for variant in ['baseline','candidate']:
    for utilization in [40,30]:
        path=f'physical/gpu-multiplier-placement-filtered/{variant}-u{utilization}/wns-placement.rpt'
        match=re.fullmatch(r'worst slack ([\d.\-]+)\s*',read(path));assert match
        physical.append(dict(design='split-reference' if variant=='baseline' else 'limb-candidate',
            initial_utilization_percent=utilization,wns_ns=float(match[1]),clock_target_ns=10,
            stage='Placement parasitic estimate, ideal clock; not routed or whole core'))
for utilization in [40,30]:
    path=f'physical/gpu-multiplier-placement-vendor/vendor-u{utilization}/wns-placement.rpt'
    match=re.fullmatch(r'worst slack ([\d.\-]+)\s*',read(path));assert match
    physical.append(dict(design='actual-vendor-fixed-parameter-elaboration',initial_utilization_percent=utilization,
        wns_ns=float(match[1]),clock_target_ns=10,stage='Placement parasitic estimate, ideal clock; not routed or whole core'))
cpu_merge=json.loads(read('physical/cpu-merge-shaped/comparison.json'))
result=dict(status='HOLD_PARTIAL_QUALIFICATION',
    cpu_same_elf=dict(generation_speedup=ablation['generation_speedup'],p3_speedup=ablation['p3_speedup'],
        summary=ablation['summary'],limitation=ablation['limitation']),
    gpu_matched_rtlsim=dict(comparison=rtl,kernel_sync_wall_seconds=float(timing[1]),
        kernel_sync_wall_tokens_per_second_including_eos=11/float(timing[1]),
        qa_compute_readback_wall_seconds=float(timing[2]),process_wall_seconds=receipt['wall_seconds'],
        limitation='Diagnostic simulation wall times, not physical GPU throughput or RTL speedup vs vendor.'),
    physical=physical,
    limb_routed_local=dict(receipt=json.loads(read('physical/gpu-multiplier-route-hilomap/receipt.json')),
        wns_report=read('physical/gpu-multiplier-extract-limb-u30/wns-extracted.rpt'),
        hold_report=read('physical/gpu-multiplier-extract-limb-u30/hold-extracted.rpt'),
        extraction=json.loads(read('physical/gpu-multiplier-extract-limb-u30/receipt.json')),
        limitation='Local TT only; full-chip/signoff PPA remains unqualified.'),
    gpu_vendor_limb_routed_local=json.loads(read('physical/gpu-multiplier-routed-outputbound-comparison.json')),
    gpu_vendor_limb_actual_rtl=json.loads(read('runs/gpu-rtl-parent-comparison.json')),
    gpu_twelve_prompt_regression=json.loads(read('runs/gpu-twelve-prompt-comparison.json')),
    cpu_prompt_regression_audit=json.loads(read('runs/cpu-prompt-regression-audit.json')),
    cpu_current_banked_rom_core_replay=json.loads(read('runs/cpu-current-rom-core-replay/independent-audit.json')),
    gpu_processor_fault_seed1=json.loads(read('runs/gpu-fault-rtl-smoke-headerfixed/receipt.json')),
    gpu_processor_fault_ten_seeds=json.loads(read('runs/gpu-fault-rtl-ten-seeds/receipt.json')),
    cpu_merge_local=cpu_merge,
    cpu_p3_uart_protocol=json.loads(read('runs/cpu-scalar-protocol/comparison.json')),
    gpu_device_bound_comparison=json.loads(read('runs/gpu-rtl-native-device-bound/comparison.json')),
    required_remaining=['Actual whole-core IO boundary/corner qualification and full-core PPA', 'CPU full-core PPA',
        'CTS/route/extracted STA, DRC/antenna/PDN/LVS/activity power and full-chip binding',
        'GPU genuine bus fault/protocol and CPU CSA/physical-interface protocol qualification',
        'CPU remaining prompt RTL regression (see audited completed/missing indices), final repeated performance and complete device provenance'],
    bindings={str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
out=BASE/'reports/current-evidence.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('CURRENT_EVIDENCE_HOLD',out)
