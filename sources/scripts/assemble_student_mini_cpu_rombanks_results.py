"""Publish the complete 1000-record CPU observations of the final 25-ROM-bank replay.

Identical to assemble_student_mini_cpu_packed_results.py except that the accepted
parent is the ROM-bank full replay (CPU_ROM_BANKS_COLD_START_REPLAY_STAGE_PASS) of the
final (12 SRAM + 25 ROM-bank macro) CPU mapping.
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
from scripts.assemble_student_mini_cpu_dfi_results import derive as dfi_derive

PACKED = 'CPU_ROM_BANKS_COLD_START_REPLAY_STAGE_PASS'


def derive(source, root):
    source = dfi_derive(source, root)
    changes = {"'CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS'": repr(PACKED),
               'paths=[Path(__file__),': "paths=[Path(__file__),ROOT/'scripts/assemble_student_mini_cpu_rombanks_results.py',",
               'aligned read-valid CPU observations with fresh counters;': 'aligned read-valid CPU observations on the final 12-SRAM + 25-ROM-bank mapping with fresh counters;'}
    for old, new in changes.items():
        if source.count(old) != 1:
            raise ValueError('ROM-bank result assembler seam changed: ' + old)
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--vectors', type=Path, required=True)
    args = parser.parse_args()
    source = args.replay.resolve()
    receipt = source / 'completion.json'
    parent = json.loads(receipt.read_text())
    if (parent['status'] != PACKED or parent.get('independent_external_memory') is not True
            or parent.get('dfi_output_latency_cycles') != 1 or parent['transcript_join']['baseline_records'] != 1000):
        raise ValueError('complete fresh ROM-bank replay required')
    verify(parent['bindings'])
    mapping = json.loads((Path(parent['parent_mapping']) / 'completion.json').read_text())
    if mapping.get('macro_count') != 12 or mapping.get('rom_banks') != 25 or mapping.get('native_read_valid_added_cycles') != 1:
        raise ValueError('final 12-SRAM + 25-ROM-bank aligned mapping required')
    original = ROOT / 'scripts/assemble_student_mini_cpu_request_results.py'
    bindings = dict(parent['bindings'])
    for name, digest in parent['artifacts'].items():
        path = source / name
        if sha(path) != digest:
            raise ValueError('ROM-bank replay artifact changed')
        bindings[str(path)] = digest
    bindings.update({str(p): sha(p) for p in (Path(__file__), ROOT / 'scripts/assemble_student_mini_cpu_dfi_results.py', ROOT / 'scripts/assemble_student_mini_cpu_packed_results.py',
                                              original, receipt, args.vectors.resolve())})
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/cpu-rombanks-results' / key
    work.mkdir(parents=True, exist_ok=False)
    compact = work / 'qualified'
    compact.mkdir()
    records = compact / 'uart-records.log'
    with (source / 'console.log').open() as raw, records.open('x') as output:
        for line in raw:
            if line.startswith(('STUDENT_CPU ', 'STUDENT_CPU_', 'STUDENT_NATIVE_', 'CPU_BOUNDARY_REPLAY_COMPLETE ')):
                output.write(line)
    measured = compact / 'measurements.json'
    measured.write_text(json.dumps(parent['transcript_join'], indent=2) + '\n')
    bindings.update({str(p): sha(p) for p in (records, measured)})
    qualified = dict(parent, bindings=dict(bindings), source_replay=str(source), fresh_rtl_execution_performed=False,
                     source_receipt_sha256=sha(receipt), artifacts={p.name: sha(p) for p in (records, measured)})
    packet = compact / 'completion.json'
    packet.write_text(json.dumps(qualified, indent=2) + '\n')
    bindings[str(packet)] = sha(packet)
    private = work / 'producer.py'
    private.write_text(derive(original.read_text(), ROOT))
    bindings[str(private)] = sha(private)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False)
    (work / 'inputs.json').write_text(json.dumps(result, indent=2) + '\n')
    verify(bindings)
    with (work / 'assemble.log').open('x') as log:
        code = subprocess.call([sys.executable, str(private), '--qualified', str(compact), '--vectors', str(args.vectors.resolve())],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work / 'assemble.log').read_text().splitlines() if x.startswith('{')]
    if rows:
        result['report'] = rows[-1]
    verify(bindings)
    if code == 0 and result.get('report', {}).get('numeric_matches') == 1000:
        result['status'] = 'CPU_ROM_BANKS_COMPLETE_RESULT_STAGE_PASS'
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], report=result.get('report'))), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
