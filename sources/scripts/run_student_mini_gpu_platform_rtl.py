"""Whole-platform GPU RTL execution: mapped Vortex core + bus-fault adapters.

Phases (each separately guarded / resumable):
  build     isolated Vortex rtlsim overlay with the mapped core RTL, the
            bus-fault physical top/adapters, OpenRAM behavioural models and the
            fault-decoding memory-system bridge; compile the real kernel.
  run       execute a shard of case ordinals, one process per case and per
            hardware counter class (MPM classes 0/4/7), saving full transcripts.
  assemble  join every case/seed to the frozen golden vectors and the SimX
            functional run of the same kernel; derive bus-error statuses only
            from the device status register; attach per-case RTL counters.
No golden output is visible to the device or the bridge.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.run_student_mini_gpu_physical_replay import overlay_directory
from scripts.student_mini_gpu_physical_replay_sources import rename_modules, timing_processor, quiet_macro, overlay_configure
from scripts.student_mini_gpu_constant_calls import lower_scheduler_constants
from scripts.student_mini_gpu_host_handshake import drain_read_response
from scripts.assemble_student_mini_gpu_results import parse
from scripts.assemble_student_mini_gpu_counters import PERF, DCACHE, MEMORY

SOURCE = Path('/mnt/d/open-soc-ai-labs-vortex')
TOOLS = Path('/mnt/d/open-soc-ai-labs-vortex-tools')
CLASSES = (0, 4, 7)
STATUS_LINE = re.compile(r'^STUDENT_GPU_DEVICE_STATUS fault=([01]) busy=([01])$')
LOCAL = ['integration/student-mini/gpu_fault_physical_top.sv', 'integration/student-mini/gpu_status_command_adapter.sv',
         'integration/student-mini/gpu_fault_memory_adapter.sv', 'tests/rtl/student_mini_gpu_fault_bridge.sv',
         'shared/rtl/vortex_banked_large_sram_wrappers.sv']


def status_processor(source):
    """After every launch the host model reads the device status register."""
    anchor = '''    if (cout_drainer) cout_drainer->tick(); // final flush

    this->cout_flush();
  }
'''
    if source.count(anchor) != 1:
        raise ValueError('unknown pinned simulator run() seam')
    return source.replace(anchor, '''    if (cout_drainer) cout_drainer->tick(); // final flush

    this->cout_flush();
    // Device status register (DCR 0xFFF): {busy, sticky bus fault}.
    uint32_t student_status = 0;
    this->dcr_read(0xFFF, 0, &student_status);
    std::cout << "STUDENT_GPU_DEVICE_STATUS fault=" << (student_status & 1u)
              << " busy=" << ((student_status >> 1) & 1u) << std::endl;
  }
''')


def connect_fault_shim(source):
    changed, count = re.subn(r'\bVortex\s+vortex\s*\(', 'student_mini_gpu_fault_bridge vortex (', source)
    if count != 1:
        raise ValueError('ambiguous simulator core instance')
    return changed


def heartbeat(work, stage, started):
    (work / 'heartbeat.json').write_text(json.dumps(dict(stage=stage, elapsed_seconds=time.monotonic() - started,
                                                        updated_at=datetime.now(timezone.utc).isoformat())) + '\n')


def environment():
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='', CHIP_BE='opencl',
               HIP_CLANG_PATH=str(TOOLS / 'llvm-vortex/bin'), MAKEFLAGS='-j2', THREADS='2',
               VORTEX_CP_POLL_TIMEOUT_S='600')
    env['PATH'] = str(TOOLS / 'verilator/bin') + ':' + env['PATH']
    return env


def execute(command, log, cwd, timeout, env):
    with log.open('w') as stream:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, 9)
            child.wait()
            return 'timeout'


def build(args):
    boundary = args.boundary.resolve()
    functional = args.functional.resolve()
    completed = json.loads((boundary / 'completion.json').read_text())
    project = boundary / 'project-banked.v'
    if completed['artifacts'].get(project.name) != sha(project):
        raise ValueError('mapped RTL changed')
    manifest = json.loads((functional / 'manifest.json').read_text())
    staged_path = ROOT / 'grading/evidence/vortex-physical/staged-openram-banked-manifest.json'
    staged = json.loads(staged_path.read_text())
    models = [Path(row['path']) for macro in staged['macros'] for name, row in macro['artifacts'].items() if name.endswith('.v')]
    paths = [Path(__file__), ROOT / 'scripts/student_mini_gpu_physical_replay_sources.py',
             ROOT / 'scripts/student_mini_gpu_constant_calls.py', ROOT / 'scripts/student_mini_gpu_host_handshake.py',
             boundary / 'completion.json', project, staged_path, *models, functional / 'manifest.json',
             *(ROOT / p for p in LOCAL), TOOLS / 'verilator/bin/verilator', TOOLS / 'verilator/bin/verilator_bin',
             *(functional / n for n in ('Makefile', 'student_mini.cu', 'device_compat.cc', 'common.h'))]
    paths.extend(SOURCE / n for n in subprocess.check_output(['git', '-C', str(SOURCE), 'ls-files', 'configure', 'hw', 'sim', 'sw'],
                                                              text=True).splitlines() if (SOURCE / n).is_file())
    bindings = {str(p): sha(p) for p in paths}
    bindings.update(manifest['bindings'])
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/gpu-platform-rtl' / key
    work.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    plan = dict(status='HOLD', bindings=bindings, boundary=str(boundary), functional=str(functional),
                input_directory=manifest['input_directory'], classes=list(CLASSES), clock_period_ns=10)
    (work / 'inputs.json').write_text(json.dumps(plan, indent=2) + '\n')
    overlay = work / 'source'
    overlay_directory(SOURCE, overlay, {'sim', 'configure'})
    (overlay / 'configure').write_text(overlay_configure((SOURCE / 'configure').read_text()))
    (overlay / 'configure').chmod(0o755)
    overlay_directory(SOURCE / 'sim', overlay / 'sim', {'rtlsim'})
    private = overlay / 'sim/rtlsim'
    overlay_directory(SOURCE / 'sim/rtlsim', private, {'Makefile', 'processor.cpp', 'rtlsim_shim.sv'})
    transformed, mapping = rename_modules(lower_scheduler_constants(project.read_text()))
    (private / 'physical-project.v').write_text(transformed)
    top, _ = rename_modules((ROOT / LOCAL[0]).read_text(), mapping)
    (private / 'physical-top.sv').write_text(top)
    processor = status_processor(drain_read_response(timing_processor((SOURCE / 'sim/rtlsim/processor.cpp').read_text())))
    (private / 'processor.cpp').write_text(processor)
    (private / 'rtlsim_shim.sv').write_text(connect_fault_shim((SOURCE / 'sim/rtlsim/rtlsim_shim.sv').read_text()))
    extra = [private / 'physical-project.v', private / 'physical-top.sv', *(ROOT / p for p in LOCAL[1:])]
    for model in models:
        output = private / model.name
        output.write_text(quiet_macro(model.read_text()))
        extra.append(output)
    makefile = (SOURCE / 'sim/rtlsim/Makefile').read_text()
    makefile += ('\n# Whole-platform GPU RTL (mapped core + bus-fault adapters).\nVL_FLAGS += --timing --timescale-override 1ns/1ps '
                 + ' '.join(map(str, extra)) + '\nCXXFLAGS := $(filter-out -std=c++17,$(CXXFLAGS)) -std=c++20\n')
    (private / 'Makefile').write_text(makefile)
    for name in ('student_mini.cu', 'device_compat.cc', 'common.h'):
        shutil.copy2(functional / name, work / name)
    (work / 'Makefile').write_text((functional / 'Makefile').read_text().replace(str(functional), str(work))
                                   .replace('CONFIGS := ', 'CONFIGS := -DVX_CFG_FPU_TYPE=STD '))
    derived = {str(p.relative_to(work)): sha(p) for p in private.iterdir() if p.is_file() and not p.is_symlink()}
    derived['source/configure'] = sha(overlay / 'configure')
    (work / 'source-derivation.json').write_text(json.dumps(dict(module_alpha_renaming=mapping, files=derived), indent=2) + '\n')
    env = environment()
    buildroot = work / 'vortex-build'
    buildroot.mkdir()
    steps = [('configure', [str(overlay / 'configure'), '--xlen=32', '--tooldir=' + str(TOOLS), '--osversion=ubuntu/focal',
                            '--prefix=' + str(work / 'install')], buildroot, 300),
             ('kernel', ['make', '-j2', '-C', str(buildroot / 'sw/kernel'),
                         'CONFIGS=-DVX_CFG_FPU_TYPE=STD -DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4',
                         'THREADS=2'], work, 900),
             ('compile', ['make', '-j2', '-C', str(work), 'all', 'PERF=1', 'THREADS=2'], work, 1800),
             ('library', ['make', '-j2', '-C', str(work), 'run-rtlsim', 'PERF=1', 'THREADS=2',
                          f'OPTS={manifest["input_directory"]}/inputs.bin 0 1'], work, 7200)]
    result = dict(plan, stages=[])
    try:
        for name, command, cwd, timeout in steps:
            heartbeat(work, name.upper(), started)
            then = time.monotonic()
            code = execute(command, work / (name + '.log'), cwd, timeout, dict(env, VORTEX_PROFILING='0'))
            result['stages'].append(dict(stage=name, exit_code=code, seconds=time.monotonic() - then))
            if code != 0:
                raise RuntimeError(f'{name} failed ({code})')
        dry = subprocess.run(['make', '-n', '-C', str(work), 'run-rtlsim', 'PERF=1', 'THREADS=2', 'OPTS=@OPTS@'],
                             cwd=work, env=env, capture_output=True, text=True, check=True).stdout
        lines = [line for line in dry.splitlines() if 'VORTEX_DRIVER=rtlsim' in line and '@OPTS@' in line]
        if len(lines) != 1:
            raise ValueError('cannot capture the runtime command')
        (work / 'run-command.sh').write_text(lines[0] + '\n')
        result['artifacts'] = {p.relative_to(work).as_posix(): sha(p) for p in
                               [*work.glob('*.log'), work / 'run-command.sh', work / 'student_mini',
                                *(buildroot / 'sw/runtime').glob('*.so')]}
        result.update(status='GPU_PLATFORM_RTL_BUILD_STAGE_PASS', reason='Mapped core + bus-fault adapters built; run shards next')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic() - started
    (work / 'build.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'GPU_PLATFORM_RTL_BUILD_STAGE_PASS' else 1


def checked_build(work):
    built = json.loads((work / 'build.json').read_text())
    if built['status'] != 'GPU_PLATFORM_RTL_BUILD_STAGE_PASS':
        raise ValueError('build stage did not pass')
    for name, digest in built['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('platform source changed: ' + name)
    for name, digest in built['artifacts'].items():
        if sha(work / name) != digest:
            raise ValueError('build artifact changed: ' + name)
    return built


def run_one(work, built, ordinal, cls, env):
    folder = work / 'runs' / f'{ordinal:04d}-c{cls}'
    record = folder / 'record.json'
    if record.is_file():
        return json.loads(record.read_text())
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    command = (work / 'run-command.sh').read_text().strip()
    command = command.replace('@OPTS@', shlex.quote(f'{built["input_directory"]}/inputs.bin') + f' {ordinal} 1')
    command = command.replace('./student_mini', shlex.quote(str(work / 'student_mini')))
    # Bounded retry of a start-up crash only (clean-20261014): a run killed by a signal before it printed any simulation
    # output line (STUDENT_GPU...) is retried at most twice; every crashed attempt is kept under startup-crash-attempts/
    # and counted/reported in the record. Any other outcome (including a crash after simulation output) is unchanged.
    attempts = []
    while True:
        then = time.monotonic()
        code = execute(['bash', '-c', command], folder / 'transcript.log', folder, 7200, dict(env, VORTEX_PROFILING=str(cls)))
        text = (folder / 'transcript.log').read_text(errors='replace')
        lines = text.splitlines()
        if code < 0 and not any(line.startswith('STUDENT_GPU') for line in lines) and len(attempts) < 2:
            kept = work / 'startup-crash-attempts' / f'{folder.name}-attempt{len(attempts) + 1}'
            kept.parent.mkdir(parents=True, exist_ok=True)
            attempts.append(dict(exit_code=code, seconds=time.monotonic() - then, transcript_sha256=sha(folder / 'transcript.log'),
                                 kept=str(kept.relative_to(work))))
            shutil.move(str(folder), str(kept))
            folder.mkdir(parents=True)
            continue
        break
    actual = [line for line in lines if line.startswith('STUDENT_GPU ')]
    status = [STATUS_LINE.fullmatch(line).groups() for line in lines if STATUS_LINE.fullmatch(line)]
    perf = [PERF.fullmatch(line).groups() for line in lines if PERF.fullmatch(line)]
    value = dict(ordinal=ordinal, counter_class=cls, exit_code=code, seconds=time.monotonic() - then,
                 transcript_sha256=sha(folder / 'transcript.log'))
    if attempts:
        value.update(startup_crash_retries=len(attempts), startup_crash_attempts=attempts)
    if (code != 0 or len(actual) != 1 or not status or len(perf) != 1
            or lines.count(f'STUDENT_GPU_COMPLETE start={ordinal} count=1') != 1):
        value['complete'] = False
    else:
        canonical = actual[0].replace(f'ordinal={ordinal} ', 'ordinal=0 ', 1) + '\nSTUDENT_GPU_COMPLETE start=0 count=1\n'
        # One status read follows every launch the runtime issues for this
        # command; a fault in any of them is a fault of the command.
        value.update(complete=True, output=parse(canonical, 1)[0], device_fault=max(int(f) for f, _ in status),
                     device_launches=len(status), device_busy=max(int(b) for _, b in status),
                     instructions=int(perf[0][0]), cycles=int(perf[0][1]))
        if cls == 4:
            cache = [DCACHE.fullmatch(line).groups() for line in lines if DCACHE.fullmatch(line)]
            value['dcache_requests'] = int(cache[0][1]) if len(cache) == 1 and cache[0][0] == '0' else None
        if cls == 7:
            memory = [MEMORY.fullmatch(line).groups() for line in lines if MEMORY.fullmatch(line)]
            value['memory'] = list(map(int, memory[0])) if len(memory) == 1 else None
    record.write_text(json.dumps(value) + '\n')
    return value


def run(args):
    work = args.work.resolve()
    built = checked_build(work)
    started = time.monotonic()
    ordinals = args.ordinals or list(range(1000))
    mine = [o for i, o in enumerate(ordinals) if i % args.shards == args.shard]
    env = environment()
    failures = retries = 0
    for index, ordinal in enumerate(mine):
        for cls in CLASSES:
            heartbeat(work, f'SHARD{args.shard} {index}/{len(mine)} ordinal={ordinal} class={cls}', started)
            value = run_one(work, built, ordinal, cls, env)
            failures += not value['complete']
            retries += value.get('startup_crash_retries', 0)
            print(json.dumps({k: value.get(k) for k in ('ordinal', 'counter_class', 'complete', 'device_fault', 'cycles', 'seconds',
                                                        'startup_crash_retries')}), flush=True)
    checked_build(work)
    print(json.dumps(dict(work=str(work), shard=args.shard, shards=args.shards, runs=len(mine) * len(CLASSES),
                          incomplete=failures, startup_crash_retries=retries, elapsed_seconds=time.monotonic() - started)), flush=True)
    return 0 if failures == 0 else 1


def assemble(args):
    from collections import defaultdict
    from statistics import fmean
    from scripts.assemble_student_mini_gpu_results import join
    from scripts.export_student_mini_input import encode
    from scripts.student_mini import summarize_seeds
    work = args.work.resolve()
    built = checked_build(work)
    vectors = args.vectors.resolve()
    functional_path = args.functional_results.resolve()
    functional = json.loads(functional_path.read_text(encoding='utf-8'))
    goldens = [json.loads(line) for line in vectors.read_text().splitlines()]
    image = Path(built['input_directory']) / 'inputs.bin'
    if image.read_bytes() != b''.join(encode(r, i) for i, r in enumerate(goldens)):
        raise ValueError('executed input image differs from the frozen golden vectors')
    simx = {r['observation']['ordinal']: r['observation'] for r in functional['records']}
    if functional.get('platform') != 'gpu' or set(simx) != set(range(len(goldens))):
        raise ValueError('complete GPU SimX functional results required')
    actuals, extras = [], {}
    for ordinal in range(len(goldens)):
        runs = {}
        for cls in CLASSES:
            path = work / 'runs' / f'{ordinal:04d}-c{cls}' / 'record.json'
            value = json.loads(path.read_text())
            transcript = path.parent / 'transcript.log'
            if not value.get('complete') or sha(transcript) != value['transcript_sha256']:
                raise ValueError(f'incomplete RTL run {ordinal}/{cls}')
            runs[cls] = value
        outputs = {json.dumps(v['output'], sort_keys=True) for v in runs.values()}
        if len(outputs) != 1 or len({(v['instructions'], v['cycles'], v['device_fault']) for v in runs.values()}) != 1:
            raise ValueError(f'counter-class execution drift at {ordinal}')
        output = dict(runs[0]['output'], ordinal=ordinal)
        reference = simx[ordinal]
        for field in ('actual_status', 'actual_bits', 'selected', 'primitive'):
            if output[field] != reference[field]:
                raise ValueError(f'RTL/SimX functional disagreement at {ordinal}: {field}')
        fault = runs[0]['device_fault']
        if output['actual_status'] == 'UNSUPPORTED_BUS_INJECTION' and fault == 1:
            output['actual_status'] = 'BUS_ERROR'
        elif fault == 1:
            output['actual_status'] = 'UNEXPECTED_DEVICE_FAULT'
        memory = runs[7]['memory']
        dcache = runs[4]['dcache_requests']
        if memory is None or dcache is None or memory[0] != memory[1] + memory[2]:
            raise ValueError(f'missing traffic counters at {ordinal}')
        actuals.append(output)
        extras[ordinal] = dict(cycles=runs[0]['cycles'], instructions=runs[0]['instructions'], cache_bytes=dcache * 8,
                               dma_bytes=memory[0] * 64, dcache_requests=dcache, memory_requests=memory[0],
                               memory_reads=memory[1], memory_writes=memory[2], device_fault=fault,
                               rtl_seconds=[runs[c]['seconds'] for c in CLASSES])
    report = join(goldens, actuals)
    for row in report['records']:
        observed = row['observation']
        ordinal = observed['ordinal']
        observed.update(extras[ordinal], backend='vortex-rtlsim-mapped-core-fault-adapters', performance_eligible=True,
                        hardware_performance_measured=True, counter_source='Vortex MPM classes 0/4/7 on the mapped GPU RTL',
                        measurement_boundary='whole one-case command including kernel startup',
                        traffic_definition='D-cache accepted 8-byte word transactions; external accepted 64-byte memory blocks',
                        missing_witnesses=[])
        golden = row['golden']
        if observed['actual_status'] == 'BUS_ERROR' or not golden['output_values']:
            matched = observed['actual_status'] == golden['expected_status'] and not observed['actual_bits']
            row['comparison'] = dict(kind='error-status', expected=golden['expected_status'], actual=observed['actual_status'],
                                     status='PASS' if matched else 'FAIL', delta=None)
            observed['numeric_match'] = matched
        row['status'] = 'PASS' if observed['numeric_match'] is True else 'FAIL'
    groups = defaultdict(list)
    for row in report['records']:
        groups[row['case']['id']].append(row)
    report['cases'] = []
    for case_id, group in groups.items():
        group.sort(key=lambda r: r['seed'])
        numeric = [dict(seed=r['seed'], **r['comparison']) for r in group if r['comparison'] and 'golden_bits' in r['comparison']]
        report['cases'].append(dict(platform='gpu', case_id=case_id, status='FAIL' if any(r['status'] == 'FAIL' for r in group) else 'PASS',
                                    failed_seeds=[r['seed'] for r in group if r['status'] == 'FAIL'],
                                    numeric=summarize_seeds(numeric) if len(numeric) == 10 else None,
                                    counters={k: dict(raw=[r['observation'][k] for r in group],
                                                      mean=fmean(r['observation'][k] for r in group))
                                              for k in ('cycles', 'instructions', 'dma_bytes', 'cache_bytes')}))
    report.update(status='GPU_PLATFORM_RTL_RESULTS', backend='vortex-rtlsim-mapped-core-fault-adapters',
                  counts={s: sum(r['status'] == s for r in report['records']) for s in ('PASS', 'FAIL')},
                  numeric_matches=sum(r['observation']['numeric_match'] is True for r in report['records']),
                  rtl_counter_records=len(report['records']), rtl_counter_coverage_complete=True,
                  reason='Every case/seed executed on the mapped GPU RTL with physical adapters; SimX agreement checked')
    report['bindings'] = {p.relative_to(ROOT).as_posix(): sha(p) for p in
                          (vectors, functional_path, work / 'build.json', work / 'inputs.json', Path(__file__))}
    report['run_record_sha256'] = hashlib.sha256(b''.join(
        (work / 'runs' / f'{o:04d}-c{c}' / 'record.json').read_bytes() for o in range(len(goldens)) for c in CLASSES)).hexdigest()
    identity = hashlib.sha256(json.dumps(report['bindings'], sort_keys=True).encode() + report['run_record_sha256'].encode()).hexdigest()
    destination = ROOT / 'grading/evidence/student-mini-v1/results' / identity
    destination.mkdir(parents=True, exist_ok=False)
    path = destination / 'results.json'
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(path=str(path), sha256=sha(path), counts=report['counts'], numeric_matches=report['numeric_matches'])))
    return 0 if report['counts']['FAIL'] == 0 else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='phase', required=True)
    b = sub.add_parser('build')
    b.add_argument('--boundary', type=Path, required=True)
    b.add_argument('--functional', type=Path, required=True)
    r = sub.add_parser('run')
    r.add_argument('--work', type=Path, required=True)
    r.add_argument('--shard', type=int, default=0)
    r.add_argument('--shards', type=int, default=1)
    r.add_argument('--ordinals', type=int, nargs='*')
    a = sub.add_parser('assemble')
    a.add_argument('--work', type=Path, required=True)
    a.add_argument('--vectors', type=Path, required=True)
    a.add_argument('--functional-results', type=Path, required=True)
    args = parser.parse_args()
    return dict(build=build, run=run, assemble=assemble)[args.phase](args)


if __name__ == '__main__':
    raise SystemExit(main())
