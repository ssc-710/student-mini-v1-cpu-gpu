"""Accept the pinned NAND's explicit De Morgan spelling; preserve failed checker."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.retry_student_mini_cpu_drive_eco import sources, parse_three
from scripts.probe_student_mini_cpu_two_gates import equivalent_cells


def equivalent_three(liberty):
    signatures = equivalent_cells(liberty); extra = []
    for strength in (1, 4):
        blocks = re.findall(r'(?ms)^    cell \("sky130_fd_sc_hd__nand2_'+str(strength)+r'"\) \{.*?(?=^    cell |\Z)', liberty)
        if len(blocks) != 1: raise ValueError('unique pinned NAND required')
        pins = re.findall(r'(?ms)^        pin \("([^\"]+)"\)\s*\{(.*?)(?=^        (?:pin|pg_pin) |\Z)', blocks[0])
        signature = sorted((name, re.findall(r'\bdirection\s*:\s*"?(input|output)"?\s*;', body),
                            re.findall(r'\bfunction\s*:\s*"([^"]+)"', body)) for name, body in pins)
        if signature != [('A', ['input'], []), ('B', ['input'], []), ('Y', ['output'], ['(!A) | (!B)'])]:
            raise ValueError('pinned NAND direction/function changed')
        extra.append(signature)
    if extra[0] != extra[1]: raise ValueError('non-equivalent drive variants')
    return signatures+[extra[0]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--failed-launch', type=Path, required=True)
    args = parser.parse_args(); packet = args.failed_launch.resolve()/'completion.json'
    failed = json.loads(packet.read_text()); verify(failed['bindings'])
    log = packet.parent/'child.log'
    if failed['status'] != 'HOLD' or 'ValueError: unexpected NAND pin function' not in log.read_text():
        raise ValueError('exact preserved function-spelling failure required')
    old_producer = packet.parent/'producer.py'; old_hook = packet.parent/'eco.tcl'
    bindings = dict(failed['bindings']); bindings.update({str(p): sha(p) for p in (Path(__file__), packet, log)})
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-three-gate-liberty-launch'/key; work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'
    body = old_producer.read_text()
    needle = 'from scripts.retry_student_mini_cpu_drive_eco import equivalent_three, parse_three'
    if body.count(needle) != 1: raise ValueError('private parser seam changed')
    body = body.replace(needle, 'from scripts.resume_student_mini_cpu_drive_eco_liberty import equivalent_three, parse_three')
    body = body.replace('paths = [Path(__file__),', "paths = [Path(__file__), ROOT/'scripts/resume_student_mini_cpu_drive_eco_liberty.py',", 1)
    producer.write_text(body); bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    original_eco = json.loads(Path(next(p for p in failed['bindings'] if '/cpu-drive-eco/' in p and p.endswith('/completion.json'))).read_text())
    placement = Path(original_eco['parent_placement']).parent
    probe = Path(next(p for p in original_eco['bindings'] if '/cpu-multiplier-drive-probe/5d5d' in p and p.endswith('/completion.json'))).parent
    print(json.dumps(dict(work=str(work), stage='PINNED_LIBERTY_ECO_QUEUED')), flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable, str(producer), '--placement', str(placement), '--probe', str(probe)],
                               cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows: result['child'] = rows[-1]
    verify(bindings)
    if not code and result.get('child', {}).get('status') == 'CPU_PLACEMENT_PREFLIGHT_STAGE_PASS': result['status'] = 'CPU_THREE_GATE_ECO_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('child'))), flush=True)
    return code


if __name__ == '__main__': raise SystemExit(main())
