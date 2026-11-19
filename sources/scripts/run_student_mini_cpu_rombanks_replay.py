"""Complete fail-fast CPU replay of the 25-bank ROM boundary (12 SRAM macros + 25 ROM bank blocks).

Reuses the exact DFI fail-fast replay producer; only the accepted parent stage
(ROM split into 25 per-bank modules) and the reported status differ.
"""
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
from scripts.run_student_mini_cpu_dfi_failfast import replay_source

PASS = 'CPU_ROM_BANKS_COLD_START_REPLAY_STAGE_PASS'
PARENT = 'CPU_ROM_BANKS_MAPPING_STAGE_PASS'


def romblock_source(source, root):
    value = replay_source(source, root)
    changes = {
        "parent['status']!='CPU_DFI_OUTPUT_MAPPING_STAGE_PASS' or parent.get('macro_count')!=29":
            f"parent['status']!='{PARENT}' or parent.get('macro_count')!=12",
        "'CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS'": repr(PASS),
        "'build/student-mini/cpu-boundary-replay'": "'build/student-mini/cpu-rombanks-replay'",
        'paths=[Path(__file__),': "paths=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_rombanks_replay.py',",
    }
    for old, new in changes.items():
        expected = 2 if old == "'CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS'" else 1
        if value.count(old) != expected:
            raise ValueError('ROM-block replay seam changed: ' + old)
        value = value.replace(old, new)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--cpu-run', type=Path, required=True)
    args = parser.parse_args()
    mapping = args.mapping.resolve()
    parent = json.loads((mapping / 'completion.json').read_text())
    if parent['status'] != PARENT or parent.get('macro_count') != 12:
        raise ValueError('25-bank ROM 12-macro mapping required')
    verify(parent['bindings'])
    original = ROOT / 'scripts/run_student_mini_cpu_boundary_replay.py'
    paths = [Path(__file__), original, ROOT / 'scripts/run_student_mini_cpu_dfi_failfast.py',
             ROOT / 'scripts/run_student_mini_cpu_dfi_replay.py', ROOT / 'scripts/run_student_mini_cpu_latency_replay.py',
             ROOT / 'tests/rtl/student_mini_cpu_failfast_main.cpp', mapping / 'completion.json']
    bindings = {str(p): sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(dict(bindings=bindings, cpu=str(args.cpu_run.resolve())), sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/cpu-rombanks-replay-launch' / key
    work.mkdir(parents=True, exist_ok=False)
    producer = work / 'producer.py'
    producer.write_text(romblock_source(original.read_text(), ROOT))
    bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False,
                  cycle_equivalence=False, macro_count=12)
    (work / 'inputs.json').write_text(json.dumps(result, indent=2) + '\n')
    verify(bindings)
    print(json.dumps(dict(work=str(work), stage='ROM_BANKS_COMPLETE_REPLAY_QUEUED')), flush=True)
    with (work / 'replay.log').open('x') as log:
        code = subprocess.call([sys.executable, str(producer), '--mapping', str(mapping), '--cpu-run', str(args.cpu_run.resolve())],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work / 'replay.log').read_text().splitlines() if x.startswith('{')]
    if rows:
        result['replay'] = rows[-1]
    verify(bindings)
    if not code and result.get('replay', {}).get('status') == PASS:
        child_packet = Path(result['replay']['work']) / 'completion.json'
        child = json.loads(child_packet.read_text())
        verify(child['bindings'])
        bindings.update(child['bindings'])
        bindings[str(child_packet)] = sha(child_packet)
        if child['transcript_join']['baseline_records'] != 1000 or child.get('independent_external_memory') is not True:
            raise ValueError('incomplete ROM-block CPU execution')
        result['status'] = 'CPU_ROM_BANKS_FULL_REPLAY_STAGE_PASS'
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('replay'))), flush=True)
    return 0 if result['status'] == 'CPU_ROM_BANKS_FULL_REPLAY_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
