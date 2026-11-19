"""One additional measured weak gate on the preserved legalized CPU HOLD."""
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
from scripts.probe_student_mini_cpu_two_gates import equivalent_cells
from scripts.apply_student_mini_cpu_drive_eco import parse_eco


def equivalent_three(liberty):
    signatures = equivalent_cells(liberty)
    extra = []
    for strength in (1, 4):
        cell = 'sky130_fd_sc_hd__nand2_'+str(strength)
        blocks = re.findall(r'(?ms)^    cell \("'+cell+r'"\) \{.*?(?=^    cell |\Z)', liberty)
        if len(blocks) != 1: raise ValueError('unique NAND2 Liberty required')
        pins = re.findall(r'(?ms)^        pin \("([^\"]+)"\)\s*\{(.*?)(?=^        (?:pin|pg_pin) |\Z)', blocks[0])
        signature = sorted((name, re.findall(r'\bdirection\s*:\s*"?(input|output)"?\s*;', body),
                            re.findall(r'\bfunction\s*:\s*"([^"]+)"', body)) for name, body in pins)
        if [x[0] for x in signature] != ['A', 'B', 'Y'] or signature[-1][1:] != (['output'], ['!(A&B)']):
            raise ValueError('unexpected NAND pin function')
        extra.append(signature)
    if extra[0] != extra[1]: raise ValueError('NAND drive functions differ')
    return signatures+[extra[0]]


def parse_three(log, expected):
    if log.count('CPU_DRIVE_ECO_COMPLETE gates=3 macros=29 topology_preserved=1') != 1:
        raise ValueError('three-gate topology witness required')
    return parse_eco(log.replace('gates=3 macros=29', 'gates=2 macros=29'), expected)


def sources(producer, hook, root, hook_path):
    for old, new in {
        'ROOT = Path(__file__).resolve().parents[1]': 'ROOT = Path('+repr(str(root))+')',
        "hook = ROOT/'integration/student-mini/cpu_multiplier_drive_eco.tcl'": 'hook = Path('+repr(str(hook_path))+')',
        "paths = [Path(__file__),": "paths = [Path(__file__), ROOT/'scripts/apply_student_mini_cpu_drive_eco.py', ROOT/'scripts/retry_student_mini_cpu_drive_eco.py',",
        'signature = equivalent_cells(liberty.read_text())': 'signature = equivalent_three(liberty.read_text())',
        "parse_eco((work/'eco.log').read_text(), parent['placement_wns_ns'])": "parse_three((work/'eco.log').read_text(), parent['placement_wns_ns'])",
        'def main():': 'from scripts.retry_student_mini_cpu_drive_eco import equivalent_three, parse_three\n\ndef main():',
        'Two equivalent drive changes legalized': 'Three equivalent drive changes legalized',
    }.items():
        if producer.count(old) != 1: raise ValueError('ECO producer seam changed: '+old)
        producer = producer.replace(old, new)
    for old, new in {
        '_096034_ sky130_fd_sc_hd__nor3_1}': '_096034_ sky130_fd_sc_hd__nor3_1 _081246_ sky130_fd_sc_hd__nand2_1}',
        '_096034_ sky130_fd_sc_hd__nor3_4}': '_096034_ sky130_fd_sc_hd__nor3_4 _081246_ sky130_fd_sc_hd__nand2_4}',
        'detailed_placement\n': 'replace_cell _081246_ sky130_fd_sc_hd__nand2_4\ndetailed_placement\n',
        'gates=2 macros=29': 'gates=3 macros=29',
    }.items():
        if hook.count(old) != 1: raise ValueError('ECO hook seam changed')
        hook = hook.replace(old, new)
    return producer, hook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--failed-eco', type=Path, required=True)
    parser.add_argument('--placement', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    args = parser.parse_args(); packet = args.failed_eco.resolve()/'completion.json'
    parent = json.loads(packet.read_text()); verify(parent['bindings'])
    log = packet.parent/'eco.log'
    if (parent['status'] != 'HOLD' or parent['reason'] != 'ValueError: legalized CPU ECO fails 100 MHz: -0.009234 ns'
        or parent['artifacts'].get(str(log)) != sha(log) or '_081246_/Y (sky130_fd_sc_hd__nand2_1)' not in log.read_text()
        or parent['bindings'].get(str(args.placement.resolve()/'completion.json')) != sha(args.placement.resolve()/'completion.json')):
        raise ValueError('actual bound residual -9.234 ps path required')
    original = ROOT/'scripts/apply_student_mini_cpu_drive_eco.py'
    hook_original = ROOT/'integration/student-mini/cpu_multiplier_drive_eco.tcl'
    bindings = {str(p): sha(p) for p in (Path(__file__), packet, log, original, hook_original)}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-three-gate-eco-launch'/key; work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'; hook = work/'eco.tcl'
    body, tcl = sources(original.read_text(), hook_original.read_text(), ROOT, hook)
    producer.write_text(body); hook.write_text(tcl)
    bindings.update({str(p): sha(p) for p in (producer, hook)})
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='RESIDUAL_NAND_DRIVE_ECO_QUEUED')), flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable, str(producer), '--placement', str(args.placement.resolve()),
                                '--probe', str(args.probe.resolve())], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows: result['child'] = rows[-1]
    verify(bindings)
    if not code and result.get('child', {}).get('status') == 'CPU_PLACEMENT_PREFLIGHT_STAGE_PASS':
        result['status'] = 'CPU_THREE_GATE_ECO_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('child'))), flush=True)
    return code


if __name__ == '__main__': raise SystemExit(main())
