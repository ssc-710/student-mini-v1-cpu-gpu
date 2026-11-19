"""Write the CPU top-level physical configuration (12 SRAM + 25 ROM-bank hard macros).

Inputs: the replay-qualified ROM-bank boundary and the 25 passing bank
hard-block runs (their abstract LEF / timing LIB).  Output: a directory with
config.mk, macro-placement.tcl and the blackbox stubs, consumed by
scripts/run_student_mini_platform_physical.py.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha

SRAM = 'vortex_sp_32x1024_w4'
SRAM_W, SRAM_H = 700.26, 661.19
BANK = 300.0
DIE_W, DIE_H = 5200, 4600
EDGE = 420.0          # wide strips: each SRAM row also has write-port pins facing the die edge
GAP = 150.0
SIDE = 170.0          # left/right margin of the SRAM rows
PHASE = (60.25, 78.76)  # common M3/M4 routing-grid phase of macro origins (15.64 um quantum)
QUANTUM = 15.64
# Bottom row raised three quanta (y 422.84 -> 469.76): the SRAM pins reach 20 um into the macro, and
# global routing reaches a pin only through the GCell (6.9 um grid from the die origin) on the macro
# edge.  At y 422.84 the read-pin edge (top, 1084.03) entered that GCell by 0.73 um and the pins sat
# in a fully blocked GCell (capacity 0, GRT-0116).  At 469.76 both edges hold >= 6.25 um of pin in
# the edge GCell, as for the top row (which routes).
EDGE_BOTTOM = 466.0
TOP_ROW = ['VexRiscv.IBusCachedPlugin_cache.banks_0.0.0.storage', 'VexRiscv.IBusCachedPlugin_cache.ways_0_tags.0.0.storage',
           'VexRiscv.RegFilePlugin_regFile.0.0.storage', 'VexRiscv.RegFilePlugin_regFile.1.0.storage',
           'VexRiscv.dataCache_1.ways_0_data_merged.0.0.storage', 'VexRiscv.dataCache_1.ways_0_tags.0.0.storage']
BOTTOM_ROW = ['sram.0.0.storage', 'sram.0.1.storage', 'data_mem_quad0.0.0.storage', 'data_mem_quad1.0.0.storage',
              'data_mem_quad2.0.0.storage', 'data_mem_quad3.0.0.storage']


def snap(value, origin):
    return origin + -(-(value - origin) // QUANTUM) * QUANTUM


def placement_tcl():
    lines = ['# 12 SRAM macros in two rows (read pins facing the logic band) and 25 ROM banks',
             '# in a 5x5 cluster inside the band, pins on each bank\'s bottom edge.',
             'set expected {}', 'set found {}',
             'foreach inst [[ord::get_db_block] getInsts] {',
             '  if {[[$inst getMaster] getType] eq "BLOCK"} { lappend found [$inst getName] }', '}']
    places = []
    for i, name in enumerate(BOTTOM_ROW):
        places.append((name, snap(SIDE + i * (SRAM_W + GAP), PHASE[0]), snap(EDGE_BOTTOM, PHASE[1]), 'R0'))
    for i, name in enumerate(TOP_ROW):
        places.append((name, snap(SIDE + i * (SRAM_W + GAP), PHASE[0]), snap(DIE_H - EDGE - SRAM_H, PHASE[1]), 'MX'))
    # Bank rows on the y = 1091 + 390 k lattice (with x = 400 + 390 k) where every bank's power
    # pins meet the top-level macro-grid straps; first row above the bottom SRAM strip.
    band_low = 1091.0 + 390.0
    for b in range(25):
        row, col = divmod(b, 5)
        # Bank columns at x = 400 + 390 k: the bank power pins then meet the top macro-grid straps.
        places.append((f'mini_rom.bank_{b:02d}', 400.0 + col * (BANK + 90.0), band_low + row * (BANK + 90.0), 'R0'))
    for name, x, y, orient in places:
        lines.append(f'lappend expected {{{name}}}')
    lines.append('if {[lsort $found] ne [lsort $expected]} { error "macro set differs: $found" }')
    for name, x, y, orient in places:
        lines.append(f'place_macro -macro_name {{{name}}} -location [list {x:.2f} {y:.2f}] -orientation {orient}')
    return '\n'.join(lines) + '\n', len(places)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True, help='passing ROM-bank full replay launch directory')
    parser.add_argument('--banks', type=Path, nargs=25, required=True, help='the 25 passing bank physical work directories, in order')
    args = parser.parse_args()
    replay = json.loads((args.replay.resolve() / 'completion.json').read_text())
    if replay['status'] != 'CPU_ROM_BANKS_FULL_REPLAY_STAGE_PASS':
        raise ValueError('passing complete ROM-bank replay required')
    mapping = Path(replay['replay']['work'])
    child = json.loads((mapping / 'completion.json').read_text())
    boundary = Path(child['parent_mapping'])
    parent = json.loads((boundary / 'completion.json').read_text())
    if parent['status'] != 'CPU_ROM_BANKS_MAPPING_STAGE_PASS':
        raise ValueError('ROM-bank boundary required')
    lefs, libs, bank_bindings = [], [], {}
    for index, work in enumerate(args.banks):
        value = json.loads((work.resolve() / 'completion.json').read_text())
        if value['status'] != 'ROM_BANK_PHYSICAL_STAGE_PASS' or value['bank'] != index:
            raise ValueError(f'bank {index} has no passing hard-block run')
        for path, digest in value['artifacts'].items():
            if sha(Path(path)) != digest:
                raise ValueError('bank artifact changed: ' + path)
        lefs.append(value['abstract']['lef'])
        libs.append(value['abstract']['lib'])
        bank_bindings[str(work.resolve() / 'completion.json')] = sha(work.resolve() / 'completion.json')
    synthesis = ROOT / 'build/student-mini/cpu-synthesis/957e229a73ffa590f8e335968b27acbe12b88f1ebab91c3b5922fe876c8a64f1'
    sram_lef = synthesis / f'{SRAM}.lef'
    sram_lib = ROOT / f'build/openram/vortex-banked/{SRAM}/{SRAM}_TT_1p8V_25C.lib'
    sram_gds = ROOT / f'build/openram/vortex-banked/{SRAM}/{SRAM}.gds'
    sdc = ROOT / 'integration/student-mini/cpu_constraint.sdc'
    bindings = {str(p): sha(p) for p in (Path(__file__), args.replay.resolve() / 'completion.json', mapping / 'completion.json',
                                         boundary / 'completion.json', boundary / 'mapped.v', sram_lef, sram_lib, sram_gds, sdc)}
    bindings.update(bank_bindings)
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/cpu-top-physical-config' / key
    work.mkdir(parents=True, exist_ok=False)
    stubs = [f'(* blackbox *) module {SRAM}(input clk0, input csb0, input [3:0] wmask0, input [9:0] addr0, '
             'input [31:0] din0, input clk1, input csb1, input [9:0] addr1, output [31:0] dout1); endmodule']
    # ROM bank modules are defined (with contents) in mapped.v; SYNTH_BLACKBOXES turns them into hard-macro references.
    (work / 'macro-blackbox.v').write_text('\n'.join(stubs) + '\n')
    tcl, count = placement_tcl()
    (work / 'macro-placement.tcl').write_text(tcl)
    names = ' '.join([SRAM] + [f'student_mini_cpu_rom_bank_{i:02d}' for i in range(25)])
    (work / 'config.mk').write_text(f'''export PLATFORM = sky130hd
export DESIGN_NAME = cpu_student_mini_physical_top_asic
export VERILOG_FILES = {boundary / "mapped.v"} {work / "macro-blackbox.v"}
export VERILOG_FILES_BLACKBOX = {work / "macro-blackbox.v"}
export SYNTH_BLACKBOXES = {names}
export ADDITIONAL_LEFS = {sram_lef} {" ".join(lefs)}
export ADDITIONAL_LIBS = {sram_lib} {" ".join(libs)}
export ADDITIONAL_GDS = {sram_gds}
export SDC_FILE = {sdc}
export CORE_MARGIN = 20
export PLACE_DENSITY = 0.30
export SYNTH_MOCK_LARGE_MEMORIES = 0
export SYNTH_MEMORY_MAX_BITS = 401856
export DIE_AREA = 0 0 {DIE_W} {DIE_H}
export CORE_AREA = 20 20 {DIE_W - 20} {DIE_H - 20}
export MACRO_PLACEMENT_TCL = {work / "macro-placement.tcl"}
export MACRO_PLACE_HALO = 10 10
export PRE_PDN_TCL = {ROOT / "ppa/openram/connect_openram_power.tcl"}
export NUM_CORES = 8
''')
    result = dict(status='CPU_TOP_PHYSICAL_CONFIG_READY', bindings=bindings, macro_count=count, sram_macros=12, rom_bank_macros=25,
                  boundary=str(boundary), artifacts={p.name: sha(p) for p in work.iterdir() if p.is_file()})
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], macros=count)))


if __name__ == '__main__':
    main()
