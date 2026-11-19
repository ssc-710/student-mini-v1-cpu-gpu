"""Rebuild all physical-boundary repairs and replay a proved 31-cycle GPU.

All derived producers live in a fresh hash-bound directory. Numerical proofs,
SRAM mapping, payload/port proofs and actual whole-core replay remain separate
gates. This does not accept a baseline or authorize reuse of old counters.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('31-cycle continuation seam changed: ' + old)
    return source.replace(old, new)


def derive(source, root, kind):
    source = replace_once(source, '\nROOT=Path(__file__).resolve().parents[1]',
                          '\nROOT=Path(' + repr(str(root)) + ')')
    # Each new producer binds its original plus this transformation. Internal
    # generated replay also binds its parent producer via the existing gate.
    original = {'repair': 'prepare_student_mini_gpu_repaired_boundary.py',
                'port': 'prepare_student_mini_gpu_port_boundary.py',
                'replay': 'run_student_mini_gpu_repaired_replay.py'}[kind]
    marker = '\n    paths=[Path(__file__),'
    source = replace_once(source, marker,
        marker + "ROOT/'scripts/continue_student_mini_gpu_nrm_replay.py',ROOT/'scripts/" + original + "',")
    if kind == 'repair':
        source = replace_once(source, "cut.get('status')!='SRT_STEP_CUT_DIFFERENTIAL_STAGE_PASS'",
                              "cut.get('status')!='FPU_NRM_CUT_DIFFERENTIAL_STAGE_PASS' or cut.get('latency_after')!=31")
    if kind == 'port':
        source = replace_once(source, "prior.get('arithmetic_latency')!=30", "prior.get('arithmetic_latency')!=31")
    if kind == 'replay':
        source = replace_once(source, "parent['arithmetic_latency']!=30", "parent['arithmetic_latency']!=31")
        # Preserve the inner derive() seam; it still relocates the real replay.
        source = source.replace('REPAIRED_30_CYCLE_GPU_REPRESENTATIVE_STAGE_PASS',
                                'REPAIRED_31_CYCLE_GPU_REPRESENTATIVE_STAGE_PASS')
    source = replace_once(source, 'arithmetic_latency=30', 'arithmetic_latency=31')
    return source.replace('30-cycle', '31-cycle')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('export-continuation', 'unit-work', 'idle-proof', 'payload-proof',
                 'port-proof', 'functional-parent', 'functional-report'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    originals = {kind: ROOT/'scripts'/name for kind, name in {
        'repair': 'prepare_student_mini_gpu_repaired_boundary.py',
        'port': 'prepare_student_mini_gpu_port_boundary.py',
        'replay': 'run_student_mini_gpu_repaired_replay.py'}.items()}
    mapper = ROOT/'scripts/prepare_student_mini_gpu_physical.py'
    paths = [Path(__file__), mapper, *originals.values(),
             args.export_continuation.resolve()/'inputs.json',
             args.unit_work.resolve()/'inputs.json', args.idle_proof.resolve(),
             args.payload_proof.resolve(), args.port_proof.resolve(), args.functional_report.resolve()]
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(dict(bindings=bindings,
        arguments={k: str(v.resolve()) for k, v in vars(args).items()}), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-nrm-replay-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    producers = {}
    for kind, original in originals.items():
        path = work/(kind + '-producer.py')
        path.write_text(derive(original.read_text(), ROOT, kind))
        producers[kind] = path
        bindings[str(path)] = sha(path)
    result = dict(status='HOLD', bindings=bindings, arithmetic_latency=31,
                  formal_baseline=False, physical_evidence_complete=False, old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n')
    begin = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    def execute(script, phase, arguments):
        verify(bindings); heartbeat(phase.upper())
        log = work/(phase + '.log')
        with log.open('x') as output:
            code = subprocess.call([sys.executable, str(script), *arguments],
                                   cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        rows = [json.loads(line) for line in log.read_text().splitlines() if line.startswith('{')]
        if rows:
            result[phase] = rows[-1]
        if code or not rows:
            raise ValueError(phase + ' failed; original child HOLD preserved')
        folder = Path(rows[-1]['work']); packet = folder/'completion.json'
        value = json.loads(packet.read_text())
        verify(value['bindings']); bindings.update(value['bindings'])
        bindings[str(packet)] = sha(packet); verify(bindings)
        return folder, value
    try:
        heartbeat('WAITING_FOR_31_CYCLE_EXPORT')
        print(json.dumps(dict(work=str(work), stage='WAITING_FOR_31_CYCLE_EXPORT')), flush=True)
        packet = args.export_continuation.resolve()/'completion.json'
        while not packet.is_file():
            if time.monotonic()-begin > 43200:
                raise TimeoutError('bounded export wait expired')
            time.sleep(10)
        parent = json.loads(packet.read_text())
        if parent['status'] != 'GPU_NRM_SOURCE_EXPORT_STAGE_PASS':
            raise ValueError('31-cycle numerical proof/export did not pass')
        verify(parent['bindings']); bindings.update(parent['bindings']); bindings[str(packet)] = sha(packet)
        exported = Path(parent['export']['work'])
        mapped, value = execute(mapper, 'mapping', ['--boundary', str(exported)])
        if value.get('boundary_complete') is not True:
            raise ValueError('real SRAM mapping incomplete')
        repaired, value = execute(producers['repair'], 'repair', ['--boundary', str(mapped),
            '--idle-proof', str(args.idle_proof.resolve()), '--payload-proof', str(args.payload_proof.resolve()),
            '--cut-proof', str(args.unit_work.resolve()/'completion.json')])
        if value['status'] != 'REPAIRED_GPU_BOUNDARY_STAGE_PASS' or value['arithmetic_latency'] != 31:
            raise ValueError('SRAM/DCR corrections not bound')
        boundary, value = execute(producers['port'], 'port', ['--repaired-boundary', str(repaired),
            '--port-proof', str(args.port_proof.resolve())])
        if value['status'] != 'GPU_PORT_REPAIRED_BOUNDARY_STAGE_PASS' or value['arithmetic_latency'] != 31:
            raise ValueError('core port correction not bound')
        replay, value = execute(producers['replay'], 'replay', ['--boundary', str(boundary),
            '--functional-parent', str(args.functional_parent.resolve()),
            '--functional-report', str(args.functional_report.resolve())])
        if value['status'] != 'REPAIRED_31_CYCLE_GPU_REPRESENTATIVE_STAGE_PASS':
            raise ValueError('31-cycle three-kernel replay failed')
        result.update(status='GPU_NRM_REPRESENTATIVE_REPLAY_STAGE_PASS', boundary=str(boundary),
            replay_continuation=str(replay), reason='Three real kernels matched full outputs; all-case, timing, route and power remain')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-begin
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'GPU_NRM_REPRESENTATIVE_REPLAY_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
