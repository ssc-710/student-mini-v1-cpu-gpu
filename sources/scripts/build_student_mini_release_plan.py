"""Write the explicit evidence plan consumed by assemble_student_mini_release.py.

Every input is named by path in a JSON file (reviewable before packaging).
Pass the specific evidence directories; nothing is discovered implicitly
except the fixed frozen inputs (golden vectors, spec, README, verifier) and,
when --cpu-rom-banks is omitted, the 25 ROM-bank runs bound by the CPU top run.

Physical evidence (plan keys physical_files / power_files / physical_aliases):
for every implementation the final files are listed, never an ODB.  DEF,
netlist, SPEF, logs and reports are packaged gzip-compressed (6_final.def.gz,
6_final.v.gz, 6_final.spef.gz, logs/*.log.gz), 6_final.sdc, config.mk and
completion.json are packaged as is.  Components:

  cpu/top, cpu/rom-bank-00 .. cpu/rom-bank-24          (platform + ROM-bank runs)
  gpu/top, gpu/<block design> x4, gpu/fullchip-sta,     (hierarchical GPU)
  gpu/partition
  accelerator-p1 .. accelerator-p3                      (profile.json, design/, raw/)
  power: cpu, gpu (gate-power work dirs), accelerator-pN (loads/)

Expected SHA-256 values are taken from each run's own completion/profile and
re-checked by the assembler while copying.  Files with identical content are
packaged once; the duplicates are recorded in physical_aliases.

Final layout example (run under WSL from the repository root):

  python3 scripts/build_student_mini_release_plan.py --out build/student-mini/release-plan.json \\
    --cpu-results CPU_RESULTS.json --cpu-protocol CPU_PROTOCOL.json \\
    --cpu-physical build/student-mini/platform-physical/<cpu-top-sha>/completion.json \\
    --cpu-power build/student-mini/cpu-gate-power/<sha>/completion.json \\
    --gpu-results GPU_RESULTS.json --gpu-protocol GPU_PROTOCOL.json \\
    --gpu-top build/student-mini/platform-physical/<gpu-top-sha>/completion.json \\
    --gpu-blocks build/student-mini/platform-physical/{<q0>,<q1>,<q2>,<q3>}/completion.json \\
    --gpu-sta build/student-mini/gpu-fullchip-sta/<sha>/completion.json \\
    --gpu-partition build/student-mini/gpu-partition/<sha>/completion.json \\
    --gpu-power build/student-mini/gpu-gate-power/<sha>/completion.json \\
    --acc-results P1.json P2.json P3.json --acc-raw P1.jsonl P2.jsonl P3.jsonl \\
    --acc-package build/student-mini/physical-packages/accelerator-p{1,2,3}/<sha> \\
    --acc-witness WITNESS.json --nano-candidate CANDIDATE.json --nano-batches B1.json B2.json \\
    --resources R1.json R2.json --sources sources.txt

  (--cpu-rom-banks build/student-mini/rom-bank-physical/<sha>/completion.json x25 may be given
  explicitly; --omit-accelerator-activity drops the per-seed activity.vcd.gz files, whose SHA-256
  stays recorded in profile.json, when the 1 GiB ZIP limit cannot otherwise be met; every omitted file is
  listed in plan key physical_files_omitted and from there in evidence-index.json and release.json.)
  A --reaudit platform run (completion field reaudit_of) is packaged with the original run's completion,
  inputs and logs (reaudit-of/, logs/reaudit-of/); config.mk is the DESIGN_CONFIG of the recorded make command.

Course mode (--course cpu-accelerator): the "CPU + 专用加速器" course (spec route A) is packaged on its
own: platforms cpu + accelerator (6 baselines, 4 implementations: CPU top + 25 ROM banks, accelerator-p1..p3).
No --gpu-* argument is accepted; the plan key "course" names the platforms, the implementations and the
excluded GPU platform (it belongs to the separate CPU+GPU course, spec route B).
Course mode (--course cpu-gpu): the "CPU + GPU" course (spec route B): platforms cpu + gpu (6 baselines,
2 implementations: CPU top + 25 ROM banks; hierarchical GPU = top + 4 quadrant blocks q0_LL..q3_UR + full-chip
STA + partition).  No --acc-* argument is accepted; --gpu-results, --gpu-protocol, --gpu-power and the GPU
physical evidence (--gpu-top/--gpu-blocks/--gpu-sta/--gpu-partition, or --gpu-physical) are required.  The
excluded accelerator belongs to the separate CPU+专用加速器 course (spec route A).
A course drops exactly the platforms it does not contain from the plan.  A GPU block run continued with
--eco-from (completion field eco_from) is packaged with its predecessor's completion and inputs (eco-from/)
and the chip-timing context SDC it was repaired against (eco-context/, completion field eco_context).
The default (no --course) is the unchanged three-platform release.  Optional inputs for either mode: --collect-environment (tool
versions of the binaries the evidence runs bound, checked by SHA-256, and the host configuration),
--memory-layout JSON, --resource-measurements JSON, --readme, --disclosure TEXT (repeatable).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform as host_platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ('cpu', 'gpu', 'accelerator')
# A course packages a subset of the platforms (grading/student-mini/spec.json "routes").
COURSES = {
    'cpu-accelerator': dict(
        id='cpu-accelerator', name='CPU + 专用加速器', spec_route='A', platforms=['cpu', 'accelerator'],
        implementations=['cpu', 'accelerator-p1', 'accelerator-p2', 'accelerator-p3'],
        implementation_components={'cpu': 'CPU top + 25 hardened ROM banks (cpu/top, cpu/rom-bank-00..24)',
                                   'accelerator-p1': 'accelerator P1', 'accelerator-p2': 'accelerator P2', 'accelerator-p3': 'accelerator P3'},
        package_name='student-mini-v1-cpu-accelerator',
        excluded_platforms={'gpu': 'Not part of this course: the GPU (Vortex) baselines, its hierarchical physical '
                                   'implementation, power and NanoChat session belong to the separate CPU+GPU course '
                                   '(spec route B) and are released in that course package. Not missing, not PASS.'}),
    'cpu-gpu': dict(
        id='cpu-gpu', name='CPU + GPU', spec_route='B', platforms=['cpu', 'gpu'],
        implementations=['cpu', 'gpu'],
        implementation_components={'cpu': 'CPU top + 25 hardened ROM banks (cpu/top, cpu/rom-bank-00..24)',
                                   'gpu': 'hierarchical GPU: top-level route run (gpu/top) + 4 hardened quadrant blocks '
                                          'q0_LL, q1_LR, q2_UL, q3_UR (gpu/vortex_physical_top_q0..q3), timed by the full-chip '
                                          'STA of the assembled netlists (gpu/fullchip-sta), partition gpu/partition'},
        package_name='student-mini-v1-cpu-gpu',
        excluded_platforms={'accelerator': 'Not part of this course: the dedicated accelerator (P1/P2/P3) baselines, its '
                                           'physical implementations, power and NanoChat session belong to the separate '
                                           'CPU+专用加速器 course (spec route A) and are released in that course package. '
                                           'Not missing, not PASS.'}),
}
# Arguments that carry a platform's evidence: a course accepts only those of its platforms.
PLATFORM_ARGS = {
    'gpu': ('gpu_results', 'gpu_protocol', 'gpu_physical', 'gpu_top', 'gpu_blocks', 'gpu_sta', 'gpu_partition', 'gpu_power'),
    'accelerator': ('acc_results', 'acc_raw', 'acc_package', 'acc_witness'),
}
# Arguments a package must name for each included platform (GPU outside course mode: --gpu-results only, as before).
REQUIRED_ARGS = {'accelerator': ('acc_results', 'acc_raw', 'acc_package', 'acc_witness')}
COURSE_REQUIRED_ARGS = {'gpu': ('gpu_results', 'gpu_protocol', 'gpu_power')}
GOLDEN = ROOT / 'grading/evidence/student-mini-v1/golden/ae10e98c1a2167d4281eb8bc6f60d218e8e57d83e5d52f0e48df5bc50d8d6fc1'

PROTOCOL_INTERFACES = {
    'accelerator': 'cocotb testbench at the accelerator ports: MINI-31 seeded random memory-ready deassertion on the DMA port; '
                   'MINI-32 command response held N cycles before rsp_ready (stability asserted); MINI-33 accepted command, '
                   'reset injected after 20 silent cycles, silence checked, command reissued',
    'gpu': 'vortex_physical_top ports: MINI-31 seeded stalls on memory request acceptance and response delivery (both ports); '
           'MINI-32 host command response (host_rsp_ready_i) held N cycles per response; MINI-33 reset after 64 busy cycles of '
           'the first launch, all DCR writes replayed, launch reissued; stability of every DUT-held handshake checked',
    'cpu': 'CPU die ports: the UART result stream (serial_source valid/ready) for MINI-31 seeded stalls and MINI-32 per-byte '
           'holds, asic_reset_i for MINI-33 (reset 2000 cycles into the record, re-execution after reboot); DFI is a '
           'fixed-latency PHY interface without handshake. The target record is placed in image slot 0',
}
POWER_METHOD = ('Routed netlist (6_final.v) compiled from Liberty cell functions into a zero-delay two-state event-driven '
                'gate model (tools/gatesim, scripts/student_mini_gatesim.py); OpenRAM macros modelled natively; driven by the '
                'cycle-by-cycle port trace of the RTL execution of the same workload; every recorded output cycle compared. '
                'Pin activity (toggle count, high time) per window written as SAIF and annotated in OpenROAD with the final '
                'SDC and SPEF (report_power, tt 25C 1.8V). Accelerators: Icarus gate simulation VCD (existing packages). '
                'Engine cross-checked against Verilator SAIF on a ROM bank: identical toggles, 4.30 vs 4.31 mW.')

# Packaged gzip-compressed (name + '.gz'); everything else is copied as is.  ODB is never packaged.
COMPRESS = ('.def', '.v', '.spef', '.log', '.rpt', '.saif', '.vcd', '.lef', '.lib', '.txt', '.hex')
NEVER = ('.odb',)
SKIP_DIRS = frozenset(('program', 'power-libs', '__pycache__'))
SKIP_NAMES = frozenset(('gatesim', 'heartbeat.json'))


def nano_sessions(batches, candidate, platforms=PLATFORMS):
    """session.json per platform from batch completions; questions not covered by a batch are
    taken from the session evidence directories (same question, passing status, exact tokens)."""
    expected = {q['question']: q['tokens'] for q in json.loads(Path(candidate).read_text(encoding='utf-8'))['quality']['ptq_exact']}
    found = {p: {} for p in platforms}
    for path in batches:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        for q in value.get('questions', []):
            for platform in ('gpu', 'accelerator'):
                if platform in found and isinstance(q.get(platform), dict) and q[platform].get('path'):
                    found[platform].setdefault(q['question'], q[platform]['path'])
            if 'cpu' in found and value.get('platform') == 'cpu' and isinstance(q.get('session'), dict) and q['session'].get('path'):
                found['cpu'].setdefault(q['question'], q['session']['path'])
    evidence = ROOT / 'grading/evidence/student-mini-v1'
    for directory, platform in (('selected-native-sessions', None), ('selected-native-accelerator-sessions', 'accelerator')):
        for session in sorted((evidence / directory).glob('*/session.json')):
            value = json.loads(session.read_text(encoding='utf-8'))
            plat = value.get('platform')
            q = value.get('question')
            if plat in ('gpu', 'accelerator') and plat in found and q in expected and q not in found[plat] and value.get('status', '').endswith('STAGE_PASS')                     and [r['token'] for r in value.get('records', [])] == expected[q]:
                found[plat][q] = str(session)
    return {p: [found[p][q] for q in expected if q in found[p]] for p in found}


# ---------------------------------------------------------------- physical evidence files

def host_path(value):
    """Completion files record WSL paths; map /mnt/<drive>/ when the builder runs on Windows."""
    text = str(value)
    if os.name == 'nt':
        found = re.match(r'^/mnt/([a-zA-Z])/(.*)$', text)
        if found:
            return Path(f'{found.group(1).upper()}:/{found.group(2)}')
    return Path(text)


def completion_path(value):
    path = Path(value).resolve()
    return path / 'completion.json' if path.is_dir() else path


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def stream_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Evidence:
    """section ('physical' | 'power') -> component -> packaged name -> {source, sha256, compress}."""

    def __init__(self):
        self.files = {'physical': {}, 'power': {}}
        self.missing = []
        self.omitted = []

    def add(self, section, component, name, source, sha256=None):
        source = Path(source)
        if source.suffix in NEVER:
            return
        if not source.is_file():
            self.missing.append(f'{section}/{component}/{name}: {source}')
            return
        compress = source.suffix in COMPRESS and not source.name.endswith('.gz')
        name = name + '.gz' if compress else name
        if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name:
            raise ValueError(f'unsafe package name {name}')
        files = self.files[section].setdefault(component, {})
        if name in files:
            if files[name]['source'] == str(source):
                return
            stem, dot, rest = name.partition('.')
            index = 2
            while f'{stem}-{index}{dot}{rest}' in files:
                index += 1
            name = f'{stem}-{index}{dot}{rest}'
        files[name] = dict(source=str(source), sha256=sha256, compress=compress)

    def deduplicate(self):
        """Identical content is packaged once; later copies become aliases of the first."""
        entries = [(section, component, name, entry) for section in ('physical', 'power')
                   for component, files in self.files[section].items() for name, entry in files.items()]
        by_size = {}
        for item in entries:
            by_size.setdefault(Path(item[3]['source']).stat().st_size, []).append(item)
        aliases = {}
        for group in by_size.values():
            if len(group) < 2:
                continue
            first = {}
            for section, component, name, entry in group:
                digest = entry['sha256'] or stream_sha(entry['source'])
                entry['sha256'] = digest
                key = (digest, entry['compress'])
                published = f'{section}/{component}/{name}'
                if key in first:
                    aliases[published] = first[key]
                    del self.files[section][component][name]
                else:
                    first[key] = published
        return aliases


def artifacts_of(done, base=None):
    """completion 'artifacts' as {host path: sha256}; relative keys are taken against base."""
    out = {}
    for key, digest in (done.get('artifacts') or {}).items():
        path = host_path(key)
        if not path.is_absolute() and base is not None:
            path = base / key
        out[str(path)] = digest
    return out


def design_configs(done):
    """DESIGN_CONFIG=... of the make commands the run recorded (the config the flow actually used)."""
    found = []
    for command in done.get('command') or []:
        for arg in command if isinstance(command, list) else []:
            if isinstance(arg, str) and arg.startswith('DESIGN_CONFIG=') and arg[14:] not in found:
                found.append(arg[14:])
    return [host_path(p) for p in found]


def config_files(evidence, component, done, work):
    """config.mk (and its sibling constraint/io/placement files) of the run that produced the result.

    The DESIGN_CONFIG recorded in the run's make command comes first; a --reaudit run has no config of its
    own (its results were produced by the run named in reaudit_of), and the config stage's config.mk that the
    run binds is only the template the runner derived its own config from."""
    configs = design_configs(done)
    if len(configs) > 1:
        raise ValueError(f'{component}: several DESIGN_CONFIG values in one run: {configs}')
    candidates = configs + [work / 'config.mk']
    for key in ('reaudit_of', 'resumed_from'):
        if done.get(key):
            candidates.append(host_path(done[key]) / 'config.mk')
    candidates += [host_path(p) for p in (done.get('bindings') or {}) if p.endswith('/config.mk') and '/flow/platforms/' not in p]
    for config in candidates:
        if config.is_file():
            evidence.add('physical', component, 'config/config.mk', config, (done.get('bindings') or {}).get(str(config)))
            for sibling in ('constraint.sdc', 'io.tcl', 'macro-placement.tcl', 'pdn.tcl'):
                if (config.parent / sibling).is_file():
                    evidence.add('physical', component, f'config/{sibling}', config.parent / sibling)
            return
    evidence.missing.append(f'physical/{component}/config/config.mk')


def route_run(evidence, component, completion):
    """Platform route run or ROM-bank run: final views, logs, config and completion."""
    completion = completion_path(completion)
    done = load(completion)
    work = completion.parent
    results = host_path(done['result_directory'])
    artifacts = artifacts_of(done)
    evidence.add('physical', component, 'completion.json', completion)
    if (work / 'inputs.json').is_file():
        evidence.add('physical', component, 'inputs.json', work / 'inputs.json')
    for suffix in ('def', 'v', 'spef', 'sdc'):
        path = results / f'6_final.{suffix}'
        evidence.add('physical', component, f'6_final.{suffix}', path, artifacts.get(str(path)))
    for path, digest in artifacts.items():
        path = Path(path)
        if path.name.startswith('6_final.') or path.suffix in NEVER:
            continue
        sub = 'abstract' if path.suffix in ('.lef', '.lib') else 'logs'
        evidence.add('physical', component, f'{sub}/{path.name}', path, digest)
    for log in sorted(work.glob('*.log')):
        evidence.add('physical', component, f'logs/{log.name}', log)
    if done.get('reaudit_of'):
        # --reaudit: only audit + sign-off were rerun on the unchanged results of the original run, whose
        # completion (with its failed audit), inputs and route logs live in the directory named by reaudit_of
        origin = host_path(done['reaudit_of'])
        bindings = done.get('bindings') or {}
        evidence.add('physical', component, 'reaudit-of/completion.json', origin / 'completion.json',
                     bindings.get(f"{done['reaudit_of']}/completion.json"))
        if (origin / 'inputs.json').is_file():
            evidence.add('physical', component, 'reaudit-of/inputs.json', origin / 'inputs.json')
        packaged = {e['source'] for e in evidence.files['physical'].get(component, {}).values()}
        for log in sorted(origin.glob('*.log')):
            if str(log) not in packaged:
                evidence.add('physical', component, f'logs/reaudit-of/{log.name}', log)
    if done.get('eco_from'):
        # --eco-from: a post-route ECO continued on the predecessor's routed result (same ORFS result directory,
        # whose 6_final.* the ECO run rewrote); the predecessor's completion, inputs and logs are its lineage
        origin = host_path(done['eco_from'])
        bindings = done.get('bindings') or {}
        evidence.add('physical', component, 'eco-from/completion.json', origin / 'completion.json',
                     bindings.get(f"{done['eco_from']}/completion.json"))
        if (origin / 'inputs.json').is_file():
            evidence.add('physical', component, 'eco-from/inputs.json', origin / 'inputs.json')
        packaged = {e['source'] for e in evidence.files['physical'].get(component, {}).values()}
        for log in sorted(origin.glob('*.log')):
            if str(log) not in packaged:
                evidence.add('physical', component, f'logs/eco-from/{log.name}', log)
    if done.get('eco_context'):
        # chip-timing context SDC overlay the ECO repaired against, and the completion of the run that derived it
        context = host_path(done['eco_context'])
        evidence.add('physical', component, f'eco-context/{context.name}', context, (done.get('bindings') or {}).get(done['eco_context']))
        if (context.parent / 'completion.json').is_file():
            evidence.add('physical', component, 'eco-context/completion.json', context.parent / 'completion.json')
    if done.get('reports_directory') and (host_path(done['reports_directory']) / '6_finish.rpt').is_file():
        evidence.add('physical', component, 'logs/6_finish.rpt', host_path(done['reports_directory']) / '6_finish.rpt')
    config_files(evidence, component, done, work)
    return done


def directory_files(evidence, section, component, directory, prefix='', expected=None):
    directory = Path(directory)
    for path in sorted(directory.rglob('*')):
        rel = path.relative_to(directory)
        if not path.is_file() or path.name in SKIP_NAMES or any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        evidence.add(section, component, prefix + rel.as_posix(), path, (expected or {}).get(rel.as_posix()))


def rom_banks_of(top_completion):
    """The ROM-bank completions bound by the CPU top run (directly or via its top-physical-config stage)."""
    found, seen = {}, set()

    def scan(bindings, depth):
        for key in bindings:
            path = host_path(key)
            if path.parent.parent.name == 'rom-bank-physical' and path.name == 'completion.json' and path.is_file():
                found[str(path)] = path
            elif depth and path.parent.parent.name == 'cpu-top-physical-config':
                # the top binds the config stage's config.mk; that stage's completion binds the ROM-bank runs
                stage = path.parent / 'completion.json'
                if stage.is_file() and str(stage) not in seen:
                    seen.add(str(stage))
                    scan(load(stage).get('bindings') or {}, depth - 1)

    scan(load(top_completion).get('bindings') or {}, 2)
    return list(found.values())


def physical_evidence(args, evidence):
    if args.cpu_physical:
        route_run(evidence, 'cpu/top', args.cpu_physical)
        banks = [completion_path(p) for p in args.cpu_rom_banks] if args.cpu_rom_banks else rom_banks_of(completion_path(args.cpu_physical))
        indexed = sorted((load(p).get('bank'), p) for p in banks)
        if [i for i, _ in indexed] != list(range(25)):
            print(f'warning: ROM banks {[i for i, _ in indexed]} are not exactly 0..24', file=sys.stderr)
        for index, path in indexed:
            route_run(evidence, f'cpu/rom-bank-{index:02d}', path)
    if args.gpu_top:
        route_run(evidence, 'gpu/top', args.gpu_top)
    for block in args.gpu_blocks or []:
        done = load(completion_path(block))
        route_run(evidence, f'gpu/{host_path(done["result_directory"]).parent.name}', block)
    if args.gpu_physical:
        route_run(evidence, 'gpu/top', args.gpu_physical)
    if args.gpu_sta:
        sta = completion_path(args.gpu_sta)
        for name in ('completion.json', 'fullchip.rpt', 'sta.log'):
            evidence.add('physical', 'gpu/fullchip-sta', name, sta.parent / name)
    if args.gpu_partition:
        part = completion_path(args.gpu_partition)
        directory_files(evidence, 'physical', 'gpu/partition', part.parent, expected=load(part).get('artifacts'))
    for platform, power in (('cpu', args.cpu_power), ('gpu', args.gpu_power)):
        if power:
            power = completion_path(power)
            directory_files(evidence, 'power', platform, power.parent, expected=load(power).get('artifacts'))
    for op, package in zip(('p1', 'p2', 'p3'), args.acc_package or []):
        package = Path(package).resolve()
        profile = load(package / 'profile.json')
        expected = {k: v['sha256'] for k, v in (profile.get('package_files') or {}).items()}
        component = f'accelerator-{op}'
        evidence.add('physical', component, 'profile.json', package / 'profile.json')
        directory_files(evidence, 'physical', component, package / 'design', 'design/', {k[7:]: v for k, v in expected.items() if k.startswith('design/')})
        directory_files(evidence, 'physical', component, package / 'raw', 'raw/', {k[4:]: v for k, v in expected.items() if k.startswith('raw/')})
        loads = package / 'loads'
        for path in sorted(loads.rglob('*')):
            rel = path.relative_to(package).as_posix()
            if not path.is_file():
                continue
            if args.omit_accelerator_activity and path.name.startswith('activity.'):
                # not packaged, but recorded: the evidence index and release.json list every omitted file
                evidence.omitted.append(dict(path=f'power/{component}/{rel}', source=str(path), sha256=expected.get(rel),
                                             bytes=path.stat().st_size, reason='--omit-accelerator-activity (1 GiB ZIP limit); '
                                             'SHA-256 bound in profile.json package_files and loads[].activity_sha256'))
                continue
            evidence.add('power', component, rel, path, expected.get(rel))


# ---------------------------------------------------------------- tool versions and host (--collect-environment)

VERSION_COMMANDS = {'openroad': ['-version'], 'openroad-drtbatch': ['-version'], 'yosys': ['-V'], 'iverilog': ['-V'],
                    'vvp': ['-V'], 'verilator': ['--version'], 'verilator_bin': ['--version'], 'sta': ['-version'],
                    'python3': ['--version'], 'python': ['--version'], 'g++': ['--version'], 'gcc': ['--version']}


def run_text(command, timeout=60):
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        return dict(command=command, error=str(error))
    text = (done.stdout or done.stderr or '').strip().splitlines()
    return dict(command=command, exit_code=done.returncode, output=text[:3])


def evidence_json_paths(plan):
    """JSON evidence files named by the plan's platform entries (results, protocol, physical, power, banks, packages, Nano)."""
    out = []

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str) and value.endswith('.json'):
            out.append(Path(value))
        elif isinstance(value, str) and Path(value).is_dir() and (Path(value) / 'profile.json').is_file():
            out.append(Path(value) / 'profile.json')

    for key in [p for p in PLATFORMS if p in plan] + ['nano_candidate', 'nano']:
        walk(plan.get(key))
    return [p for p in dict.fromkeys(out) if p.is_file()]


