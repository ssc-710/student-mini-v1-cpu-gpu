"""Export a PERF-enabled, synthesizable mini Vortex boundary without routing.

No modifications to the vendor checkout or existing SimX/counter builds.
The generated ASIC source remains HOLD until memory binding, RTL replay,
adapter qualification and actual SKY130HD signoff are complete.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha

CONFIGS = '-DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_FPU_TYPE=STD'


def check_resolved(text):
    values = dict(re.findall(r'^#define (VX_CFG_\w+) ([^\n]+)$', text, re.M))
    expected = dict(VX_CFG_NUM_CORES='1', VX_CFG_NUM_WARPS='2', VX_CFG_NUM_THREADS='4',
                    VX_CFG_L2_ENABLED='0', VX_CFG_ICACHE_ENABLED='1',
                    VX_CFG_DCACHE_ENABLED='1', VX_CFG_LMEM_ENABLED='1',
                    VX_CFG_FPU_TYPE='STD', VX_CFG_FDIV_LATENCY='17', VX_CFG_FSQRT_LATENCY='17')
    for name, value in expected.items():
        if values.get(name) != value:
            raise ValueError('wrong mini synthesizable boundary: '+name)
    return values


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    source = Path('/mnt/d/open-soc-ai-labs-vortex')
    tools = Path('/mnt/d/open-soc-ai-labs-vortex-tools')
    names = subprocess.check_output(['git', '-C', str(source), 'ls-files', 'hw', 'sw', 'ci',
                                     'configure', 'config.mk.in', 'VX_config.toml'], text=True).splitlines()
    paths = [source/name for name in names if (source/name).is_file()]
    paths += [Path(__file__), tools/'sv2v/bin/sv2v', tools/'verilator/bin/verilator',
              ROOT/'shared/rtl/vortex_physical_top.sv', ROOT/'shared/rtl/vortex_command_adapter.sv',
              ROOT/'shared/rtl/vortex_memory_adapter.sv']
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-boundary'/identity
    work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', physical_evidence_complete=False, bindings=bindings,
                  configs=CONFIGS, perf_enable=True, entity_gpu_required=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n')
    started = time.monotonic()
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='', MAKEFLAGS='-j2')
    def run(command, name, cwd, timeout):
        print(json.dumps(dict(work=str(work), stage=name)), flush=True)
        with (work/(name+'.log')).open('x') as log:
            completed = subprocess.run(command, cwd=cwd, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, timeout=timeout)
        if completed.returncode:
            raise RuntimeError(name+' failed')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work), stage='WAITING_FOR_SERIAL_QUEUE')), flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if any(sha(Path(p)) != digest for p, digest in bindings.items()):
                raise ValueError('GPU boundary source changed while queued')
            build = work/'vortex-build'
            build.mkdir()
            run([str(source/'configure'), '--xlen=32', '--tooldir='+str(tools),
                 '--osversion=ubuntu/focal', '--prefix='+str(work/'install')], 'configure', build, 120)
            resolver = [sys.executable, str(source/'ci/gen_config.py'), '--config', str(source/'VX_config.toml'),
                        '--format', 'cpp', '--resolved']
            sim = subprocess.check_output(resolver+['--cflags='+CONFIGS+' -DVX_CFG_XLEN=32 -DSIMULATION -DSV_DPI'], text=True)
            asic = subprocess.check_output(resolver+['--cflags='+CONFIGS+' -DVX_CFG_XLEN=32 -DSYNTHESIS -DASIC'], text=True)
            sim_values, asic_values = check_resolved(sim), check_resolved(asic)
            # This is a configuration comparison, never a functional equivalence proof.
            compared = [name for name in sim_values if name.startswith(('VX_CFG_F', 'VX_CFG_NUM_', 'VX_CFG_ICACHE_', 'VX_CFG_DCACHE_'))]
            differences = {name: [sim_values[name], asic_values.get(name)] for name in compared if sim_values[name] != asic_values.get(name)}
            if differences:
                raise ValueError('simulation/ASIC configuration differs: '+str(differences))
            (work/'sim-resolved.h').write_text(sim)
            (work/'asic-resolved.h').write_text(asic)
            run(['make', '-j2', '-C', str(build/'hw/syn/yosys'), 'gen-sources', 'PERF=1',
                 'CONFIGS='+CONFIGS, 'PREFIX='+str(work/'mini'), 'SV2V='+str(tools/'sv2v/bin/sv2v'),
                 'VERILATOR='+str(tools/'verilator/bin/verilator')], 'generate', work, 900)
            project = work/'mini_Vortex/project.v'
            if not project.is_file() or project.stat().st_size == 0:
                raise ValueError('missing generated synthesizable Vortex')
            if any(sha(Path(p)) != digest for p, digest in bindings.items()):
                raise ValueError('GPU source changed during export')
            result.update(extraction_complete=True, project_sha256=sha(project),
                          reason='STD-FPU/PERF ASIC source generated; SRAM binding, full RTL equivalence, adapters, route and activity power remain unqualified')
    except Exception as error:
        result.update(extraction_complete=False, reason=f'{type(error).__name__}: {error}')
    result['elapsed_seconds'] = time.monotonic()-started
    result['artifacts'] = {p.relative_to(work).as_posix(): sha(p) for p in work.rglob('*')
                           if p.is_file() and not p.is_symlink()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), complete=result['extraction_complete'], reason=result['reason'])), flush=True)
    return 0 if result['extraction_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
