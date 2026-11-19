"""Complete CPU replay of the final ROM-bank boundary with the port-activity recorder.

The exact ROM-bank full-replay producer (run_student_mini_cpu_rombanks_replay.py)
is reused; the only derivation is the bridge, which gets the observation-only
recorder of scripts/student_mini_cpu_port_trace.py, and the work root.  The
replay still has to reproduce every baseline record and Nano session row of
the executed CPU (same pass criteria).  The child work directory holds
port-trace.txt for the gate-level power replay.
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
from scripts.run_student_mini_cpu_rombanks_replay import romblock_source, PARENT, PASS


def traced_source(source, root):
    value = romblock_source(source, root)
    changes = {
        "bridge.write_text(wrapper(design['modules'][TOP]['ports']))":
            "bridge.write_text(__import__('scripts.student_mini_cpu_port_trace',fromlist=['traced']).traced("
            "wrapper(design['modules'][TOP]['ports']),design['modules'][TOP]['ports']))",
        "'build/student-mini/cpu-rombanks-replay'": "'build/student-mini/cpu-activity-replay'",
        "paths=[Path(__file__),": "paths=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_activity_trace.py',"
                                  "ROOT/'scripts/student_mini_cpu_port_trace.py',",
    }
    for old, new in changes.items():
        if value.count(old) != 1:
            raise ValueError('CPU activity replay seam changed: ' + old)
        value = value.replace(old, new)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--cpu-run', type=Path, required=True)
    args = parser.parse_args()
    mapping = args.mapping.resolve()
    parent = json.loads((mapping / 'completion.json').read_text())
    if parent['status'] != PARENT or parent.get('rom_banks') != 25:
        raise ValueError('25-bank ROM mapping required')
    verify(parent['bindings'])
    original = ROOT / 'scripts/run_student_mini_cpu_boundary_replay.py'
    paths = [Path(__file__), ROOT / 'scripts/student_mini_cpu_port_trace.py', ROOT / 'scripts/run_student_mini_cpu_rombanks_replay.py',
             original, ROOT / 'scripts/run_student_mini_cpu_dfi_failfast.py', ROOT / 'tests/rtl/student_mini_cpu_failfast_main.cpp',
             mapping / 'completion.json']
    bindings = {str(p): sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(dict(bindings=bindings, cpu=str(args.cpu_run.resolve())), sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/cpu-activity-replay-launch' / key
    work.mkdir(parents=True, exist_ok=False)
    producer = work / 'producer.py'
    producer.write_text(traced_source(original.read_text(), ROOT))
    bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, purpose='gate-level activity stimulus')
    (work / 'inputs.json').write_text(json.dumps(result, indent=2) + '\n')
    with (work / 'replay.log').open('x') as log:
        code = subprocess.call([sys.executable, str(producer), '--mapping', str(mapping), '--cpu-run', str(args.cpu_run.resolve())],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work / 'replay.log').read_text().splitlines() if x.startswith('{')]
    if rows:
        result['replay'] = rows[-1]
    verify(bindings)
    if not code and result.get('replay', {}).get('status') == PASS:
        child = Path(result['replay']['work'])
        trace = child / 'port-trace.txt'
        if not trace.is_file():
            raise ValueError('traced replay left no port trace')
        result.update(status='CPU_ACTIVITY_TRACE_STAGE_PASS', child=str(child), trace_bytes=trace.stat().st_size,
                      reason='Full replay passed with the observation-only port recorder')
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], replay=result.get('replay'))), flush=True)
    return 0 if result['status'] == 'CPU_ACTIVITY_TRACE_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
