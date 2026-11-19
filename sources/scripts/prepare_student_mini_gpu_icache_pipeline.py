"""Private 2->3-stage instruction cache; hierarchy then real whole-core replay.

This is a feasibility candidate, not a promotion or baseline certificate.
Historical boundaries are preserved. New counters/physical evidence required.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify, execute_locked_route
from scripts.generate_vortex_macro_placements import reachable_instances
from scripts.student_mini_gpu_icache_pipeline import pipeline_icache, replay_producer


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('boundary', 'placement', 'functional-parent', 'functional-report'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(); parent = args.boundary.resolve(); place = args.placement.resolve()
    prior = json.loads((parent/'completion.json').read_text())
    timing = json.loads((place/'completion.json').read_text())
    if (prior['status'] != 'GPU_PORT_REPAIRED_BOUNDARY_STAGE_PASS' or prior['arithmetic_latency'] != 57
        or prior['boundary_complete'] is not True or sum(prior['macro_counts'].values()) != 37):
        raise ValueError('current replayed 57-cycle mapped GPU required')
    project = parent/'project-banked.v'
    report = Path(timing['reports_directory'])/'3_resizer.rpt'
    if (timing['status'] != 'HOLD' or timing['clock_period_ns'] != 10
        or timing['bindings'].get(str(project)) != sha(project)
        or timing['artifacts'].get(str(report)) != sha(report)):
        raise ValueError('actual matching GPU timing HOLD required')
    text = report.read_text()
    if '.bank.cache_tags.tag_store.' not in text or '.bank.cache_data.g_data_slice[7].' not in text:
        raise ValueError('observed icache tag/data path differs')
    bindings = dict(prior['bindings']); verify(bindings)
    for name, digest in prior['artifacts'].items():
        path = parent/name
        if sha(path) != digest: raise ValueError('mapped parent artifact changed')
        bindings[str(path)] = digest
    original = ROOT/'scripts/run_student_mini_gpu_physical_replay.py'
    tool = Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    files = [Path(__file__), ROOT/'scripts/student_mini_gpu_icache_pipeline.py',
        ROOT/'scripts/run_student_mini_gpu_repaired_replay.py', original, tool,
        parent/'completion.json', place/'completion.json', report,
        args.functional_parent.resolve()/'manifest.json', args.functional_report.resolve(),
        ROOT/'scripts/generate_vortex_macro_placements.py', ROOT/'scripts/retry_student_mini_route.py']
    bindings.update({str(p):sha(p) for p in files}); verify(bindings)
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-icache-pipeline'/key; work.mkdir(parents=True, exist_ok=False)
    boundary = work/'boundary'; boundary.mkdir()
    (boundary/'project-banked.v').write_text(pipeline_icache(project.read_text()))
    for name in ('vortex_physical_top.sv','vortex_command_adapter.sv','macros-blackboxes.v','macro-placement.tcl'):
        shutil.copyfile(parent/name, boundary/name)
    (boundary/'config.mk').write_text((parent/'config.mk').read_text().replace(str(parent), str(boundary)))
    producer = work/'replay-producer.py'; producer.write_text(replay_producer(original.read_text(), ROOT))
    bindings[str(producer)] = sha(producer)
    bindings.update({str(p):sha(p) for p in boundary.iterdir()})
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False,
        whole_gpu_equivalence=False, old_counters_reusable=False, arithmetic_latency=57,
        icache_latency_before=2, icache_latency_after=3, boundary=str(boundary))
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n')
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage, updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work), stage='ICACHE_PIPELINE_QUEUED')), flush=True)
    try:
        sources = [boundary/name for name in ('project-banked.v','macros-blackboxes.v','vortex_command_adapter.sv','vortex_physical_top.sv')]
        sources += [ROOT/'shared/rtl'/name for name in ('vortex_banked_large_sram_wrappers.sv','vortex_memory_adapter.sv')]
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); fcntl.flock(lock, fcntl.LOCK_EX); verify(bindings)
            script = boundary/'mapped.ys'
            script.write_text('read_verilog -sv '+' '.join(map(str,sources))+f'; hierarchy -check -top vortex_physical_top; proc; opt_clean; check -assert; write_json {boundary}/mapped.json\n')
            if execute_locked_route([str(tool), '-Q', '-T', '-s', str(script)], boundary/'mapped.log', 900, heartbeat):
                raise ValueError('icache hierarchy check failed')
            design = json.loads((boundary/'mapped.json').read_text())
            instances = reachable_instances(design, set(prior['macro_counts']), top='vortex_physical_top', prefix='')
            if Counter(name for _,name in instances) != Counter(prior['macro_counts']):
                raise ValueError('frozen macro geometry changed')
        receipt = dict(result, status='GPU_ICACHE_PIPELINE_BOUNDARY_STAGE_PASS', boundary_complete=True,
            macro_counts=prior['macro_counts'], placements=prior['placements'], logical_shapes=prior['logical_shapes'],
            private_command_adapter=str(boundary/'vortex_command_adapter.sv'),
            private_physical_top=str(boundary/'vortex_physical_top.sv'),
            artifacts={p.name:sha(p) for p in boundary.iterdir() if p.is_file()})
        (boundary/'completion.json').write_text(json.dumps(receipt, indent=2)+'\n')
        bindings[str(boundary/'completion.json')] = sha(boundary/'completion.json')
        verify(bindings); heartbeat('WHOLE_GPU_REPLAY')
        command = [sys.executable, str(producer), '--boundary', str(boundary)]
        for name in ('functional_parent','functional_report'):
            command += ['--'+name.replace('_','-'), str(getattr(args,name).resolve())]
        with (work/'replay.log').open('x') as output:
            code = subprocess.call(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        rows = [json.loads(line) for line in (work/'replay.log').read_text().splitlines() if line.startswith('{')]
        if rows: result['replay'] = rows[-1]
        verify(bindings)
        if code or result.get('replay',{}).get('status') != 'PHYSICAL_BOUNDARY_REPRESENTATIVE_REPLAY_STAGE_PASS':
            raise ValueError('changed cache whole-core representative replay failed')
        packet = Path(result['replay']['work'])/'completion.json'; child = json.loads(packet.read_text())
        verify(child['bindings'])
        if (len(child['records']) != 3 or sorted(r['operator'] for r in child['records']) != ['p1','p2','p3']
            or child['bindings'].get(str(boundary/'project-banked.v')) != sha(boundary/'project-banked.v')):
            raise ValueError('replay scope/source binding differs')
        bindings.update(child['bindings']); bindings[str(packet)] = sha(packet)
        result.update(status='GPU_ICACHE_PIPELINE_REPRESENTATIVE_STAGE_PASS',
            reason='Changed instruction cache executed three full-output kernels; all-case counters, protocol, timing and power remain')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); verify(bindings)
    result['artifacts'] = {p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status'] == 'GPU_ICACHE_PIPELINE_REPRESENTATIVE_STAGE_PASS' else 1


if __name__ == '__main__': raise SystemExit(main())
