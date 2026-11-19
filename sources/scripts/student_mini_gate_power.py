"""Gate-level activity power shared by the CPU and GPU platforms.

  1. compile the routed netlist (6_final.v) into a gatesim program;
  2. replay the recorded RTL port trace of one workload on the routed
     netlist (tools/gatesim), comparing every recorded output cycle, and write
     the pin activity of the measured window as SAIF;
  3. OpenROAD report_power on the final database with its SDC and extracted
     SPEF, the SAIF annotated at the design scope (tt 25 C 1.8 V corner).
No activity is estimated or propagated: unannotated pins are reported.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.collect_openroad_activity_power import parse_activity_annotation, parse_power_json

OPENROAD = Path('/home/soclab/.local/bin/openroad')
STD_LIB = Path('/home/soclab/src/orfs-clean-aabf2a/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib')
ENGINE_SOURCE = ROOT / 'tools/gatesim/gatesim.cpp'
COMPILER = ROOT / 'scripts/student_mini_gatesim.py'
CORNER = dict(process='sky130hd tt', voltage_v=1.8, temperature_c=25, liberty=STD_LIB.name)
POWER_TCL = '''foreach lib $::env(GATE_POWER_LIBS) { read_liberty $lib }
read_db $::env(GATE_POWER_ODB)
read_sdc $::env(GATE_POWER_SDC)
read_spef $::env(GATE_POWER_SPEF)
# One session, every workload: each SAIF re-annotates every pin it lists.
foreach {saif out} $::env(GATE_POWER_ITEMS) {
  read_saif -scope $::env(GATE_POWER_SCOPE) $saif
  report_activity_annotation -report_unannotated > $out/annotation.rpt
  report_power -format json -digits 15 > $out/power.json
  report_power > $out/power.rpt
}
'''


def tool_bindings():
    return {str(p): sha(p) for p in (Path(__file__), ENGINE_SOURCE, COMPILER, OPENROAD, STD_LIB,
                                     ROOT / 'scripts/collect_openroad_activity_power.py')}


def build_engine(work: Path) -> Path:
    engine = work / 'gatesim'
    if not engine.exists():
        subprocess.run(['g++', '-O2', '-std=c++17', '-o', str(engine), str(ENGINE_SOURCE)], check=True)
    return engine


def compile_netlist(work: Path, netlist: Path, top: str, macro_models: list[Path], log: Path, modules: list[str] = ()) -> Path:
    out = work / 'program'
    command = [sys.executable, str(COMPILER), 'compile', '--liberty', str(STD_LIB), '--netlist', str(netlist), '--top', top,
               '--out', str(out)]
    for model in macro_models:
        command += ['--macro-model', str(model)]
    for module in modules:
        command += ['--module-netlist', module]
    with log.open('x') as stream:
        subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=3600)
    summary = json.loads((out / 'summary.json').read_text())
    if summary['undriven_nets']:
        raise ValueError(f'{summary["undriven_nets"]} undriven nets in the routed netlist: {summary["undriven_examples"][:5]}')
    return out


def reset_release_cycle(trace: Path, reset_port: str, active_low: bool = True) -> int:
    """First cycle at which the recorded reset input is deasserted."""
    layout, width = [], 0
    with trace.open() as stream:
        for line in stream:
            parts = line.split()
            if parts[0] == 'L' and parts[1] == 'I':
                layout.append((parts[2], int(parts[3])))
                width += int(parts[3])
            elif parts[0] == 'I':
                offset = 0
                for name, w in layout:
                    if name == reset_port:
                        bits = bin(int(parts[2], 16))[2:].zfill(width)
                        value = bits[offset:offset + w] == '1'
                        if value == active_low:
                            return int(parts[1])
                    offset += w
    raise ValueError('reset never released in ' + str(trace))


def replay(engine: Path, program: Path, trace: Path, out: Path, timeout: int, begin_cycle: int | None = None,
           windows: list[int] | None = None, stop: bool = False, qualify: Path | None = None, check_from: int = 0) -> dict:
    """Replay one trace; single window [begin_cycle, end) or the selected marker windows."""
    command = [str(engine), str(program / 'program.txt'), str(program / 'saifmap.txt'), str(trace), str(out)]
    if windows is not None:
        command += ['--windows', ','.join(map(str, windows))] + (['--stop'] if stop else [])
    else:
        command += ['--begin', str(begin_cycle or 0)]
    if qualify is not None:
        command += ['--qualify', str(qualify)]
    command += ['--check-from', str(check_from), '--mismatch-log', '200']
    with (out / 'gatesim.log').open('x') as log:
        code = subprocess.call(command, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    report = out / 'gatesim.json'
    value = json.loads(report.read_text()) if report.is_file() else {}
    value['exit_code'] = code
    if code or value.get('mismatched_cycles') != 0 or value.get('checked_cycles', 0) <= 0:
        raise ValueError(f'gate replay disagrees with the RTL ports: {value}')
    if value.get('races'):
        raise ValueError(f'gate replay has {value["races"]} same-edge data races')
    return value


def power(odb: Path, sdc: Path, spef: Path, libs: list[Path], scope: str, items: list[tuple[Path, Path]], log: Path) -> list[dict]:
    """OpenROAD power of one routed design for every (saif, output directory) workload."""
    tcl = log.with_suffix('.tcl')
    tcl.write_text(POWER_TCL)
    env = dict(os.environ, GATE_POWER_LIBS=' '.join(map(str, [STD_LIB, *libs])), GATE_POWER_ODB=str(odb), GATE_POWER_SDC=str(sdc),
               GATE_POWER_SPEF=str(spef), GATE_POWER_SCOPE=scope,
               GATE_POWER_ITEMS=' '.join(f'{saif} {out}' for saif, out in items))
    with log.open('x') as stream:
        code = subprocess.call([str(OPENROAD), '-exit', '-no_splash', '-threads', '2', str(tcl)], env=env, stdout=stream,
                               stderr=subprocess.STDOUT, timeout=4 * 3600)
    if code:
        raise RuntimeError(f'OpenROAD power exited {code}; see {log}')
    results = []
    for _, out in items:
        annotation = (out / 'annotation.rpt').read_text()
        annotated, total, coverage = parse_activity_annotation(annotation, 'SAIF')
        dynamic_mw, leakage_mw, total_mw = parse_power_json(out / 'power.json')
        unannotated = [line.strip() for line in annotation.split('Unannotated pins:', 1)[-1].splitlines() if line.strip()]
        results.append(dict(annotated_pins=annotated, total_pins=total, annotation_percent=coverage,
                            unannotated_pins=total - annotated, unannotated_percent=100.0 - coverage,
                            unannotated_examples=unannotated[:20], dynamic_mw=dynamic_mw, leakage_mw=leakage_mw,
                            total_mw=total_mw))
    return results


def trace_layout(trace: Path):
    """Output ports of a port trace, MSB-first concatenation order: [(port, width)]."""
    layout = []
    with trace.open() as stream:
        for line in stream:
            if not line.startswith('L '):
                break
            _, kind, port, width = line.split()
            if kind == 'O':
                layout.append((port, int(width)))
    return layout


def write_qualifiers(path: Path, layout, rule):
    """rule(port, lsb_bit) -> [(port, lsb_bit), ...] qualifying output bits (all must be 1 to compare)."""
    offset, at = {}, 0
    for port, width in layout:
        offset[port] = (at, width)
        at += width
    index = lambda port, bit: offset[port][0] + offset[port][1] - 1 - bit
    lines = []
    for port, width in layout:
        for bit in range(width):
            quals = rule(port, bit)
            if quals:
                lines.append(f"{index(port, bit)} " + ' '.join(str(index(q, b)) for q, b in quals))
    path.write_text('\n'.join(lines) + '\n')
    return len(lines)


def gpu_rule(port, bit):
    """Memory request fields matter only while that port's request is valid (data and byte enables
    only for writes, data only in enabled bytes); host response fields only while the response is valid."""
    valid = lambda p: ('mem_req_valid_o', 1 - p)   # [0:1] ascending: port 0 is the MSB
    rw = lambda p: ('mem_req_rw_o', 1 - p)
    if port == 'mem_req_data_o':
        p = bit // 512
        return [valid(p), rw(p), ('mem_req_byteen_o', p * 64 + (bit % 512) // 8)]
    if port == 'mem_req_byteen_o':
        return [valid(bit // 64), rw(bit // 64)]
    if port == 'mem_req_addr_o':
        return [valid(bit // 26)]
    if port == 'mem_req_tag_o':
        return [valid(bit // 10)]
    if port == 'mem_req_rw_o':
        return [valid(1 - bit)]
    if port in ('host_rsp_data_o', 'host_rsp_error_o'):
        return [('host_rsp_valid_o', 0)]
    return []


def gzip_file(path: Path) -> Path:
    target = path.with_suffix(path.suffix + '.gz')
    with path.open('rb') as src, target.open('wb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
    path.unlink()
    return target


def sanitize_macro_libs(libs: list[Path], out: Path) -> tuple[list[Path], dict]:
    """Copies of the OpenRAM macro libraries without internal_power groups.

    The OpenRAM analytical power model wrote access energies of 3e10..2e11 per
    edge (also in its own datasheets), i.e. no valid characterisation exists.
    Macro access energy is therefore excluded (reported with the per-macro
    access counts); macro leakage and pin capacitance (net switching) remain.
    """
    out.mkdir(parents=True, exist_ok=True)
    clean, removed = [], {}
    for lib in libs:
        text = lib.read_text()
        count, pieces, i = 0, [], 0
        while True:
            j = text.find('internal_power(', i)
            if j < 0:
                pieces.append(text[i:])
                break
            k = text.index('{', j)
            depth, m = 1, k + 1
            while depth:
                depth += (text[m] == '{') - (text[m] == '}')
                m += 1
            pieces.append(text[i:j])
            i = m
            count += 1
        target = out / lib.name
        target.write_text(''.join(pieces))
        clean.append(target)
        removed[lib.name] = count
    return clean, removed


def config_libs(config: Path) -> list[Path]:
    found = re.search(r'^export ADDITIONAL_LIBS = (.*)$', config.read_text(), re.M)
    return [Path(p) for p in found.group(1).split()] if found else []
