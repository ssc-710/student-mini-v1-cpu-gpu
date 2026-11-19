"""Extract the actual simulated LiteX CPU boundary at its external DFI port.

Retains the generated CPU, caches, SRAM, Wishbone/LiteDRAM interconnect and DMA
guard. Only SDRAM model return signals become external inputs; model logic then
becomes dead. This is a synthesis-entry candidate, not equivalence or B0 proof.
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

PREFIX = 'build_soc_coursesimsoc_dfi_p0_'
DFI_INPUTS = {'rddata': 128, 'rddata_valid': 1}
DFI_OUTPUTS = {'address': 13, 'bank': 2, 'cas_n': 1, 'cke': 1, 'cs_n': 1,
    'ras_n': 1, 'we_n': 1, 'wrdata': 128, 'wrdata_mask': 16,
    'wrdata_en': 1, 'rddata_en': 1, 'reset_n': 1, 'odt': 1, 'act_n': 1}


def cut_dfi_inputs(source):
    """Cut precisely two generated DFI return drivers before alias canonicalization."""
    ports = []
    for suffix, width in DFI_INPUTS.items():
        name = PREFIX+suffix
        span = f'[{width-1}:0] ' if width > 1 else ''
        declaration = rf'^wire\s*(?:\[{width-1}:0\]\s*)?{name};\s*$'
        source, count = re.subn(declaration, '', source, flags=re.M)
        if count != 1:
            raise ValueError('ambiguous DFI declaration: '+name)
        driver = rf'^assign\s+\{{{name}\}}\s*=\s*build_soc_coursesimsoc_new_banks_read(?:_data)?3;\s*$'
        source, count = re.subn(driver, '', source, flags=re.M)
        if count != 1:
            raise ValueError('ambiguous external model driver: '+name)
        ports.append(f'    input wire {span}{name},')
    source, count = re.subn(r'^module sim \(\s*$', 'module sim (\n'+'\n'.join(ports), source, flags=re.M)
    if count != 1:
        raise ValueError('ambiguous simulated CPU top')
    return source


def validate_boundary(design):
    top = design['modules']['cpu_student_mini_physical_top']
    for names, direction in ((DFI_INPUTS, 'input'), (DFI_OUTPUTS, 'output')):
        for suffix, width in names.items():
            port = top['ports'][PREFIX+suffix]
            if port['direction'] != direction or len(port['bits']) != width:
                raise ValueError('DFI boundary differs: '+suffix)
    cells = list(top['cells'].values())
    def original_module(cell):
        name = cell['type']
        return design['modules'].get(name, {}).get('attributes', {}).get('hdlname', name)
    for module in ('VexRiscv', 'student_mini_native_dma_bridge', 'litex_wishbone_csr_bridge'):
        if sum(original_module(cell) == module for cell in cells) != 1:
            raise ValueError('missing or duplicated on-chip boundary: '+module)
    memories = []
    for name, cell in top['cells'].items():
        if cell['type'].startswith('$mem'):
            parameters = cell['parameters']
            size = int(parameters['SIZE'], 2)
            width = int(parameters['WIDTH'], 2)
            if size >= 4194304:
                raise ValueError('external SDRAM model survived boundary extraction')
            memories.append(dict(name=name, words=size, width_bits=width, bytes=size*width//8))
    if not memories:
        raise ValueError('local storage was incorrectly removed')
    return memories


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu-run', type=Path, required=True)
    args = parser.parse_args()
    parent = args.cpu_run.resolve()
    gateware = parent/'soc/gateware'
    completed = json.loads((parent/'completion.json').read_text())
    if not completed.get('target_run_complete'):
        raise ValueError('CPU replay incomplete')
    original = json.loads((parent/'inputs.json').read_text())
    generated = gateware/'sim.v'
    if completed['artifacts']['soc/gateware/sim.v'] != sha(generated):
        raise ValueError('simulated top changed')
    sources = [Path(name) for name in re.findall(r'--cc ([^ "\n]+)', (gateware/'build_sim.sh').read_text())]
    if not sources or generated not in sources:
        raise ValueError('missing original compilation source list')
    for path in sources:
        if path != generated and original['files'].get(str(path)) not in (None, sha(path)):
            raise ValueError('compiled CPU source changed: '+str(path))
    yosys = Path('/home/soclab/tools/oss-cad-suite/bin/yosys').resolve()
    paths = [*sources, *gateware.glob('*.init'), gateware/'build_sim.sh',
             parent/'inputs.json', parent/'completion.json', Path(__file__), yosys]
    bindings = {str(path): sha(path) for path in paths}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-boundary'/identity
    work.mkdir(parents=True, exist_ok=False)
    cut_source = work/'sim-dfi-boundary.v'
    cut_source.write_text(cut_dfi_inputs(generated.read_text()))
    compile_sources = [cut_source if path == generated else path for path in sources]
    script = '\n'.join([
        'read_verilog -sv '+' '.join(str(p) for p in compile_sources),
        'hierarchy -check -top sim', 'proc',
        'expose '+' '.join('sim/w:'+PREFIX+name for name in DFI_OUTPUTS),
        'opt_clean -purge', 'memory_collect', 'opt_clean -purge',
        # Remove unused optional cache ports across hierarchy, never tie X to 0.
        'opt', 'opt_hier', 'opt_clean -purge',
        'rename sim cpu_student_mini_physical_top', 'check -assert',
        f'write_json {work}/boundary.json', f'write_verilog -noattr {work}/boundary.v', 'stat'])+'\n'
    (work/'extract.ys').write_text(script)
    started = time.monotonic()
    result = dict(status='HOLD', physical_evidence_complete=False, bindings=bindings,
                  external_boundary='DFI SDRAM model only; the actual on-chip LiteDRAM controller/adapter is retained')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work), status='WAITING_FOR_SERIAL_QUEUE')), flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if any(sha(Path(p)) != digest for p, digest in bindings.items()):
                raise ValueError('CPU boundary inputs changed while queued')
            with (work/'yosys.log').open('x') as log:
                code = subprocess.run([str(yosys), '-Q', '-T', '-s', str(work/'extract.ys')],
                    cwd=gateware, stdout=log, stderr=subprocess.STDOUT, timeout=600).returncode
            if code:
                raise RuntimeError('boundary extraction failed; inspect yosys.log')
            result['top_memories'] = validate_boundary(json.loads((work/'boundary.json').read_text()))
            if any(sha(Path(p)) != digest for p, digest in bindings.items()):
                raise ValueError('CPU boundary source changed during extraction')
            result.update(extraction_complete=True,
                reason='Actual on-chip source boundary extracted; DFI replay/equivalence, ASIC reset semantics, mapped memories and routed power remain unqualified')
    except Exception as error:
        result.update(extraction_complete=False, reason=f'{type(error).__name__}: {error}')
    result['elapsed_seconds'] = time.monotonic()-started
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), complete=result['extraction_complete'], reason=result['reason'])), flush=True)
    return 0 if result['extraction_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
