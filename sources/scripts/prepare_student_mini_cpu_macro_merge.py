"""Pack byte-grain CPU memories into shared 32-bit SRAM macros (29 -> 12 macros).

Purely structural re-mapping of an already proved DFI-aligned boundary:

* the 16 L2 ``data_mem_grain*`` byte lanes share one read/write address, so
  each group of four becomes one byte-masked 32x1024 macro;
* the 4 D-cache ``ways_0_data_symbol*`` lanes share the read address/enable and
  write the same ``dataWriteCmd_payload_address`` whenever enabled, so they
  become one byte-masked macro whose write address is selected by the active
  lane enable;
* the two 16x10 UART FIFOs move from 4 KiB macros to an RTL register array with
  the identical synchronous-read wrapper.

No VexRiscv/LiteX logic, ROM, register file, tag or SRAM behavior changes.
The result is not accepted until a fresh complete replay, synthesis and
physical signoff pass.
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

CELL = 'student_mini_cpu_sram_32x1024'
FLOP = 'student_mini_cpu_flop_fifo_ram_16x10'
INSTANCE = re.compile(r'  ' + CELL + r' \\(\S+)  \(\n((?:    \.[a-z_]+\(.*\),?\n)+)  \);\n')
PORT = re.compile(r'    \.([a-z_]+)\((.*?)\),?$')

FLOP_MODULE = f'''
// Register-array replacement for a 16x10 FIFO that previously occupied a
// whole 32x1024 macro.  Same ports and the same read_live/held_data wrapper
// as {CELL}; same-cycle collision returns old data (the macro is undefined).
module {FLOP}(clk, write_address, read_address, write_data, write_enable, read_enable, read_data);
  input clk;
  input [9:0] write_address;
  input [9:0] read_address;
  input [31:0] write_data;
  input [3:0] write_enable;
  input read_enable;
  output [31:0] read_data;
  reg [9:0] storage [0:15];
  reg [9:0] macro_data;
  reg [31:0] held_data;
  reg read_live;
  wire [31:0] live_data = {{22'h000000, macro_data}};
  always @(posedge clk) begin
    if (write_enable[0]) storage[write_address[3:0]] <= write_data[9:0];
    if (read_enable) macro_data <= storage[read_address[3:0]];
    read_live <= read_enable;
    held_data <= read_live ? live_data : held_data;
  end
  assign read_data = read_live ? live_data : held_data;
endmodule
'''


def parse(text):
    found = {}
    for match in INSTANCE.finditer(text):
        ports = {}
        for line in match.group(2).splitlines():
            port = PORT.match(line)
            if not port:
                raise ValueError('unexpected macro port line: ' + line)
            ports[port.group(1)] = port.group(2)
        if set(ports) != {'clk', 'read_address', 'read_data', 'read_enable', 'write_address', 'write_data', 'write_enable'}:
            raise ValueError('unexpected macro ports: ' + match.group(1))
        found[match.group(1)] = dict(span=match.span(), ports=ports)
    if len(found) != 29:
        raise ValueError(f'expected 29 mapped macros, found {len(found)}')
    return found


def byte_lane(ports, name):
    """Return (write data byte, write enable bit, read data byte) of an 8-bit lane."""
    data = re.fullmatch(r"\{ 24'hxxxxxx, (\S+) \}", ports['write_data'])
    enable = re.fullmatch(r"\{ 3'h0, (\S+) \}", ports['write_enable'])
    read = re.fullmatch(r'\{ (\S+)\[31:8\], (\S+) \}', ports['read_data'])
    if not (data and enable and read):
        raise ValueError('not an 8-bit byte lane: ' + name)
    return data.group(1), enable.group(1), read.group(2)


def instance(name, ports):
    order = ('clk', 'read_address', 'read_data', 'read_enable', 'write_address', 'write_data', 'write_enable')
    body = ',\n'.join(f'    .{key}({ports[key]})' for key in order)
    return f'  {CELL} \\{name}  (\n{body}\n  );\n'


def transform(text):
    found = parse(text)
    replacements = {}
    added = []
    # L2 data memory: 16 byte grains with one shared address -> 4 macros.
    grains = [f'data_mem_grain{i}.0.0' for i in range(16)]
    shared = {key: found[grains[0]]['ports'][key] for key in ('clk', 'read_address', 'read_enable', 'write_address')}
    for name in grains:
        if any(found[name]['ports'][key] != value for key, value in shared.items()):
            raise ValueError('L2 grains do not share address/enable/clock: ' + name)
    for quad in range(4):
        lanes = [byte_lane(found[grains[4*quad+k]]['ports'], grains[4*quad+k]) for k in range(4)]
        ports = dict(shared,
                     write_data='{ ' + ', '.join(l[0] for l in reversed(lanes)) + ' }',
                     write_enable='{ ' + ', '.join(l[1] for l in reversed(lanes)) + ' }',
                     read_data='{ ' + ', '.join(l[2] for l in reversed(lanes)) + ' }')
        replacements[grains[4*quad]] = instance(f'data_mem_quad{quad}.0.0', ports)
        for k in range(1, 4):
            replacements[grains[4*quad+k]] = ''
        added.append(f'data_mem_quad{quad}.0.0')
    # D-cache data: 4 symbols, shared read side, enable-selected write address.
    symbols = [f'VexRiscv.dataCache_1.ways_0_data_symbol{i}.0.0' for i in range(4)]
    shared = {key: found[symbols[0]]['ports'][key] for key in ('clk', 'read_address', 'read_enable')}
    for name in symbols:
        if any(found[name]['ports'][key] != value for key, value in shared.items()):
            raise ValueError('D-cache symbols do not share read side: ' + name)
    lanes = [byte_lane(found[name]['ports'], name) for name in symbols]
    addresses = [found[name]['ports']['write_address'] for name in symbols]
    select = 'student_mini_dcache_merged_write_address'
    mux = addresses[3]
    for lane, address in reversed(list(zip(lanes[:3], addresses[:3]))):
        mux = f'{lane[1]} ? {address} : {mux}'
    ports = dict(shared, write_address=select,
                 write_data='{ ' + ', '.join(l[0] for l in reversed(lanes)) + ' }',
                 write_enable='{ ' + ', '.join(l[1] for l in reversed(lanes)) + ' }',
                 read_data='{ ' + ', '.join(l[2] for l in reversed(lanes)) + ' }')
    replacements[symbols[0]] = (f'  wire [9:0] {select};\n  assign {select} = {mux};\n'
                                + instance('VexRiscv.dataCache_1.ways_0_data_merged.0.0', ports))
    for name in symbols[1:]:
        replacements[name] = ''
    added.append('VexRiscv.dataCache_1.ways_0_data_merged.0.0')
    # UART FIFOs: 16x10 -> register array with the same wrapper semantics.
    for name in ('storage.0.0', 'storage_1.0.0'):
        ports = found[name]['ports']
        if (not re.fullmatch(r"\{ 6'h00, \S+ \}", ports['read_address'])
                or not re.fullmatch(r"\{ 6'h00, \S+ \}", ports['write_address'])
                or not re.fullmatch(r"\{ 22'hxxxxxx, \S+ \}", ports['write_data'])
                or not re.fullmatch(r"\{ 2'h0, (\S+), \1 \}", ports['write_enable'])
                or not re.fullmatch(r'\{ \S+\[31:10\], \S+ \}', ports['read_data'])):
            raise ValueError('UART FIFO is not a 16x10 lane: ' + name)
        replacements[name] = instance(name, ports).replace(f'  {CELL} ', f'  {FLOP} ', 1)
    out = []
    cursor = 0
    for name, entry in sorted(found.items(), key=lambda item: item[1]['span'][0]):
        start, end = entry['span']
        out.append(text[cursor:start])
        out.append(replacements.get(name, text[start:end]))
        cursor = end
    out.append(text[cursor:])
    result = ''.join(out)
    marker = f'module {CELL}('
    if result.count(marker) != 1:
        raise ValueError('macro wrapper module not unique')
    result = result.replace(marker, FLOP_MODULE.lstrip('\n') + '\n' + marker)
    kept = [name for name in found if name not in replacements or replacements[name].startswith(f'  {CELL} \\{name} ')]
    macros = sorted(set(kept) | set(added))
    if len(macros) != 12 or len(re.findall(r'^  ' + CELL + r' \\', result, re.M)) != 12:
        raise ValueError('expected exactly 12 macro instances after packing')
    return result, macros


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', type=Path, required=True, help='proved DFI-aligned boundary directory')
    args = parser.parse_args()
    mapping = args.mapping.resolve()
    parent = json.loads((mapping / 'completion.json').read_text())
    if parent['status'] != 'CPU_DFI_OUTPUT_MAPPING_STAGE_PASS' or parent.get('macro_count') != 29:
        raise ValueError('proved 29-macro DFI-aligned boundary required')
    verify(parent['bindings'])
    for name in ('mapped.v', 'mapped.json'):
        if parent['artifacts'].get(name) != sha(mapping / name):
            raise ValueError('parent artifact changed: ' + name)
    yosys = Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    macro = ROOT / 'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'
    paths = [Path(__file__), ROOT / 'scripts/student_mini.py', ROOT / 'scripts/retry_student_mini_route.py',
             mapping / 'completion.json', mapping / 'mapped.v', mapping / 'mapped.json', yosys, macro]
    bindings = {str(p): sha(p) for p in paths}
    bindings.update(parent['bindings'])
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/cpu-macro-merge-boundary' / key
    work.mkdir(parents=True, exist_ok=False)
    text, macros = transform((mapping / 'mapped.v').read_text())
    (work / 'mapped.v').write_text(text)
    script = work / 'structure.ys'
    script.write_text(f'read_verilog -sv {work / "mapped.v"}\nread_verilog -lib {macro}\n'
                      f'hierarchy -check -top cpu_student_mini_physical_top_asic\nproc\n'
                      f'write_json {work / "mapped.json"}\nstat\n')
    with (work / 'yosys.log').open('x') as log:
        code = subprocess.call([str(yosys), '-q', '-s', str(script)], stdout=log, stderr=subprocess.STDOUT)
    if code:
        raise RuntimeError('packed boundary does not elaborate')
    design = json.loads((work / 'mapped.json').read_text())
    top = design['modules']['cpu_student_mini_physical_top_asic']
    old = json.loads((mapping / 'mapped.json').read_text())['modules']['cpu_student_mini_physical_top_asic']
    if top['ports'] != old['ports']:
        raise ValueError('top-level ports changed')
    counted = sum(1 for cell in top['cells'].values() if cell['type'] == CELL)
    if counted != 12:
        raise ValueError(f'elaborated macro count {counted} != 12')
    verify(bindings)
    result = dict(parent, status='CPU_MACRO_PACKED_MAPPING_STAGE_PASS', bindings=bindings,
                  parent_mapping=str(mapping), macro_count=12, macro_instances=macros,
                  packing=dict(l2_grains_per_macro=4, dcache_symbols_per_macro=4, uart_fifo='register-array'),
                  formal_baseline=False, physical_evidence_complete=False, whole_core_equivalence=False,
                  reason='Structural byte-lane packing of shared-address memories; complete replay and physical signoff still required')
    result.pop('elapsed_seconds', None)
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], macro_count=12)))


if __name__ == '__main__':
    main()
