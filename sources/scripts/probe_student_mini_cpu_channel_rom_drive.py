"""Measure the actual wider-channel ROM critical gate, not the old multiplier."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify, execute_locked_route
from scripts.audit_student_mini_cpu_timing import worst_setup


def equivalent_cells(liberty):
    signatures = []
    for strength in (0, 1, 2, 4):
        name = 'sky130_fd_sc_hd__o21ai_'+str(strength)
        blocks = re.findall(r'(?ms)^    cell \("'+name+r'"\) \{.*?(?=^    cell |\Z)', liberty)
        if len(blocks) != 1: raise ValueError('unique actual O21AI cell required')
        pins = re.findall(r'(?ms)^        pin \("([^\"]+)"\)\s*\{(.*?)(?=^        (?:pin|pg_pin) |\Z)', blocks[0])
        signature = sorted((name, re.findall(r'\bdirection\s*:\s*"?(input|output)"?\s*;', body),
                            re.findall(r'\bfunction\s*:\s*"([^"]+)"', body)) for name, body in pins)
        if ([p[0] for p in signature] != ['A1','A2','B1','Y']
            or any(p[1] != ['input'] or p[2] for p in signature[:-1])
            or signature[-1][1] != ['output'] or len(signature[-1][2]) != 1):
            raise ValueError('actual O21AI pin/function signature differs')
        signatures.append(signature)
    if any(s != signatures[0] for s in signatures[1:]): raise ValueError('non-equivalent drive cells')
    return signatures[0]


def parse_probe(log, expected):
    rows = re.findall(r'(?m)^CPU_ROM_DRIVE_PROBE strength=([0124])\nworst slack max (-?\d+\.\d+)\s*$', log)
    if [s for s,v in rows] != ['0','1','2','4'] or '[ERROR' in log or 'Error:' in log:
        raise ValueError('complete actual four-strength measurements required')
    if log.splitlines().count('CPU_ROM_DRIVE_COMPLETE gates=1 diagnostic_only=1 no_checkpoint_written=1') != 1:
        raise ValueError('actual topology witness missing')
    values = {s:float(v) for s,v in rows}
    if not all(math.isfinite(v) for v in values.values()) or abs(values['0']-expected) > .001:
        raise ValueError('actual original timing did not reproduce')
    return values


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    args = parser.parse_args(); packet = args.placement.resolve()/'completion.json'
    parent = json.loads(packet.read_text())
    if (parent['status'] != 'HOLD' or parent['clock_period_ns'] != 10 or parent['geometry']['gap'] != 160
        or parent['geometry']['macro_count'] != 29 or parent['macro_power_connected'] is not True):
        raise ValueError('actual wider-channel powered CPU timing HOLD required')
    report = Path(parent['reports_directory'])/'3_detailed_place.rpt'
    odb = Path(parent['result_directory'])/'3_5_place_dp.odb'
    sdc = Path(parent['result_directory'])/'3_place.sdc'
    for path in (report, odb, sdc):
        if parent['artifacts'].get(str(path)) != sha(path): raise ValueError('actual placement artifact changed')
    observed = worst_setup(report.read_text(), parent['placement_wns_ns'])
    if (not observed['startpoint'].startswith('rom_request_boundary.rom_address[0]')
        or not observed['endpoint'].startswith('mini_rom_bank_data[17][22]')
        or '_125420_/Y (sky130_fd_sc_hd__o21ai_0)' not in report.read_text()):
        raise ValueError('actual ROM worst path differs')
    platform = Path('/home/soclab/src/orfs-clean-aabf2a/flow/platforms/sky130hd')
    liberty = platform/'lib/sky130_fd_sc_hd__tt_025C_1v80.lib'; rc = platform/'setRC.tcl'
    macro = Path(re.findall(r'^export ADDITIONAL_LIBS = (.+)$', Path(parent['config']).read_text(), re.M)[0])
    hook = ROOT/'integration/student-mini/cpu_channel_rom_drive_probe.tcl'; tool = Path('/home/soclab/.local/bin/openroad')
    signature = equivalent_cells(liberty.read_text())
    bindings = dict(parent['bindings']); verify(bindings)
    files = [Path(__file__), packet, report, odb, sdc, liberty, macro, rc, hook, tool,
             ROOT/'scripts/audit_student_mini_cpu_timing.py', ROOT/'scripts/retry_student_mini_route.py']
    bindings.update({str(p):sha(p) for p in files})
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-channel-rom-drive'/key; work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', bindings=bindings, diagnostic_only=True, formal_baseline=False,
                  physical_evidence_complete=False, observed_path=observed, equivalent_cell_signature=signature)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); begin = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage, updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work), stage='ROM_GATE_DIAGNOSTIC_QUEUED')), flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); fcntl.flock(lock, fcntl.LOCK_EX); verify(bindings)
            command = ['env', f'MINI_SC_LIB={liberty}', f'MINI_MACRO_LIB={macro}', f'MINI_RC={rc}',
                       f'MINI_ODB={odb}', f'MINI_SDC={sdc}', str(tool), '-exit', str(hook)]
            if execute_locked_route(command, work/'probe.log', 180, lambda _:heartbeat('MEASURING_SINGLE_ROM_GATE')):
                raise ValueError('actual OpenROAD gate probe failed')
            result['worst_slack_ns_by_strength'] = parse_probe((work/'probe.log').read_text(), parent['placement_wns_ns'])
            verify(bindings); result.update(status='CPU_CHANNEL_ROM_DRIVE_DIAGNOSTIC_COMPLETE',
                reason='One equivalent gate strength measured; no legalization/route/power acceptance')
    except Exception as error: result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-begin
    result['artifacts'] = {p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], measurements=result.get('worst_slack_ns_by_strength'), reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'CPU_CHANNEL_ROM_DRIVE_DIAGNOSTIC_COMPLETE' else 1


if __name__ == '__main__': raise SystemExit(main())