def collect_tools(plan):
    """Tool binaries and flow/PDK files the evidence runs bound (path -> SHA-256 recorded by the run), the current
    SHA-256 of that path (same binary or not) and its version output; ORFS / OpenROAD source commits."""
    bound = {}
    for path in evidence_json_paths(plan):
        try:
            value = load(path)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        pairs = list((value.get('bindings') or {}).items()) + list((value.get('external_tool_binary_sha256') or {}).items())
        for key, digest in pairs:
            if not isinstance(digest, str) or str(ROOT) in key or key.startswith(('C:', 'c:')) or '/flow/results/' in key \
                    or '/flow/logs/' in key or '/flow/objects/' in key:
                continue
            bound.setdefault(key, {}).setdefault(digest, set()).add(str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path))
    tools, flow = [], []
    for key in sorted(bound):
        path = host_path(key)
        current = stream_sha(path) if path.is_file() else None
        entry = dict(path=key, recorded_sha256=sorted(bound[key]), current_sha256=current,
                     current_matches_recorded=current in bound[key], bound_by=sorted({e for s in bound[key].values() for e in s})[:6],
                     bound_by_count=len({e for s in bound[key].values() for e in s}))
        if '/bin/' in key or path.name in VERSION_COMMANDS:
            if path.name in VERSION_COMMANDS and path.is_file() and os.name != 'nt':
                entry['version'] = run_text([str(path)] + VERSION_COMMANDS[path.name])
            tools.append(entry)
        else:
            flow.append(entry)
    sources = {}
    for key in bound:
        found = re.match(r'^(.*/orfs[^/]*)/flow/', key)
        if found:
            sources.setdefault('orfs', found.group(1))
    for name, directory in list(sources.items()):
        base = host_path(directory)
        sources[name] = dict(path=directory, commit=run_text(['git', '-C', str(base), 'rev-parse', 'HEAD']),
                             openroad_submodule_commit=run_text(['git', '-C', str(base / 'tools/OpenROAD'), 'rev-parse', 'HEAD']),
                             yosys_submodule_commit=run_text(['git', '-C', str(base / 'tools/yosys'), 'rev-parse', 'HEAD']))
    lock = load(ROOT / 'third_party/sources.lock.json')
    # source provenance of the tool binaries / flow tree from the passing source audits (audit_student_mini_*_source.py)
    provenance = []
    for audit in sorted(ROOT.glob('build/student-mini/*source*audit*/audit.json')):
        try:
            value = load(audit)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not str(value.get('status', '')).endswith('PASS'):
            continue
        binaries = {k: v for k, v in (value.get('bindings') or {}).items() if k in bound or k.endswith('/bin/openroad')}
        provenance.append(dict(audit=str(audit.relative_to(ROOT)), sha256=stream_sha(audit), schema=value.get('schema'), status=value.get('status'),
                               source_commit=value.get('source_commit'), source_url=value.get('source_url'),
                               source_repositories=value.get('source_repositories'), declared_tool_gitlinks=value.get('declared_tool_gitlinks'),
                               installed_binary=(value.get('install_transform') or {}).get('replay_sha256'), binaries=binaries,
                               limitations=value.get('limitations'), scope=value.get('scope')))
    return dict(method='Every non-repository file bound (path -> SHA-256) by the packaged evidence runs; current SHA-256 '
                       're-measured at plan time and the version printed by that binary; ORFS/OpenROAD commits from git.',
                binaries=tools, flow_and_pdk_files=flow, sources=sources, provenance=provenance,
                sources_lock=dict(path='third_party/sources.lock.json', sha256=stream_sha(ROOT / 'third_party/sources.lock.json'),
                                  entries=[{k: s.get(k) for k in ('name', 'commit', 'version', 'required_for')} for s in lock.get('sources', [])],
                                  patches=lock.get('patches')))


