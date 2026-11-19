"""Legalize the measured two-cell CPU drive ECO in a new, immutable variant.

No logic/precision/clock change. Negative timing or legalization errors stop
before routing. This stage never issues a whole physical or baseline PASS.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify, execute_locked_route
from scripts.probe_student_mini_cpu_two_gates import equivalent_cells


def parse_eco(log, expected):
    rows = re.findall(r'(?m)^CPU_DRIVE_ECO stage=(original|legalized)\nworst slack max (-?\d+\.\d+)\s*$', log)
    if [x[0] for x in rows] != ['original', 'legalized'] or 'Error:' in log or '[ERROR' in log:
        raise ValueError('complete actual original and legalized timing required')
    if log.splitlines().count('CPU_DRIVE_ECO_COMPLETE gates=2 macros=29 topology_preserved=1') != 1:
        raise ValueError('topology and legalization witness missing')
    initial, final = [float(x[1]) for x in rows]
    if not all(math.isfinite(x) for x in (initial, final)) or abs(initial-expected) > .001:
        raise ValueError('original timing not reproduced')
    if final < 0:
        raise ValueError(f'legalized CPU ECO fails 100 MHz: {final} ns')
    return final


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    args = parser.parse_args()
    packet = args.placement.resolve()/'completion.json'
    probe_packet = args.probe.resolve()/'completion.json'
    parent = json.loads(packet.read_text()); probe = json.loads(probe_packet.read_text())
    if (parent['status'] != 'HOLD' or parent['clock_period_ns'] != 10
        or parent['macro_power_connected'] is not True or parent['geometry']['macro_count'] != 29):
        raise ValueError('powered frozen 29-macro CPU placement HOLD required')
    if (probe['status'] != 'CPU_MULTIPLIER_DRIVE_DIAGNOSTIC_COMPLETE'
        or probe['worst_slack_ns_by_strength']['4'] < 0
        or probe['bindings'].get(str(packet)) != sha(packet)):
        raise ValueError('same-placement positive two-gate diagnostic required')
    bindings = dict(parent['bindings']); bindings.update(probe['bindings']); verify(bindings)
    flow = Path('/home/soclab/src/orfs-clean-aabf2a/flow')
    platform = flow/'platforms/sky130hd'
    liberty = platform/'lib/sky130_fd_sc_hd__tt_025C_1v80.lib'
    rc = platform/'setRC.tcl'; tool = Path('/home/soclab/.local/bin/openroad')
    old_results = Path(parent['result_directory'])
    if old_results.parent != flow/'results/sky130hd/cpu_student_mini_physical_top_asic':
        raise ValueError('unexpected frozen placement location')
    odb = old_results/'3_5_place_dp.odb'; sdc = old_results/'3_place.sdc'
    old_config = Path(parent['config'])
    for path in (odb, sdc, old_config):
        if parent['artifacts'].get(str(path)) != sha(path): raise ValueError('source checkpoint changed')
    macro = Path(re.findall(r'^export ADDITIONAL_LIBS = (.+)$', old_config.read_text(), re.M)[0])
    signature = equivalent_cells(liberty.read_text())
    # Preserve the actual source-bound supply checker already used by this parent.
    checkers = [Path(p) for p in parent['bindings'] if Path(p).name == 'power.tcl'
                and Path(p).parent.parent.name == 'cpu-dfi-physical-continuation']
    if len(checkers) != 1: raise ValueError('unique bound macro supply checker required')
    checker = checkers[0]
    from scripts.continue_student_mini_cpu_request_route import bound_checker
    bound_checker(parent, checker, checker.parent/'placement-producer.py', 'cpu', 29)
    hook = ROOT/'integration/student-mini/cpu_multiplier_drive_eco.tcl'
    paths = [Path(__file__), packet, probe_packet, odb, sdc, old_config, liberty, rc, macro, tool, hook,
             ROOT/'scripts/retry_student_mini_route.py', ROOT/'scripts/probe_student_mini_cpu_two_gates.py',
             ROOT/'scripts/continue_student_mini_cpu_request_route.py']
    bindings.update({str(p): sha(p) for p in paths})
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-drive-eco'/identity; work.mkdir(parents=True, exist_ok=False)
    variant = 'student-mini-cpu-drive-eco-'+identity[:16]
    results = old_results.parent/variant
    config = work/'config.mk'; shutil.copyfile(old_config, config); bindings[str(config)] = sha(config)
    result = dict(status='HOLD', bindings=bindings, preflight_complete=False,
                  formal_baseline=False, physical_evidence_complete=False, clock_period_ns=10, threads=2,
                  macro_power_connected=False, geometry=parent['geometry'], config=str(config),
                  result_directory=str(results), reports_directory=str(work), parent_placement=str(packet),
                  supply_checker=str(checker), equivalent_cell_signatures=signature,
                  precision_changed=False, clock_changed=False, parent_synthesis=parent.get('parent_synthesis'))
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n')
    start = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-start))+'\n')
    print(json.dumps(dict(work=str(work), stage='CPU_DRIVE_ECO_QUEUED')), flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); fcntl.flock(lock, fcntl.LOCK_EX); verify(bindings)
            results.mkdir(parents=True, exist_ok=False)
            command = ['env', f'MINI_SC_LIB={liberty}', f'MINI_MACRO_LIB={macro}', f'MINI_RC={rc}',
                       f'MINI_ODB={odb}', f'MINI_SDC={sdc}', f'MINI_OUTPUT={results}', str(tool), '-exit', str(hook)]
            if execute_locked_route(command, work/'eco.log', 600, lambda _: heartbeat('LEGALIZING_TWO_GATE_ECO')):
                raise ValueError('OpenROAD ECO/legalization failed')
            result['placement_wns_ns'] = parse_eco((work/'eco.log').read_text(), parent['placement_wns_ns'])
            for name in ('3_place.odb', '3_place.v', '3_place.sdc'):
                if not (results/name).is_file() or not (results/name).stat().st_size: raise ValueError('missing ECO artifact')
            command = ['env', f'STUDENT_MINI_PDN_ODB={results}/3_place.odb', str(tool), '-exit', str(checker)]
            if execute_locked_route(command, work/'macro-power.log', 120, lambda _: heartbeat('CHECKING_MACRO_SUPPLY')):
                raise ValueError('ECO macro supply check failed')
            if (work/'macro-power.log').read_text().splitlines().count('CPU_MACRO_POWER_CONNECTED macros=29 pins=58') != 1:
                raise ValueError('actual macro supply assertion missing')
            verify(bindings)
            result.update(status='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS', preflight_complete=True,
                          macro_power_connected=True, reason='Two equivalent drive changes legalized at 100 MHz; CTS/route/activity/power remain')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-start
    result['artifacts'] = {str(p): sha(p) for folder in (work, results) if folder.exists()
                           for p in folder.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'], wns=result.get('placement_wns_ns'))), flush=True)
    return 0 if result['preflight_complete'] else 1


if __name__ == '__main__': raise SystemExit(main())
