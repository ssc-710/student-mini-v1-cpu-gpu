"""Split the firmware ROM block into 25 per-bank hard-block modules.

``student_mini_cpu_rom_block`` keeps its ports, its registered bank selector
and its combinational output selector; each 512-word bank becomes a separate
module ``student_mini_cpu_rom_bank_NN`` (address[8:0] -> registered data[31:0])
holding exactly that bank's words.  Words beyond the 12558-word image (only in
bank 24) are 0, the value the reference LiteX ROM holds there; the original
mapped netlist left them undefined.  Behaviour for every defined address is
unchanged.  Each bank is later placed and routed as its own hard macro.
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
BANKS = 25
WORDS = 512


def bank_module(index, words):
    lines = [f'// Firmware ROM bank {index}: words {index * WORDS}..{index * WORDS + WORDS - 1}.',
             f'module student_mini_cpu_rom_bank_{index:02d} (',
             '  input wire sys_clk,', '  input wire [8:0] address,', '  output reg [31:0] data', ');',
             f'  reg [31:0] rom [0:{WORDS - 1}];', '  initial begin']
    lines += [f"    rom[{i}] = 32'd{word};" for i, word in enumerate(words)]
    lines += ['  end', '  always @(posedge sys_clk) data <= rom[address];', 'endmodule', '']
    return '\n'.join(lines)


def wrapper():
    lines = [f'// Firmware ROM: 25 hard-block banks + registered bank selector + output selector.',
             f'module {BLOCK} (', '  input wire sys_clk,', '  input wire [14:0] mini_rom_request_address,',
             '  output wire [31:0] build_soc_coursesimsoc_coursesimsoc_dat_r', ');',
             f'  wire [31:0] mini_rom_bank_data [0:{BANKS - 1}];', '  reg [5:0] mini_rom_bank_q;']
    for index in range(BANKS):
        lines.append(f'  student_mini_cpu_rom_bank_{index:02d} bank_{index:02d} (.sys_clk(sys_clk), '
                     f'.address(mini_rom_request_address[8:0]), .data(mini_rom_bank_data[{index}]));')
    lines += ['  always @(posedge sys_clk) mini_rom_bank_q <= mini_rom_request_address[14:9];',
              '  assign build_soc_coursesimsoc_coursesimsoc_dat_r = mini_rom_bank_data[mini_rom_bank_q];', 'endmodule', '']
    return '\n'.join(lines)


def transform(text):
    match = re.search(r'// Firmware ROM hard block: moved verbatim from ' + TOP + r'\.\nmodule ' + BLOCK + r' \(.*?\nendmodule\n', text, re.S)
    if not match:
        raise ValueError('ROM-block module not found')
    block = match.group(0)
    values = {int(a): int(b) for a, b in re.findall(r"rom\[(\d+)\] = 32'd(\d+);", block)}
    if sorted(values) != list(range(12558)):
        raise ValueError('expected the complete 12558-word image')
    seam = ('  always @(posedge sys_clk) mini_rom_bank_q <= mini_rom_request_address[14:9];\n'
            '  assign build_soc_coursesimsoc_coursesimsoc_dat_r = mini_rom_bank_data[mini_rom_bank_q];\n')
    if block.count(seam) != 1 or block.count('rom[mini_rom_bank*512 + mini_rom_request_address[8:0]]') != 1:
        raise ValueError('ROM block structure changed')
    banks = []
    for index in range(BANKS):
        words = [values.get(index * WORDS + i, 0) for i in range(WORDS)]
        banks.append(bank_module(index, words))
    replacement = wrapper() + '\n' + '\n'.join(banks)
    return text.replace(block, replacement, 1), banks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', type=Path, required=True, help='ROM-block boundary directory')
    args = parser.parse_args()
    mapping = args.mapping.resolve()
    parent = json.loads((mapping / 'completion.json').read_text())
    if parent['status'] != 'CPU_ROM_BLOCK_MAPPING_STAGE_PASS':
        raise ValueError('ROM-block boundary required')
    verify(parent['bindings'])
    for name in ('mapped.v', 'mapped.json'):
        if parent['artifacts'].get(name) != sha(mapping / name):
            raise ValueError('parent artifact changed: ' + name)
    yosys = Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    macro = ROOT / 'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'
    paths = [Path(__file__), mapping / 'completion.json', mapping / 'mapped.v', mapping / 'mapped.json', yosys, macro]
    bindings = {str(p): sha(p) for p in paths}
    bindings.update(parent['bindings'])
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/cpu-rom-banks-boundary' / key
    (work / 'banks').mkdir(parents=True, exist_ok=False)
    text, banks = transform((mapping / 'mapped.v').read_text())
    (work / 'mapped.v').write_text(text)
    for index, module in enumerate(banks):
        (work / 'banks' / f'student_mini_cpu_rom_bank_{index:02d}.v').write_text(module)
    script = work / 'structure.ys'
    script.write_text(f'read_verilog -sv {work / "mapped.v"}\nread_verilog -lib {macro}\n'
                      f'hierarchy -check -top {TOP}\nproc\nwrite_json {work / "mapped.json"}\nstat\n')
    with (work / 'yosys.log').open('x') as log:
        if subprocess.call([str(yosys), '-q', '-s', str(script)], stdout=log, stderr=subprocess.STDOUT):
            raise RuntimeError('ROM-bank boundary does not elaborate')
    design = json.loads((work / 'mapped.json').read_text())
    old = json.loads((mapping / 'mapped.json').read_text())
    if design['modules'][TOP]['ports'] != old['modules'][TOP]['ports'] or design['modules'][BLOCK]['ports'] != old['modules'][BLOCK]['ports']:
        raise ValueError('ports changed')
    if sum(c['type'].startswith('student_mini_cpu_rom_bank_') for c in design['modules'][BLOCK]['cells'].values()) != BANKS:
        raise ValueError('unexpected ROM bank hierarchy')
    verify(bindings)
    result = dict(parent, status='CPU_ROM_BANKS_MAPPING_STAGE_PASS', bindings=bindings, parent_mapping=str(mapping),
                  macro_count=12, rom_banks=BANKS, rom_words=12558, rom_fill_beyond_image=0,
                  formal_baseline=False, physical_evidence_complete=False,
                  reason='ROM split into 25 per-bank hard-block modules; complete replay and physical signoff still required')
    result.pop('elapsed_seconds', None)
    result['artifacts'] = {p.relative_to(work).as_posix(): sha(p) for p in work.rglob('*') if p.is_file()}
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'])))


if __name__ == '__main__':
    main()