def collect_host(windows_version=None):
    """Development-machine configuration as seen by the run environment (WSL2), measured at plan time."""
    info = dict(collected_by='build_student_mini_release_plan.py --collect-environment', python=sys.version.split()[0],
                machine=host_platform.machine(), uname=' '.join(host_platform.uname()))
    if os.name != 'nt':
        cpu = run_text(['lscpu'])
        try:
            lines = subprocess.run(['lscpu'], capture_output=True, text=True, timeout=30).stdout.splitlines()
            fields = {l.split(':', 1)[0].strip(): l.split(':', 1)[1].strip() for l in lines if ':' in l}
            info['cpu'] = {k: fields.get(k) for k in ('Model name', 'Architecture', 'CPU(s)', 'Thread(s) per core', 'Core(s) per socket',
                                                       'Socket(s)', 'Hypervisor vendor', 'Virtualization type')}
        except (OSError, subprocess.SubprocessError):
            info['cpu'] = cpu
        try:
            meminfo = dict(l.split(':', 1) for l in Path('/proc/meminfo').read_text().splitlines() if ':' in l)
            info['memory_total_bytes'] = int(meminfo['MemTotal'].split()[0]) * 1024
            info['swap_total_bytes'] = int(meminfo['SwapTotal'].split()[0]) * 1024
        except (OSError, KeyError, ValueError):
            pass
        info['logical_cpus'] = os.cpu_count()
        try:
            release = dict(l.split('=', 1) for l in Path('/etc/os-release').read_text().splitlines() if '=' in l)
            info['os'] = release.get('PRETTY_NAME', '').strip('"')
        except OSError:
            pass
        info['kernel'] = host_platform.release()
        info['wsl'] = 'microsoft' in host_platform.release().lower()
    if windows_version:
        info['windows'] = windows_version
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cpu-results', required=True)
    parser.add_argument('--cpu-protocol')
    parser.add_argument('--cpu-physical', help='completion.json (or work dir) of the CPU top platform-physical run')
    parser.add_argument('--cpu-rom-banks', nargs='*', help='the 25 ROM-bank completion.json files (default: those bound by the CPU top)')
    parser.add_argument('--cpu-power')
    parser.add_argument('--course', choices=sorted(COURSES), help='package one course (default: the full three-platform release)')
    parser.add_argument('--gpu-results', help='required without --course')
    parser.add_argument('--gpu-protocol')
    parser.add_argument('--gpu-physical', help='single-run GPU implementation (legacy; use --gpu-top/--gpu-blocks/--gpu-sta)')
    parser.add_argument('--gpu-top', help='completion.json of the GPU top-level route run')
    parser.add_argument('--gpu-blocks', nargs=4, help='completion.json of the four GPU block route runs')
    parser.add_argument('--gpu-sta', help='gpu-fullchip-sta/<sha>/completion.json')
    parser.add_argument('--gpu-partition', help='gpu-partition/<sha>/completion.json')
    parser.add_argument('--gpu-power')
    parser.add_argument('--acc-results', nargs=3, help='required unless the course excludes the accelerator')
    parser.add_argument('--acc-raw', nargs=3, help='required unless the course excludes the accelerator')
    parser.add_argument('--acc-package', nargs=3, help='required unless the course excludes the accelerator')
    parser.add_argument('--acc-witness', help='required unless the course excludes the accelerator')
    parser.add_argument('--omit-accelerator-activity', action='store_true',
                        help='do not package loads/seed-N/activity.vcd.gz (their SHA-256 remains in profile.json)')
    parser.add_argument('--no-physical-files', action='store_true', help='plan without physical/power evidence files')
    parser.add_argument('--nano-candidate', required=True)
    parser.add_argument('--nano-batches', nargs='*', default=[], help='Nano batch completion.json files (GPU/accelerator and CPU)')
    parser.add_argument('--resources', nargs='*', default=[])
    parser.add_argument('--sources', type=Path, help='text file: one repo-relative source path per line')
    parser.add_argument('--boundary-note', default='')
    parser.add_argument('--readme', type=Path, help='package README (default integration/student-mini/release/README.md)')
    parser.add_argument('--collect-environment', action='store_true',
                        help='record tool versions (binaries bound by the evidence runs, SHA-checked) and the host configuration')
    parser.add_argument('--windows-version', help='host Windows version string (cmd /c ver), recorded with --collect-environment')
    parser.add_argument('--memory-layout', type=Path, help='JSON: memory layout derived from the source files it cites (SPEC.json memory_layout)')
    parser.add_argument('--resource-measurements', type=Path, help='JSON: dependency size / temporary disk measurements (data/resources)')
    parser.add_argument('--nano-model-card', type=Path, help='JSON model card of the accepted Nano candidate (data/nano/model-card.json)')
    parser.add_argument('--disclosure', action='append', default=[], help='free-text disclosure item for release.json (repeatable)')
    parser.add_argument('--tool-note', action='append', default=[], help='tool provenance note recorded in SPEC.json tools.notes (repeatable)')
    args = parser.parse_args()
    course = COURSES.get(args.course)
    platforms = course['platforms'] if course else list(PLATFORMS)
    flag = lambda k: '--' + k.replace('_', '-')
    for platform, keys in PLATFORM_ARGS.items():
        given = [k for k in keys if getattr(args, k)]
        if platform not in platforms and given:
            parser.error(f"--course {args.course} packages {course['platforms']} only; {platform} arguments not accepted: {given}")
    for platform in platforms:
        missing = [flag(k) for k in REQUIRED_ARGS.get(platform, ()) + (COURSE_REQUIRED_ARGS.get(platform, ()) if course else ())
                   if not getattr(args, k)]
        if missing:
            parser.error(f"{' '.join(missing)} required{f' for --course {args.course}' if course else ''}")
    if not course and not args.gpu_results:
        parser.error('--gpu-results is required without --course')
    if course and 'gpu' in platforms and not (args.gpu_physical or (args.gpu_top and args.gpu_blocks and args.gpu_sta and args.gpu_partition)):
        parser.error(f'--course {args.course}: GPU physical evidence required (--gpu-top --gpu-blocks --gpu-sta --gpu-partition, or --gpu-physical)')
    if args.gpu_physical and (args.gpu_top or args.gpu_blocks or args.gpu_sta):
        parser.error('--gpu-physical (single run) and --gpu-top/--gpu-blocks/--gpu-sta (hierarchical) are exclusive')
    a = lambda p: str(Path(p).resolve()) if p else None
    c = lambda p: str(completion_path(p)) if p else None
    if args.gpu_top or args.gpu_blocks or args.gpu_sta:
        gpu_physical = dict(top=c(args.gpu_top), blocks=[c(p) for p in args.gpu_blocks or []], sta=c(args.gpu_sta),
                            partition=c(args.gpu_partition))
    else:
        gpu_physical = c(args.gpu_physical)
    cpu = dict(results=a(args.cpu_results), protocol=a(args.cpu_protocol), physical=c(args.cpu_physical), power=c(args.cpu_power))
    if args.cpu_physical:
        banks = [completion_path(p) for p in args.cpu_rom_banks] if args.cpu_rom_banks else rom_banks_of(completion_path(args.cpu_physical))
        cpu['rom_banks'] = [str(p) for _, p in sorted((load(p).get('bank'), p) for p in banks)]
    plan = dict(vectors=str(GOLDEN / 'vectors.jsonl'), golden_manifest=str(GOLDEN / 'manifest.json'),
                spec=str(ROOT / 'grading/student-mini/spec.json'),
                cpu=cpu,
                gpu=dict(results=a(args.gpu_results), protocol=a(args.gpu_protocol), physical=gpu_physical, power=c(args.gpu_power)),
                accelerator=dict(witness=a(args.acc_witness), **{op: dict(results=a(r), raw=a(w), package=a(k)) for op, r, w, k in
                                                                 zip(('p1', 'p2', 'p3'), args.acc_results or [], args.acc_raw or [],
                                                                     args.acc_package or [])}),
                nano_candidate=a(args.nano_candidate),
                nano=nano_sessions(args.nano_batches, args.nano_candidate, platforms),
                resources=[a(p) for p in args.resources],
                sources=[l.strip() for l in args.sources.read_text().splitlines() if l.strip()] if args.sources else [],
                protocol_interfaces={p: v for p, v in PROTOCOL_INTERFACES.items() if p in platforms}, power_method=POWER_METHOD,
                readme=str((args.readme or ROOT / 'integration/student-mini/release/README.md').resolve()),
                verifier=str(ROOT / 'scripts/student_mini_release_verify.py'),
                boundary_note=args.boundary_note)
    if course:
        for platform in PLATFORMS:
            if platform not in platforms:
                del plan[platform]
        plan['course'] = course
    for key, path in (('memory_layout', args.memory_layout), ('resource_measurements', args.resource_measurements),
                      ('nano_model_card', args.nano_model_card)):
        if path:
            load(path)  # must be valid JSON
            plan[key] = str(path.resolve())
    if args.disclosure:
        plan['disclosures'] = args.disclosure
    if args.collect_environment:
        plan['tools'] = dict(collect_tools(plan), notes=args.tool_note)
        plan['host'] = collect_host(args.windows_version)
    if not args.no_physical_files:
        evidence = Evidence()
        physical_evidence(args, evidence)
        plan['physical_aliases'] = evidence.deduplicate()
        plan['physical_files'] = evidence.files['physical']
        plan['power_files'] = evidence.files['power']
        plan['physical_files_missing'] = evidence.missing
        plan['physical_files_omitted'] = evidence.omitted
        total = sum(Path(e['source']).stat().st_size for s in evidence.files.values() for f in s.values() for e in f.values())
        print(json.dumps(dict(components=sum(len(s) for s in evidence.files.values()),
                              files=sum(len(f) for s in evidence.files.values() for f in s.values()),
                              aliases=len(plan['physical_aliases']), source_bytes=total, missing=evidence.missing[:20],
                              omitted=len(evidence.omitted), omitted_bytes=sum(o['bytes'] for o in evidence.omitted))),
              file=sys.stderr)
    args.out.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(args.out)


if __name__ == '__main__':
    main()
