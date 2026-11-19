"""Bind the actual STD/PERF mini GPU to existing audited SRAM views.

This prepares and checks a synthesis boundary, not a functional equivalence or
physical signoff. Unsupported memory shapes fail before any placement starts.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.enumerate_vortex_sram_variants import enumerate_rams
from scripts.generate_vortex_openram_bindings import generate
from scripts.generate_vortex_macro_placements import reachable_instances, pack, render_tcl, parse_lef


def check_shapes(rams, plan):
    known = {(row['module'], row['data_width'], row['depth'], row['write_enable_width']): row for row in plan['variants']}
    if not rams: raise ValueError('no actual reachable GPU memories')
    missing = set(rams)-set(known)
    if missing: raise ValueError('unsupported mini GPU SRAM shape: '+str(sorted(missing)))
    expected = Counter()
    banks = {'vortex_dp_256x64_w32': ('vortex_sp_64x128_w8', 4),
             'vortex_sp_512x64_w64': ('vortex_sp_128x128_w16', 4),
             'vortex_sp_512x128_w64': ('vortex_sp_128x128_w16', 4)}
    for key, count in rams.items():
        row = known[key]
        if row.get('physical_macro', True): expected[row['macro_name']] += count
        else:
            name, multiplier = banks[row['macro_name']]
            expected[name] += count*multiplier
    return expected


def validate_ports(module):
    expected = {'clk': ('input', 1), 'reset': ('input', 1),
        'mem_req_valid': ('output', 2), 'mem_req_rw': ('output', 2),
        'mem_req_byteen': ('output', 128), 'mem_req_addr': ('output', 52),
        'mem_req_data': ('output', 1024), 'mem_req_tag': ('output', 20),
        'mem_req_ready': ('input', 2), 'mem_rsp_valid': ('input', 2),
        'mem_rsp_data': ('input', 1024), 'mem_rsp_tag': ('input', 20), 'mem_rsp_ready': ('output', 2)}
    for name, (direction, width) in expected.items():
        row = module['ports'].get(name)
        if not row or row['direction'] != direction or len(row['bits']) != width:
            raise ValueError('GPU wrapper port mismatch: '+name)


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary', type=Path, required=True)
    args = parser.parse_args()
    boundary = args.boundary.resolve()
    parent = json.loads((boundary/'completion.json').read_text())
    project = boundary/'mini_Vortex/project.v'
    if parent.get('extraction_complete') is not True or sha(project) != parent['project_sha256']:
        raise ValueError('actual STD/PERF boundary not verified')
    plan_path = ROOT/'grading/evidence/vortex-physical/openram-banked-logical-plan.json'
    staged_path = ROOT/'grading/evidence/vortex-physical/staged-openram-banked-manifest.json'
    plan, staged = (json.loads(p.read_text()) for p in (plan_path, staged_path))
    if staged.get('status') != 'PASS': raise ValueError('macro views lack prior qualification')
    yosys = Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    sources = [ROOT/'shared/rtl'/name for name in ('vortex_banked_large_sram_wrappers.sv',
        'vortex_command_adapter.sv', 'vortex_memory_adapter.sv', 'vortex_physical_top.sv')]
    paths = [Path(__file__), boundary/'completion.json', project, plan_path, staged_path, yosys, *sources,
        ROOT/'scripts/enumerate_vortex_sram_variants.py', ROOT/'scripts/generate_vortex_openram_bindings.py',
        ROOT/'scripts/generate_vortex_macro_placements.py', ROOT/'scripts/add_openram_via3_dogbones.py',
        ROOT/'ppa/common/constraint.sdc', ROOT/'ppa/designs/gpu-vortex-b0/common.mk',
        ROOT/'ppa/designs/gpu-vortex-b0/macro-inputs-banked.mk', ROOT/'ppa/openram/connect_openram_power.tcl']
    bindings = dict(parent['bindings'])
    for macro in staged['macros']:
        for row in macro['artifacts'].values():
            path = Path(row['path'])
            if sha(path) != row['sha256']: raise ValueError('macro view changed: '+str(path))
            paths.append(path)
    bindings.update({str(p): sha(p) for p in paths})
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-macro-boundary'/identity
    work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', physical_evidence_complete=False, bindings=bindings,
                  boundary_complete=False, simulation_asic_equivalence=False)
    started = time.monotonic()
    def run(name, text):
        script = work/(name+'.ys')
        script.write_text(text+'\n')
        with (work/(name+'.log')).open('x') as log:
            code = subprocess.run([str(yosys), '-Q', '-T', '-s', str(script)], cwd=ROOT,
                stdout=log, stderr=subprocess.STDOUT, timeout=900).returncode
        if code: raise RuntimeError(name+' hierarchy failed')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work), stage='WAITING_FOR_SERIAL_QUEUE')), flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if any(sha(Path(p)) != value for p, value in bindings.items()): raise ValueError('source changed while queued')
            run('original', f'read_verilog -sv {project}; hierarchy -check -top Vortex; proc; opt_clean; write_json {work}/original.json')
            original = json.loads((work/'original.json').read_text())
            validate_ports(original['modules']['Vortex'])
            rams = enumerate_rams(original)
            expected = check_shapes(rams, plan)
            result['logical_shapes'] = [dict(module=key[0], width=key[1], depth=key[2], write_enable_width=key[3], count=value) for key, value in sorted(rams.items())]
            transformed, boxes, mapping = generate(plan, project.read_text())
            (work/'project-banked.v').write_text(transformed)
            (work/'macros-blackboxes.v').write_text(boxes)
            (work/'bindings.sv').write_text(mapping)
            all_sources = [work/'macros-blackboxes.v', *sources, work/'project-banked.v']
            run('mapped', 'read_verilog -sv '+' '.join(map(str, all_sources))+
                f'; hierarchy -check -top vortex_physical_top; proc; opt_clean; check -assert; write_json {work}/mapped.json')
            mapped = json.loads((work/'mapped.json').read_text())
            instances = reachable_instances(mapped, set(expected), top='vortex_physical_top', prefix='')
            if Counter(name for _, name in instances) != expected: raise ValueError('mapped SRAM multiplicity differs')
            if len([c for c in mapped['modules']['vortex_physical_top']['cells'].values() if c['type'] == 'Vortex']) != 1:
                raise ValueError('actual Vortex core was lost')
            sizes = {m['macro_name']: parse_lef(Path(m['artifacts'][m['macro_name']+'.lef']['path']))[0] for m in staged['macros']}
            placements = pack(instances, sizes, origin=(60.25, 78.76), limit=(4139.75, 4139.75))
            (work/'macro-placement.tcl').write_text(render_tcl(placements))
            (work/'config.mk').write_text('\n'.join([
                f'GPU_PROJECT = {work}/project-banked.v', f'GPU_BLACKBOXES = {work}/macros-blackboxes.v',
                'export VERILOG_TOP_PARAMS = MEM_PORTS 2 MEM_ADDR_WIDTH 26 MEM_DATA_WIDTH 512 MEM_TAG_WIDTH 10',
                'export DIE_AREA = 0 0 4200 4200', 'export CORE_AREA = 20 20 4180 4180',
                f'export MACRO_PLACEMENT_TCL = {work}/macro-placement.tcl',
                f'include {ROOT}/ppa/designs/gpu-vortex-b0/common.mk', 'export NUM_CORES = 2', '']))
            if any(sha(Path(p)) != value for p, value in bindings.items()): raise ValueError('source changed during binding')
            result.update(boundary_complete=True, macro_counts=dict(expected), placements=placements,
                reason='Actual STD/PERF core and adapters bound to known SRAM shapes; functional ASIC replay, physical timing/route/power remain required')
    except Exception as error: result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic()-started
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), boundary_complete=result['boundary_complete'], reason=result['reason'])), flush=True)
    return 0 if result['boundary_complete'] else 1


if __name__ == '__main__': raise SystemExit(main())
