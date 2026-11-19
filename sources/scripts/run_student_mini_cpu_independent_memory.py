"""Re-run a proved, unchanged CPU with its own original external memory model."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def derive(source, reference_producer, receipt):
    changes = {
        'from scripts.student_mini_cpu_replay_sources import reference_source,quiet_macro,wrapper,compare_transcripts,TOP':
        'from scripts.student_mini_cpu_replay_sources import reference_source,quiet_macro,compare_transcripts,TOP\nfrom scripts.student_mini_cpu_independent_memory import wrapper,memory_source',
        'paths=[Path(__file__),':
        "paths=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_independent_memory.py',ROOT/'scripts/student_mini_cpu_independent_memory.py',Path("+repr(str(reference_producer))+"),Path("+repr(str(receipt))+"),",
        '        reference.write_text(reference_source(rtl.read_text()))':
        "        reference.write_text(reference_source(rtl.read_text()))\n        environment=work/'independent-memory.v';environment.write_text(memory_source(rtl.read_text()))",
        "compilation += [mapping/'mapped.v',actual_macro,bridge]":
        "compilation += [mapping/'mapped.v',actual_macro,bridge,environment]",
        "for path in [*sources,reference,actual_macro,bridge,*work.glob('*.init')]:":
        "for path in [*sources,reference,actual_macro,bridge,environment,*work.glob('*.init')]:",
        "result.update(status='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS',cold_start_replay_complete=True,":
        "result.update(status='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS',cold_start_replay_complete=True,independent_external_memory=True,memory_return_lockstep_checked=True,",
    }
    for old, new in changes.items():
        if source.count(old) != 1: raise ValueError('independent-memory replay seam changed: '+old)
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--replay', type=Path, required=True)
    args = parser.parse_args(); receipt = args.replay.resolve()/'completion.json'
    parent = json.loads(receipt.read_text())
    if parent['status'] != 'CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS' or parent['transcript_join']['baseline_records'] != 1000:
        raise ValueError('unchanged full CPU reference replay required')
    producers = [Path(p) for p in parent['bindings'] if '/cpu-tag-bank-replay/' in p and p.endswith('/producer.py')]
    if len(producers) != 1: raise ValueError('unique qualified bank-tag CPU producer required')
    original = producers[0]; bindings = dict(parent['bindings']); verify(bindings)
    paths = [Path(__file__), ROOT/'scripts/student_mini_cpu_independent_memory.py', receipt, original]
    bindings.update({str(p): sha(p) for p in paths})
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-independent-memory-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'; producer.write_text(derive(original.read_text(), original, receipt))
    bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False,
                  actual_rtl_changed=False, old_cycle_checks_retained=True)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='INDEPENDENT_MEMORY_FULL_CPU_PROOF_QUEUED')), flush=True)
    with (work/'replay.log').open('x') as log:
        code = subprocess.call([sys.executable, str(producer), '--mapping', parent['parent_mapping'],
                                '--cpu-run', parent['parent_cpu']], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    rows = [json.loads(line) for line in (work/'replay.log').read_text().splitlines() if line.startswith('{')]
    if rows: result['replay'] = rows[-1]
    verify(bindings)
    if code == 0 and result.get('replay', {}).get('status') == 'CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS':
        packet = Path(result['replay']['work'])/'completion.json'; child = json.loads(packet.read_text())
        if child.get('independent_external_memory') is not True or child.get('memory_return_lockstep_checked') is not True:
            raise ValueError('independent memory proof markers missing')
        verify(child['bindings']); bindings.update(child['bindings']); bindings[str(packet)] = sha(packet)
        result['status'] = 'CPU_INDEPENDENT_MEMORY_LOCKSTEP_STAGE_PASS'
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('replay'))), flush=True)
    return 0 if result['status'] == 'CPU_INDEPENDENT_MEMORY_LOCKSTEP_STAGE_PASS' else 1


if __name__ == '__main__': raise SystemExit(main())
