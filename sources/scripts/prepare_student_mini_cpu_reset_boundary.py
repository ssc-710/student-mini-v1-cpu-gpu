"""Expose ASIC reset without pretending FPGA-style init is an ASIC reset.

Exact structural projection only. Cold-start equivalence under a declared
external reset waveform, reset recovery and SRAM mapping remain separate gates.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha

TOP = 'cpu_student_mini_physical_top'
RESET = 'build_soc_coursesimsoc_int_rst'


def project_reset(source):
    pattern = rf'(?m)^module {TOP}\((.*?)\);'
    headers = list(re.finditer(pattern, source, re.S))
    if len(headers) != 1: raise ValueError('ambiguous CPU physical boundary')
    start = headers[0].start()
    end_match = re.search(r'(?m)^endmodule\s*$', source[headers[0].end():])
    if not end_match: raise ValueError('unterminated CPU physical boundary')
    end = headers[0].end()+end_match.end()
    original = source[start:end]
    if 'asic_reset_i' in original: raise ValueError('ASIC reset port already exists')
    changed, count = re.subn(rf'(?m)^  reg {RESET} = 1\'h1;$',
        f'  wire {RESET};\n  input asic_reset_i;\n  wire asic_reset_i;', original)
    if count != 1: raise ValueError('power-on reset initialization differs')
    changed, count = re.subn(rf'(?m)^  always @\(posedge sys_clk\)\n    {RESET} <= 1\'h0;$',
        f'  assign {RESET} = asic_reset_i;', changed)
    if count != 1: raise ValueError('power-on reset driver differs')
    changed = changed.replace('module '+TOP+'(', 'module '+TOP+'_asic(asic_reset_i, ', 1)
    # Any other write to this reset net invalidates the projection contract.
    if re.search(rf'\b{RESET}\s*<=', changed): raise ValueError('additional internal reset driver')
    return source[:start]+changed+source[end:]


def memory_inventory(design):
    top = design['modules'][TOP+'_asic']
    reset = top['ports'].get('asic_reset_i')
    if not reset or reset['direction'] != 'input' or len(reset['bits']) != 1:
        raise ValueError('external ASIC reset input missing')
    rows = []
    for name, cell in top['cells'].items():
        if cell['type'] not in ('$mem', '$mem_v2'): continue
        values = cell['parameters']
        number = lambda key: int(values[key], 2)
        row = dict(name=name, width=number('WIDTH'), depth=number('SIZE'),
            read_ports=number('RD_PORTS'), write_ports=number('WR_PORTS'),
            read_clock_enable=number('RD_CLK_ENABLE'), read_clock_polarity=number('RD_CLK_POLARITY'),
            write_clock_enable=number('WR_CLK_ENABLE'), write_clock_polarity=number('WR_CLK_POLARITY'),
            read_transparency=number('RD_TRANSPARENCY_MASK') if 'RD_TRANSPARENCY_MASK' in values else None,
            initialized_bits=sum(bit in '01' for bit in values['INIT']))
        if row['depth'] >= 4194304: raise ValueError('external SDRAM model was reintroduced')
        rows.append(row)
    if not rows: raise ValueError('CPU local memories missing')
    return rows


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary', type=Path, required=True)
    args = parser.parse_args()
    boundary = args.boundary.resolve()
    parent_path = boundary/'completion.json'
    parent = json.loads(parent_path.read_text())
    rtl = boundary/'boundary.v'
    if parent.get('extraction_complete') is not True or parent['artifacts'].get('boundary.v') != sha(rtl):
        raise ValueError('source CPU boundary not qualified')
    yosys = Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    bindings = dict(parent['bindings'])
    bindings.update({str(p): sha(p) for p in (parent_path, rtl, Path(__file__), yosys)})
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-reset-boundary'/identity
    work.mkdir(parents=True, exist_ok=False)
    (work/'cpu-asic.v').write_text(project_reset(rtl.read_text()))
    script = work/'memory-inventory.ys'
    script.write_text(f'read_verilog -sv {work}/cpu-asic.v\nhierarchy -check -top {TOP}_asic\nproc\nflatten\nmemory_dff\nmemory_collect\nopt_clean\ncheck -assert\nwrite_json {work}/memories.json\n')
    result = dict(status='HOLD', physical_evidence_complete=False, reset_equivalence=False,
        boundary_complete=False, bindings=bindings,
        reset_contract='Active-high external reset, synchronous to sys_clk; original cold-start pulse was high before the first rising edge then low. Full recovery proof is pending.')
    started = time.monotonic()
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work), stage='WAITING_FOR_SERIAL_QUEUE')), flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if any(sha(Path(p)) != value for p, value in bindings.items()): raise ValueError('source changed while queued')
            with (work/'yosys.log').open('x') as log:
                code = subprocess.run([str(yosys), '-Q', '-T', '-s', str(script)], cwd=ROOT,
                    stdout=log, stderr=subprocess.STDOUT, timeout=600).returncode
            if code: raise RuntimeError('ASIC reset/memory elaboration failed')
            result['memories'] = memory_inventory(json.loads((work/'memories.json').read_text()))
            if any(sha(Path(p)) != value for p, value in bindings.items()): raise ValueError('source changed during elaboration')
            result.update(boundary_complete=True,
                reason='External reset entry elaborates and storage semantics inventoried; same-ROM full session, reset/DFI equivalence, SRAM mapping and physical signoff remain required')
    except Exception as error: result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic()-started
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), boundary_complete=result['boundary_complete'], reason=result['reason'])), flush=True)
    return 0 if result['boundary_complete'] else 1


if __name__ == '__main__': raise SystemExit(main())
