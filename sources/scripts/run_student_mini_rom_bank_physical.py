"""Place, route and sign off one CPU firmware-ROM bank as a hard block.

Full ORFS flow (synthesis -> finish) at NUM_CORES=2 plus generate_abstract
(LEF + timing-model LIB used by the CPU top).  The bank uses met1-met4 only (power grid with met4
pins, signals up to met4), leaving met5 to the top-level power straps.  Acceptance: 10 ns setup/hold
closed with the block I/O budget below, zero DRC and antenna violations, and
physical VDD/VSS connectivity.  The block I/O budget is checked again by the
flat top-level STA (top + all bank netlists and parasitics).

No KLayout is installed: the final GDS merge is not part of the deliverable
(DEF, netlist, SDC, SPEF and logs are), so `finish` runs with GDS_FINAL_FILE
empty.  --resume completes a run that stopped only at that GDS step (or was
interrupted after routing): every input of the stopped run is re-verified
unchanged and make continues in the same flow variant, so finished stages are
not rerun.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.audit_student_mini_route import check_metrics

# Flow/tool locations and the metric reader, copied with identical values from scripts/run_student_mini_platform_physical.py
# (2026-10-14) so that a bank run no longer binds the platform runner: edits to that runner (GPU work) must not invalidate
# running or finished bank hardenings.  OPENROAD is the drt-batch build; without STUDENT_MINI_DRT_BATCH_SIZE in the
# environment its detailed router behaves exactly as the unpatched binary (patch default unchanged).
FLOW = Path('/home/soclab/src/orfs-clean-aabf2a/flow')
OPENROAD = Path('/home/soclab/.local/bin/openroad-drtbatch')
YOSYS = Path('/home/soclab/tools/oss-cad-suite/bin/yosys')


def last_metric(path, key):
    """OpenROAD JSON metric files can repeat keys; the final occurrence is the final value."""
    values = re.findall(r'"' + re.escape(key) + r'"\s*:\s*([-+0-9.eE]+|null)', path.read_text())
    if not values or values[-1] == 'null':
        return None
    return float(values[-1])

SIZE = 300
# met1/met4 power grid with met4 pins and signal routing up to met4: met5 stays free over the bank,
# where the CPU top-level met5 straps connect to the bank pins (an abstract with met5 power pins
# under a full met5 obstruction cannot be reached by the top grid: PSM-0039 on every bank).
PDN = ROOT / 'integration/student-mini/rom_bank_pdn.tcl'
INPUT_DELAY = 3.0
OUTPUT_DELAY = 5.0
SDC = f'''create_clock -name core_clock -period 10.000 [get_ports sys_clk]
set_input_delay {INPUT_DELAY} -clock core_clock [get_ports {{address[*]}}]
set_output_delay {OUTPUT_DELAY} -clock core_clock [get_ports {{data[*]}}]
set_load 0.03 [all_outputs]
'''
IO = 'set_io_pin_constraint -pin_names [concat [get_ports sys_clk] [get_ports {address[*]}] [get_ports {data[*]}]] -region bottom:*\n'


def resume_inputs(parent: Path):
    """Inputs of a stopped run that may be continued in place."""
    stopped = json.loads((parent / 'completion.json').read_text())
    if stopped['status'] != 'HOLD':
        raise ValueError('only a stopped (HOLD) run can be resumed')
    log = (parent / 'make.log').read_text(errors='replace')
    if not ('KLayout not found' in log or stopped['reason'].startswith('ValueError: bank input changed')):
        raise ValueError('resume is only for runs stopped at the GDS step: ' + stopped['reason'])
    scripts = ('run_student_mini_rom_bank_physical.py', 'run_student_mini_platform_physical.py')   # flow drivers, re-bound below
    changed = [p for p, v in stopped['bindings'].items() if Path(p).name not in scripts and sha(Path(p)) != v]
    if changed:
        raise ValueError('stopped run inputs changed: ' + changed[0])
    return stopped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary', type=Path, help='cpu-rom-banks-boundary directory')
    parser.add_argument('--bank', type=int)
    parser.add_argument('--resume', type=Path, help='work directory of a run stopped at the GDS step')
    parser.add_argument('--timeout', type=int, default=4 * 3600)
    args = parser.parse_args()
    started = time.monotonic()
    if args.resume:
        parent_run = args.resume.resolve()
        stopped = resume_inputs(parent_run)
        bindings = {k: v for k, v in stopped['bindings'].items()
                    if Path(k).name not in ('run_student_mini_rom_bank_physical.py', 'run_student_mini_platform_physical.py')}
        bindings[str(Path(__file__))] = sha(Path(__file__))
        bindings[str(parent_run / 'completion.json')] = sha(parent_run / 'completion.json')
        bank, name, variant = stopped['bank'], stopped['design'], stopped['variant']
        config = parent_run / 'config.mk'
        key = hashlib.sha256(json.dumps(dict(bindings=bindings, bank=bank, resume=str(parent_run)), sort_keys=True).encode()).hexdigest()
        work = ROOT / 'build/student-mini/rom-bank-physical' / key
        work.mkdir(parents=True, exist_ok=False)
    else:
        boundary = args.boundary.resolve()
        parent = json.loads((boundary / 'completion.json').read_text())
        if parent['status'] != 'CPU_ROM_BANKS_MAPPING_STAGE_PASS' or not 0 <= args.bank < parent['rom_banks']:
            raise ValueError('ROM-bank boundary and a valid bank index required')
        bank = args.bank
        name = f'student_mini_cpu_rom_bank_{bank:02d}'
        source = boundary / 'banks' / f'{name}.v'
        if parent['artifacts'].get(f'banks/{name}.v') != sha(source):
            raise ValueError('bank source changed')
        tools = [OPENROAD, YOSYS, FLOW / 'Makefile', FLOW / 'scripts/generate_abstract.tcl', FLOW / 'scripts/load.tcl', FLOW / 'platforms/sky130hd/config.mk',
                 FLOW / 'platforms/sky130hd/pdn.tcl']
        bindings = {str(p): sha(p) for p in [Path(__file__), ROOT / 'scripts/audit_student_mini_route.py',
                                              ROOT / 'integration/student-mini/audit_platform_route.tcl',
                                              boundary / 'completion.json', source, PDN, *tools]}
        key = hashlib.sha256(json.dumps(dict(bindings=bindings, bank=bank, size=SIZE), sort_keys=True).encode()).hexdigest()
        work = ROOT / 'build/student-mini/rom-bank-physical' / key
        work.mkdir(parents=True, exist_ok=False)
        (work / 'constraint.sdc').write_text(SDC)
        (work / 'io.tcl').write_text(IO)
        config = work / 'config.mk'
        config.write_text(f'''export PLATFORM = sky130hd
export DESIGN_NAME = {name}
export VERILOG_FILES = {source}
export SDC_FILE = {work / "constraint.sdc"}
export DIE_AREA = 0 0 {SIZE} {SIZE}
export CORE_AREA = 10 10 {SIZE - 10} {SIZE - 10}
export PLACE_DENSITY = 0.3
export IO_CONSTRAINTS = {work / "io.tcl"}
export SYNTH_MEMORY_MAX_BITS = 500000
export NUM_CORES = 2
export PDN_TCL = {PDN}
export MAX_ROUTING_LAYER = met4
''')
        for path in (config, work / 'constraint.sdc', work / 'io.tcl'):
            bindings[str(path)] = sha(path)
        variant = f'student-mini-rom-bank-{key[:16]}'
    results = FLOW / 'results/sky130hd' / name / variant
    logs = FLOW / 'logs/sky130hd' / name / variant
    result = dict(status='HOLD', bank=bank, design=name, bindings=bindings, variant=variant, clock_period_ns=10,
                  io_budget=dict(input_delay_ns=INPUT_DELAY, output_delay_ns=OUTPUT_DELAY), threads=2,
                  result_directory=str(results), metrics_directory=str(logs), formal_baseline=False,
                  resumed_from=str(args.resume.resolve()) if args.resume else None, gds='not generated (KLayout not installed)')
    (work / 'inputs.json').write_text(json.dumps(result, indent=2) + '\n')
    try:
        command = ['make', '-C', str(FLOW), f'DESIGN_CONFIG={config}', f'FLOW_VARIANT={variant}', 'NUM_CORES=2',
                   f'OPENROAD_EXE={OPENROAD}', f'YOSYS_EXE={YOSYS}', 'GDS_FINAL_FILE=', 'finish', 'do-generate_abstract']
        with (work / 'make.log').open('x') as log:
            code = subprocess.call(command, cwd=FLOW, stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout)
        result['make_exit_code'] = code
        if code:
            raise RuntimeError('ORFS flow failed; see make.log')
        changed = [p for p, v in bindings.items() if sha(Path(p)) != v]
        if changed:
            raise ValueError('bank input changed during the run: ' + ', '.join(changed))
        detailed = {k: int(last_metric(logs / '5_2_route.json', k)) for k in
                    ('detailedroute__route__drc_errors', 'detailedroute__antenna__violating__nets',
                     'detailedroute__antenna__violating__pins')}
        result['route_metrics'] = check_metrics(detailed, {'finish__timing__setup__ws': last_metric(logs / '6_report.json', 'finish__timing__setup__ws')},
                                                (results / '6_final.sdc').read_text())
        hold = last_metric(logs / '6_report.json', 'finish__timing__hold__ws')
        if hold is None or not math.isfinite(hold) or hold < 0:
            raise ValueError('hold timing not closed')
        result['route_metrics']['hold_wns_ns'] = hold
        audit_log = work / 'audit.log'
        with audit_log.open('x') as log:
            subprocess.call([str(OPENROAD), '-exit', str(ROOT / 'integration/student-mini/audit_platform_route.tcl')],
                            env={'STUDENT_MINI_ROUTE_ODB': str(results / '6_final.odb'), 'PATH': '/usr/bin:/bin'},
                            stdout=log, stderr=subprocess.STDOUT)
        pdn = dict(re.findall(r'^PLATFORM_AUDIT_PDN net=(\w+) status=(\w+)', audit_log.read_text(errors='replace'), re.M))
        if pdn != {'VDD': 'PASS', 'VSS': 'PASS'}:
            raise ValueError('power-grid connectivity failed')
        abstract = {'lef': results / f'{name}.lef', 'lib': results / f'{name}_typ.lib'}
        if not all(p.is_file() and p.stat().st_size for p in abstract.values()):
            raise ValueError('abstract views missing')
        if 'LAYER met5' in abstract['lef'].read_text():
            raise ValueError('bank abstract uses met5 (pins or obstruction): the top-level straps could not reach it')
        result['abstract'] = {k: str(v) for k, v in abstract.items()}
        result['artifacts'] = {str(p): sha(p) for p in [*(results / ('6_final.' + s) for s in ('def', 'v', 'sdc', 'spef', 'odb')),
                                                      *abstract.values(), logs / '5_2_route.json', logs / '6_report.json',
                                                      work / 'make.log', audit_log]}
        result.update(status='ROM_BANK_PHYSICAL_STAGE_PASS', power_grid=pdn,
                      reason='Bank closed at 10 ns with its I/O budget, DRC/antenna zero, PDN connected; abstract generated')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic() - started
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), bank=bank, status=result['status'], reason=result['reason'],
                          metrics=result.get('route_metrics'))), flush=True)
    return 0 if result['status'] == 'ROM_BANK_PHYSICAL_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
