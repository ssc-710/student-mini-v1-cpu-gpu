"""Route only the actual legalized CPU ECO, retaining strict CTS and GRT gates."""
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
from scripts.student_mini_route_cts_gate import inject
from scripts.route_student_mini_platform import checked_parent


def eco_checker(parent):
    checked_parent(parent, 'cpu')
    checker = Path(parent['supply_checker'])
    if parent['bindings'].get(str(checker)) != sha(checker): raise ValueError('ECO supply checker changed')
    logs = [Path(p) for p in parent['artifacts'] if Path(p).name == 'macro-power.log']
    if len(logs) != 1 or parent['artifacts'][str(logs[0])] != sha(logs[0]):
        raise ValueError('actual ECO macro power log missing or changed')
    if logs[0].read_text().splitlines().count('CPU_MACRO_POWER_CONNECTED macros=29 pins=58') != 1:
        raise ValueError('actual ECO supply marker missing')
    return [checker]


def derive(source, root):
    source = inject(source)
    source = source.replace('ROOT = Path(__file__).resolve().parents[1]', 'ROOT = Path('+repr(str(root))+')', 1)
    source = source.replace('paths = [Path(__file__),', "paths = [Path(__file__), ROOT/'scripts/route_student_mini_cpu_drive_eco.py', ROOT/'scripts/route_student_mini_platform.py',", 1)
    begin = source.index('        checker_names = '); end = source.index('        if len(checkers) != 1:', begin)
    return source[:begin]+('        from scripts.route_student_mini_cpu_drive_eco import eco_checker\n'
                          '        checkers = eco_checker(parent)\n')+source[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--placement', type=Path, required=True)
    args = parser.parse_args(); packet = args.placement.resolve()/'completion.json'
    parent = json.loads(packet.read_text()); verify(parent['bindings']); eco_checker(parent)
    original = ROOT/'scripts/route_student_mini_platform.py'
    paths = [Path(__file__), original, ROOT/'scripts/student_mini_route_cts_gate.py', packet]
    bindings = {str(p): sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-drive-eco-route-launch'/key; work.mkdir(parents=True, exist_ok=False)
    private = work/'producer.py'; private.write_text(derive(original.read_text(), ROOT)); bindings[str(private)] = sha(private)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='LEGALIZED_ECO_CTS_QUEUED')), flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable, str(private), '--platform', 'cpu', '--placement', str(args.placement.resolve())],
                               cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows: result['child'] = rows[-1]
    verify(bindings)
    if not code and result.get('child', {}).get('status') == 'PLATFORM_ROUTE_STAGE_PASS': result['status'] = 'CPU_DRIVE_ECO_ROUTE_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('child'))), flush=True)
    return code


if __name__ == '__main__': raise SystemExit(main())
