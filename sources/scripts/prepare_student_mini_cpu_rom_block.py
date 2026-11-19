"""Move the CPU boot/firmware ROM into its own hard-block module (hierarchical PnR).

The ROM table, its 25 registered 512-word banks, the registered bank selector
and the combinational output selector are moved verbatim from the top module
into ``student_mini_cpu_rom_block``; the top instantiates it on the same nets.
No contents, latency, reset or bus behaviour change.  The packed 12-macro
boundary is the parent.  Acceptance still requires a fresh complete replay.
"""
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

TOP = 'cpu_student_mini_physical_top_asic'
BLOCK = 'student_mini_cpu_rom_block'
ROM_DECL = re.compile(r'  reg \[31:0\] rom \[(\d+):0\];\n  initial begin\n(?:    rom\[\d+\] = 32\'d\d+;\n)+  end\n')
CUT = '''  // Timing foundation: one-cycle read, exact original ROM contents.
  // Capture each 512-word bank and its selector at the same clock edge.
  reg [31:0] mini_rom_bank_data [0:24];
  reg [5:0] mini_rom_bank_q;
  genvar mini_rom_bank;
  generate for (mini_rom_bank=0; mini_rom_bank<25; mini_rom_bank=mini_rom_bank+1) begin : g_mini_rom_cut
    always @(posedge sys_clk)
      mini_rom_bank_data[mini_rom_bank] <= rom[mini_rom_bank*512 + mini_rom_request_address[8:0]];
  end endgenerate
  always @(posedge sys_clk) mini_rom_bank_q <= mini_rom_request_address[14:9];
  assign build_soc_coursesimsoc_coursesimsoc_dat_r = mini_rom_bank_data[mini_rom_bank_q];
'''
INSTANCE = f'''  // Hierarchical hard block: firmware ROM (identical contents and timing).
  {BLOCK} mini_rom (
    .sys_clk(sys_clk), .mini_rom_request_address(mini_rom_request_address),
    .build_soc_coursesimsoc_coursesimsoc_dat_r(build_soc_coursesimsoc_coursesimsoc_dat_r)
  );
'''


def transform(text):
    declarations = list(ROM_DECL.finditer(text))
    if len(declarations) != 1 or int(declarations[0].group(1)) != 12557:
        raise ValueError('expected exactly one 12558-word ROM table')
    if text.count(CUT) != 1:
        raise ValueError('ROM bank/selector seam changed')
    table = declarations[0].group(0)
    if text.index(table) > text.index(CUT):
        raise ValueError('ROM table must precede its banks')
    body = text.replace(table, '', 1).replace(CUT, INSTANCE, 1)
    module = (f'// Firmware ROM hard block: moved verbatim from {TOP}.\n'
              f'module {BLOCK} (\n  input wire sys_clk,\n  input wire [14:0] mini_rom_request_address,\n'
              f'  output wire [31:0] build_soc_coursesimsoc_coursesimsoc_dat_r\n);\n' + table + CUT + 'endmodule\n')
    marker = 'module student_mini_cpu_rom_request_cut ('
    if body.count(marker) != 1:
        raise ValueError('ROM request module seam changed')
    return body.replace(marker, module + '\n' + marker, 1), module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', type=Path, required=True, help='packed 12-macro boundary')
    args = parser.parse_args()
    mapping = args.mapping.resolve()
    parent = json.loads((mapping / 'completion.json').read_text())
    if parent['status'] != 'CPU_MACRO_PACKED_MAPPING_STAGE_PASS' or parent.get('macro_count') != 12:
        raise ValueError('packed 12-macro boundary required')
    verify(parent['bindings'])
    for name in ('mapped.v', 'mapped.json'):
        if parent['artifacts'].get(name) != sha(mapping / name):
            raise ValueError('parent artifact changed: ' + name)
    yosys = Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    macro = ROOT / 'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'
    paths = [Path(__file__), ROOT / 'scripts/student_mini.py', mapping / 'completion.json', mapping / 'mapped.v',
             mapping / 'mapped.json', yosys, macro]
    bindings = {str(p): sha(p) for p in paths}
    bindings.update(parent['bindings'])
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/cpu-rom-block-boundary' / key
    work.mkdir(parents=True, exist_ok=False)
    text, module = transform((mapping / 'mapped.v').read_text())
    (work / 'mapped.v').write_text(text)
    (work / 'rom_block.v').write_text(module)
    script = work / 'structure.ys'
    script.write_text(f'read_verilog -sv {work / "mapped.v"}\nread_verilog -lib {macro}\n'
                      f'hierarchy -check -top {TOP}\nproc\nwrite_json {work / "mapped.json"}\nstat\n')
    with (work / 'yosys.log').open('x') as log:
        if subprocess.call([str(yosys), '-q', '-s', str(script)], stdout=log, stderr=subprocess.STDOUT):
            raise RuntimeError('ROM-block boundary does not elaborate')
    design = json.loads((work / 'mapped.json').read_text())
    old = json.loads((mapping / 'mapped.json').read_text())
    if design['modules'][TOP]['ports'] != old['modules'][TOP]['ports']:
        raise ValueError('top-level ports changed')
    cells = design['modules'][TOP]['cells'].values()
    if sum(c['type'] == BLOCK for c in cells) != 1 or sum(c['type'] == 'student_mini_cpu_sram_32x1024' for c in cells) != 12:
        raise ValueError('unexpected hierarchy after the ROM move')
    verify(bindings)
    result = dict(parent, status='CPU_ROM_BLOCK_MAPPING_STAGE_PASS', bindings=bindings, parent_mapping=str(mapping),
                  macro_count=12, rom_block=BLOCK, formal_baseline=False, physical_evidence_complete=False,
                  reason='Firmware ROM moved verbatim into a hard-block module; complete replay and physical signoff still required')
    result.pop('elapsed_seconds', None)
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'])))


if __name__ == '__main__':
    main()
