"""Complete ORFS implementation (synthesis -> finish) of a frozen platform netlist.

One make invocation from synthesis to the final database, at NUM_CORES=2, so
the result is reproducible on the student machine profile. The design config,
macro placement and every referenced input are copied/bound by SHA before the
run and re-verified afterwards.  Acceptance requires 10 ns setup/hold closure,
zero DRC and antenna violations, every connected macro pin accessed and routed,
and physical VDD/VSS grid connectivity.  Power/activity is a separate stage.
No KLayout is installed: the GDS merge is not part of the deliverable (DEF,
netlist, SDC, SPEF, logs), so `finish` runs with GDS_FINAL_FILE empty.

Antenna repair: ORFS repeats repair_antennas + detailed_route inside the route
stage, where the second router starts on top of the first one's memory and the
process outgrows the 8 GiB budget.  The route stage therefore runs one detailed
route (SKIP_ANTENNA_REPAIR_POST_DRT=1); each repair round then runs in its own
OpenROAD process (integration/student-mini/antenna_round.tcl), its result kept
only with zero DRC, and the flow continues to `finish`.  DRC and antenna sign-off
use the accepted round results and an antenna check of the final database.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.audit_student_mini_route import check_metrics

FLOW = Path('/home/soclab/src/orfs-clean-aabf2a/flow')
# OpenROAD of the locked revision with third_party/patches/openroad-drt-batch-size.patch: detailed
# routing keeps every routed worker of a batch (1024) until the batch commits, which sets the peak
# memory independent of the thread count; DRT_BATCH_SIZE workers per batch keep the GPU blocks and
# the antenna rounds far below 8 GiB (LL: iteration-0 peak 8.73 -> 4.08 GB, identical violations).
OPENROAD = Path('/home/soclab/.local/bin/openroad-drtbatch')
OPENROAD_PATCH = Path(__file__).resolve().parents[1] / 'third_party/patches/openroad-drt-batch-size.patch'
DRT_BATCH_SIZE = '64'
YOSYS = Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
# Antenna rounds run with jemalloc: glibc malloc fragmentation pushes the incremental re-route over
# 8 GiB (CPU: glibc 8.44 GB, tcmalloc 7.51 GB, jemalloc 7.30 GB peak; identical routing result).
JEMALLOC = Path('/usr/lib/x86_64-linux-gnu/libjemalloc.so.2')
STAGES = ('1_2_yosys', '2_1_floorplan', '2_2_floorplan_macro', '2_3_floorplan_tapcell', '2_4_floorplan_pdn',
          '3_3_place_gp', '3_4_place_resized', '3_5_place_dp', '4_1_cts', '5_1_grt', '5_2_route', '5_3_fillcell',
          '6_report')


def config_inputs(text):
    """Every absolute path named in an export line must be a bound input file."""
    paths = []
    for line in text.splitlines():
        if not line.startswith('export '):
            continue
        for token in line.split('=', 1)[1].split():
            if token.startswith('/') and not token.startswith(str(FLOW)):
                paths.append(Path(token))
    return paths


def last_metric(path, key):
    """OpenROAD JSON metric files can repeat keys; the final occurrence is the final value."""
    values = re.findall(r'"' + re.escape(key) + r'"\s*:\s*([-+0-9.eE]+|null)', path.read_text())
    if not values or values[-1] == 'null':
        return None
    return float(values[-1])


def post_route_eco(args, work, results, reports, route_odb, config_text, max_layer, heartbeat, started):
    """Post-route timing ECO passes on the accepted route database (--eco-from), each step in its own process:
    post_route_eco.tcl (repair on calibrated global-route parasitics, liberty + STA), detail_route_fresh.tcl
    (re-route of the changed nets, no liberty) and post_route_timing.tcl (OpenRCX extraction, timed on the
    written-back SPEF like ORFS 6_final.spef).  The repair also delays the clock of register-to-register capture
    flops it could not close (useful_skew_eco.tcl), and a quadrant block's chip-level ports, unconstrained in its
    budget SDC, are timed against the GPU I/O constraint (eco_chip_io.tcl) by the repair and the pass timing.
    A later pass whose repair or detailed route fails leaves the last accepted route database in place.
    A pass is kept only with zero DRC and no new hold violation, when the worst register-to-register setup slack
    (the paths inside the block) or the worst overall setup slack (with the boundary-budget I/O paths) improves
    while the other drops by at most 0.02 ns; passes stop at the first pass that is not kept, or once setup and
    hold are met."""
    platform = FLOW / 'platforms/sky130hd'
    extra_libs = re.search(r'^export ADDITIONAL_LIBS = (.*)$', config_text, re.M)
    libs = [str(platform / 'lib/sky130_fd_sc_hd__tt_025C_1v80.lib')] + (extra_libs.group(1).split() if extra_libs else [])
    dont_use = re.search(r'export DONT_USE_CELLS \+= ((?:.*\\\n)*.*)', (platform / 'config.mk').read_text())
    env = dict(PATH='/usr/bin:/bin', LD_PRELOAD=str(JEMALLOC), STUDENT_MINI_LIBS=' '.join(libs),
               STUDENT_MINI_SDC=str(results / '5_1_grt.sdc'), STUDENT_MINI_PLATFORM_DIR=str(platform),
               STUDENT_MINI_DONT_USE=' '.join(dont_use.group(1).replace('\\', ' ').split()),
               STUDENT_MINI_MAX_LAYER=max_layer, STUDENT_MINI_DRT_BATCH_SIZE=DRT_BATCH_SIZE,
               STUDENT_MINI_ECO_CHIP_IO='1' if args.platform == 'gpu-block' else '0')

    def tool(script, log_name, stage, extra):
        with (work / log_name).open('x') as log:
            proc = subprocess.Popen(['/usr/bin/time', '-v', str(OPENROAD), '-exit', '-no_splash', '-threads', '2',
                                     str(ROOT / 'integration/student-mini' / script)],
                                    cwd=work, env={**env, **extra}, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            while proc.poll() is None:
                heartbeat(stage)
                if time.monotonic() - started > args.timeout:
                    proc.terminate()
                    proc.wait(60)
                    raise TimeoutError(f'{stage} exceeded {args.timeout} s')
                time.sleep(20)
        text = (work / log_name).read_text(errors='replace')
        peak = re.findall(r'Maximum resident set size \(kbytes\): (\d+)', text)
        return proc.returncode, text, int(peak[-1]) * 1024 if peak else None

    def timing(odb, tag):
        spef = results / f'5_2_route.eco-timing-{tag}.spef'
        code, text, peak = tool('post_route_timing.tcl', f'eco-timing-{tag}.log', f'eco-timing-{tag}',
                                dict(STUDENT_MINI_ODB=str(odb), STUDENT_MINI_SPEF=str(spef)))
        found = re.search(r'^STUDENT_MINI_RCX_TIMING wns=(\S+) tns=(\S+) hold=(\S+)$', text, re.M)
        r2r = re.search(r'^STUDENT_MINI_RCX_R2R wns=(\S+)$', text, re.M)
        if code or not found or not r2r:
            raise RuntimeError(f'post-route timing {tag} failed; see eco-timing-{tag}.log')
        spef.unlink(missing_ok=True)
        return dict(wns_ns=float(found.group(1)), tns_ns=float(found.group(2)), hold_wns_ns=float(found.group(3)),
                    r2r_wns_ns=float(r2r.group(1)), log=f'eco-timing-{tag}.log', peak_rss_bytes=peak)

    def better(now, best):
        r2r, wns = now['r2r_wns_ns'] - best['r2r_wns_ns'], now['wns_ns'] - best['wns_ns']
        return (r2r > 0.005 and wns >= -0.02) or (wns > 0.005 and r2r >= -0.02)

    best = timing(route_odb, 'base')
    passes = [dict(eco_pass=0, timing=best, accepted=True)]
    for index in range(1, args.eco_passes + 1):
        if best['wns_ns'] >= 0 and best['hold_wns_ns'] >= 0:
            break
        repaired = results / f'5_2_route.eco{index}.repaired.odb'
        out = results / f'5_2_route.eco{index}.odb'
        entry = dict(eco_pass=index, accepted=False)
        passes.append(entry)
        for attempt in ('', '-retry'):
            # one retry: in tests the repair process failed once on a Tcl channel error ("no data available")
            # and passed on the unchanged inputs
            code, text, peak = tool('post_route_eco.tcl', f'eco{index}-repair{attempt}.log', f'eco-{index}-repair',
                                    dict(STUDENT_MINI_ODB=str(route_odb), STUDENT_MINI_OUT=str(repaired)))
            if not code and 'STUDENT_MINI_ECO_COMPLETE' in text:
                break
        else:
            if index == 1:
                raise RuntimeError(f'post-route ECO repair {index} failed; see eco{index}-repair-retry.log')
            # a later pass that cannot run leaves the last accepted route database in place
            entry['repair_failed'] = f'eco{index}-repair-retry.log'
            break
        changes = re.search(r'^STUDENT_MINI_ECO_CHANGES insts=(\d+) dropped_routes=(\d+)$', text, re.M)
        entry.update(repair_log=f'eco{index}-repair{attempt}.log', repair_peak_rss_bytes=peak,
                     changed_instances=int(changes.group(1)), dropped_routes=int(changes.group(2)),
                     dont_touch_nets=re.findall(r'^STUDENT_MINI_ECO_DONT_TOUCH_NET (\S+)$', text, re.M),
                     skewed_flops=int((re.findall(r'^STUDENT_MINI_ECO_SKEWED_FLOPS (\d+)$', text, re.M) or ['0'])[-1]))
        code, text, peak = tool('detail_route_fresh.tcl', f'eco{index}-drt.log', f'eco-{index}-detailed-route',
                                dict(STUDENT_MINI_ODB=str(repaired), STUDENT_MINI_OUT=str(out),
                                     STUDENT_MINI_DRC=str(reports / f'5_route_drc.eco{index}.rpt'),
                                     STUDENT_MINI_MAZE=str(results / f'maze.eco{index}.log'),
                                     STUDENT_MINI_ANT=str(reports / f'drt_antennas.eco{index}.log')))
        violations = re.findall(r'Number of violations = (\d+)', text)
        if code or 'STUDENT_MINI_DRT_COMPLETE' not in text or not violations:
            if index == 1:
                raise RuntimeError(f'post-route ECO detailed route {index} failed; see eco{index}-drt.log')
            entry['drt_failed'] = f'eco{index}-drt.log'
            break
        repaired.unlink()
        entry.update(drt_log=f'eco{index}-drt.log', drt_peak_rss_bytes=peak, drc=int(violations[-1]))
        # a few stubborn markers left by the re-route: up to two more detailed-route runs on its result
        for cleanup in (1, 2):
            if not entry['drc']:
                break
            again = results / f'5_2_route.eco{index}.cleanup{cleanup}.odb'
            code, text, peak = tool('detail_route_fresh.tcl', f'eco{index}-drt-cleanup{cleanup}.log',
                                    f'eco-{index}-detailed-route-cleanup{cleanup}',
                                    dict(STUDENT_MINI_ODB=str(out), STUDENT_MINI_OUT=str(again),
                                         STUDENT_MINI_DRC=str(reports / f'5_route_drc.eco{index}.cleanup{cleanup}.rpt'),
                                         STUDENT_MINI_MAZE=str(results / f'maze.eco{index}.cleanup{cleanup}.log'),
                                         STUDENT_MINI_ANT=str(reports / f'drt_antennas.eco{index}.cleanup{cleanup}.log')))
            violations = re.findall(r'Number of violations = (\d+)', text)
            if code or 'STUDENT_MINI_DRT_COMPLETE' not in text or not violations:
                break
            shutil.move(str(again), str(out))
            entry.update(drt_log=f'eco{index}-drt-cleanup{cleanup}.log', drc=int(violations[-1]),
                         drt_cleanups=cleanup, drt_peak_rss_bytes=max(entry['drt_peak_rss_bytes'] or 0, peak or 0))
        if entry['drc']:
            break
        entry['timing'] = now = timing(out, str(index))
        if not better(now, best) or now['hold_wns_ns'] < min(best['hold_wns_ns'], 0.0):
            break
        entry['accepted'] = True
        shutil.move(str(route_odb), str(results / f'5_2_route.before-eco{index}.odb'))
        shutil.move(str(out), str(route_odb))
        best = now
    return passes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=('cpu', 'gpu', 'gpu-block'), required=True)
    parser.add_argument('--abstract', action='store_true', help='also generate the LEF/liberty abstract (hard block)')
    parser.add_argument('--config', type=Path, required=True, help='frozen config.mk (absolute input paths)')
    parser.add_argument('--parent', type=Path, required=True, help='completion.json proving the netlist source')
    parser.add_argument('--expected-macros', type=int, required=True)
    parser.add_argument('--timeout', type=int, default=6 * 3600)
    parser.add_argument('--antenna-rounds', type=int, default=8)
    parser.add_argument('--fresh-drt', action='store_true',
                        help='detailed routing in its own jemalloc process without liberty (GPU quadrant blocks)')
    parser.add_argument('--reaudit', type=Path,
                        help='work directory of an earlier run of the same inputs whose route and finish completed: only '
                             'the post-route audit and sign-off checks run again, on its unchanged results (every bound '
                             'input other than the audit scripts must still match its recorded SHA-256)')
    parser.add_argument('--resume-antenna', type=Path,
                        help='work directory of an earlier run of the same inputs whose route (DRC 0) and finish completed '
                             'but whose antenna repair stalled: more antenna rounds continue from its accepted route '
                             'database, then finish and the audit run again (only the runner, antenna_round.tcl and the '
                             'audit scripts may differ from its recorded inputs)')
    parser.add_argument('--eco-from', type=Path,
                        help='work directory of an earlier routing run of the same inputs whose detailed route reached '
                             'zero DRC (finish not required): post-route timing ECO passes (post_route_eco.tcl repair, '
                             'detail_route_fresh.tcl re-route of the changed nets, post_route_timing.tcl RCX/SPEF timing) '
                             'continue from its accepted route database, then the antenna rounds, finish and the audit '
                             '(only the runner, antenna_round.tcl, the ECO scripts and the audit scripts may differ)')
    parser.add_argument('--eco-passes', type=int, default=3)
    parser.add_argument('--post-route-eco', action='store_true',
                        help='run the post-route timing ECO passes (as --eco-from does) inside this run, after detailed '
                             'routing reaches zero DRC and before the antenna rounds (one uninterrupted run per block)')
    args = parser.parse_args()
    if sum(bool(a) for a in (args.reaudit, args.resume_antenna, args.eco_from)) > 1:
        raise ValueError('--reaudit, --resume-antenna and --eco-from are exclusive')
    config = args.config.resolve()
    parent = args.parent.resolve()
    parent_value = json.loads(parent.read_text())
    if not parent_value.get('status', '').endswith('STAGE_PASS'):
        raise ValueError('netlist source has no passing replay/mapping stage')
    text = config.read_text()
    inputs = config_inputs(text)
    tcl = re.search(r'^export MACRO_PLACEMENT_TCL = (\S+)$', text, re.M)
    if not tcl:
        raise ValueError('fixed macro placement required')
    tools = [OPENROAD, YOSYS, FLOW / 'Makefile', FLOW / 'scripts/global_route.tcl', FLOW / 'scripts/detail_route.tcl',
             ROOT / 'integration/student-mini/antenna_round.tcl', ROOT / 'integration/student-mini/detail_route_fresh.tcl', JEMALLOC,
             OPENROAD_PATCH, ROOT / 'integration/student-mini/macro_pdn_check.tcl',
             FLOW / 'platforms/sky130hd/config.mk', FLOW / 'platforms/sky130hd/pdn.tcl']
    audit_scripts = [Path(__file__), ROOT / 'scripts/audit_student_mini_route.py',
                     ROOT / 'integration/student-mini/audit_platform_route.tcl', ROOT / 'integration/student-mini/audit_macro_pins.py']
    eco_scripts = [ROOT / 'integration/student-mini' / f for f in (
        'post_route_eco.tcl', 'post_route_timing.tcl', 'rc_calibrated.tcl', 'useful_skew_eco.tcl', 'eco_chip_io.tcl')] \
        if args.eco_from or args.post_route_eco else []
    bindings = {str(p): sha(p) for p in [*audit_scripts, config, parent, *inputs, *tools, *eco_scripts]}
    prior = None
    if args.reaudit or args.resume_antenna or args.eco_from:
        # the earlier run must have finished routing and finish on exactly these inputs (an ECO run: reached a
        # zero-DRC detailed route); only the audit scripts (reaudit), or the audit scripts, the runner and
        # antenna_round.tcl (resume; ECO: also the ECO scripts) may differ
        prior_dir = (args.reaudit or args.resume_antenna or args.eco_from).resolve()
        prior = json.loads((prior_dir / 'completion.json').read_text())
        complete = prior.get('make_exit_code') == 0 and prior.get('route_drc_errors') == 0
        routed = ((prior.get('detailed_route') or {}).get('drc') == 0
                  and all(r.get('drc_after') == 0 for r in prior.get('antenna_rounds', []) if r.get('accepted')))
        if prior.get('platform') != args.platform or not (complete or (args.eco_from and routed)):
            raise ValueError('reaudit/resume needs a run whose route (DRC 0) and finish completed '
                             '(an ECO run: whose detailed route reached zero DRC)')
        if args.resume_antenna and (prior.get('reaudit_of') or prior.get('resumed_from') or prior.get('eco_from')):
            raise ValueError('resume from the original routing run')
        if args.eco_from and prior.get('reaudit_of'):
            raise ValueError('an ECO run continues a routing, resumed or ECO run, not a re-audit')
        audit_paths = {str(p) for p in audit_scripts}
        if args.resume_antenna or args.eco_from:
            audit_paths.add(str(ROOT / 'integration/student-mini/antenna_round.tcl'))
        audit_paths.update(str(p) for p in eco_scripts)
        stale = [p for p, v in prior['bindings'].items() if p not in audit_paths and sha(Path(p)) != v]
        if stale or any(p not in prior['bindings'] for p in bindings if p not in audit_paths):
            raise ValueError(f'reaudit inputs differ from the earlier run: {stale[:2]}')
        bindings = {**prior['bindings'], **{p: bindings[p] for p in audit_paths}}
        bindings[str(prior_dir / 'completion.json')] = sha(prior_dir / 'completion.json')
    key = hashlib.sha256(json.dumps(dict(bindings=bindings, platform=args.platform), sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/platform-physical' / key
    work.mkdir(parents=True, exist_ok=False)
    chain = []
    if prior:
        # an ECO run may continue an earlier resumed or ECO run: chain = the earlier runs back to the original
        # routing run, whose directory holds the run config and the routing logs
        chain = [(prior_dir, prior)]
        while any(chain[-1][1].get(k) for k in ('eco_from', 'resumed_from', 'reaudit_of')):
            up = Path(next(chain[-1][1][k] for k in ('eco_from', 'resumed_from', 'reaudit_of') if chain[-1][1].get(k)))
            chain.append((up, json.loads((up / 'completion.json').read_text())))
        src = chain[-1][0]  # logs of the routing run
        variant = prior['variant']
        run_config = src / 'config.mk'
    else:
        src = work
        variant = f'student-mini-{args.platform}-final-{key[:16]}'
        run_config = work / 'config.mk'
        run_config.write_text(text.replace('export NUM_CORES = 8', 'export NUM_CORES = 2') + '\nexport NUM_CORES = 2\n'
                              '# Antenna rounds run as separate processes (see module docstring).\n'
                              'export SKIP_ANTENNA_REPAIR_POST_DRT = 1\n')
        bindings[str(run_config)] = sha(run_config)
        shutil.copyfile(Path(tcl.group(1)), work / 'macro-placement.tcl')
    design = re.search(r'^export DESIGN_NAME = (\S+)$', text, re.M).group(1)
    layer = re.search(r'^export MAX_ROUTING_LAYER = (met\d)$', text, re.M)
    max_layer = layer.group(1) if layer else 'met5'
    results = FLOW / 'results/sky130hd' / design / variant
    logs = FLOW / 'logs/sky130hd' / design / variant
    reports = FLOW / 'reports/sky130hd' / design / variant
    result = dict(status='HOLD', platform=args.platform, bindings=bindings, variant=variant, clock_period_ns=10,
                  drt_batch_size=int(DRT_BATCH_SIZE),
                  threads=2, result_directory=str(results), metrics_directory=str(logs),
                  reports_directory=str(reports), formal_baseline=False, physical_evidence_complete=False)
    if prior:
        result['eco_from' if args.eco_from else 'resumed_from' if args.resume_antenna else 'reaudit_of'] = str(prior_dir)

    def logpath(name):
        # a log of this run, or of the earlier run(s) it re-audits / resumes / continues
        for d in [work] + [d for d, _ in chain]:
            if (d / name).exists():
                return d / name
        return src / name
    (work / 'inputs.json').write_text(json.dumps(result, indent=2) + '\n')
    started = time.monotonic()

    def heartbeat(stage):
        (work / 'heartbeat.json').write_text(json.dumps(dict(stage=stage, elapsed_seconds=time.monotonic() - started,
                                                            updated_at=datetime.now(timezone.utc).isoformat())) + '\n')

    def verify():
        changed = [p for p, v in bindings.items() if sha(Path(p)) != v]
        if changed:
            raise ValueError('physical input changed: ' + changed[0])

    try:
        verify()
        base = ['make', '-C', str(FLOW), f'DESIGN_CONFIG={run_config}', f'FLOW_VARIANT={variant}', 'NUM_CORES=2',
                f'OPENROAD_EXE={OPENROAD}', f'YOSYS_EXE={YOSYS}', f'COURSE_ROOT={ROOT}', 'GDS_FINAL_FILE=']
        route_odb = results / '5_2_route.odb'
        route_target = str(route_odb.relative_to(FLOW))
        result['command'] = [base + [route_target], 'antenna rounds (antenna_round.tcl)', base + ['finish']]

        def run(command, log_name, stage):
            with (work / log_name).open('x') as log:
                proc = subprocess.Popen(command, cwd=FLOW, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                        env={**os.environ, 'STUDENT_MINI_DRT_BATCH_SIZE': DRT_BATCH_SIZE})
                while proc.poll() is None:
                    heartbeat(stage)
                    if time.monotonic() - started > args.timeout:
                        proc.terminate()
                        proc.wait(60)
                        raise TimeoutError(f'{stage} exceeded {args.timeout} s')
                    time.sleep(20)
            return proc.returncode

        if prior and args.reaudit:
            for k in ('command', 'macro_pdn_preflight', 'detailed_route', 'antenna_rounds', 'route_drc_errors',
                      'make_exit_code', 'stage_seconds'):
                if k in prior:
                    result[k] = prior[k]
        else:
            if prior:
                for k in ('command', 'macro_pdn_preflight', 'detailed_route'):
                    if k in prior:
                        result[k] = prior[k]
                rounds = [dict(r, resumed=True) for r in prior.get('antenna_rounds', [])]
                first = max([r['round'] for r in rounds] + [0]) + 1
                drc = 0
                if args.eco_from:
                    result['post_route_eco'] = post_route_eco(args, work, results, reports, route_odb, run_config.read_text(),
                                                              max_layer, heartbeat, started)
            else:
                # Preflight: every hard-macro VDD/VSS pin must touch the floorplan power grid before hours of
                # place and route (a floating macro is otherwise found only by the final PSM check).
                code = run(base + [str((results / '2_floorplan.odb').relative_to(FLOW))], 'make-floorplan.log', 'ORFS-floorplan')
                if code:
                    result['make_exit_code'] = code
                    raise RuntimeError('ORFS floorplan failed; see make-floorplan.log')
                with (work / 'macro-pdn.log').open('x') as log:
                    subprocess.call([str(OPENROAD), '-exit', '-no_splash', str(ROOT / 'integration/student-mini/macro_pdn_check.tcl')],
                                    env={'STUDENT_MINI_ODB': str(results / '2_floorplan.odb'), 'PATH': '/usr/bin:/bin'},
                                    stdout=log, stderr=subprocess.STDOUT)
                found = re.findall(r'^STUDENT_MINI_MACRO_PDN connected=(\d+) unconnected=(\d+)$',
                                   (work / 'macro-pdn.log').read_text(errors='replace'), re.M)
                if not found or int(found[0][1]) or int(found[0][0]) != 2 * args.expected_macros:
                    raise RuntimeError(f'macro power pins not on the floorplan grid: {found}; see macro-pdn.log')
                result['macro_pdn_preflight'] = dict(connected=int(found[0][0]), unconnected=int(found[0][1]))
                if args.fresh_drt:
                    # ORFS up to global routing; detailed routing in its own jemalloc process without liberty
                    grt_target = str((results / '5_1_grt.odb').relative_to(FLOW))
                    result['command'] = [base + [grt_target], 'detailed route (detail_route_fresh.tcl)',
                                         'antenna rounds (antenna_round.tcl)', base + ['finish']]
                    code = run(base + [grt_target], 'make.log', 'ORFS-grt')
                    if code:
                        result['make_exit_code'] = code
                        raise RuntimeError('ORFS flow failed before detailed routing; see make.log')
                    env = dict(STUDENT_MINI_ODB=str(results / '5_1_grt.odb'), STUDENT_MINI_OUT=str(route_odb), PATH='/usr/bin:/bin',
                               LD_PRELOAD=str(JEMALLOC), STUDENT_MINI_MAX_LAYER=max_layer, STUDENT_MINI_DRT_BATCH_SIZE=DRT_BATCH_SIZE,
                               STUDENT_MINI_DRC=str(reports / '5_route_drc.rpt'), STUDENT_MINI_MAZE=str(results / 'maze.log'),
                               STUDENT_MINI_ANT=str(reports / 'drt_antennas.log'))
                    reports.mkdir(parents=True, exist_ok=True)
                    with (work / 'drt.log').open('x') as log:
                        proc = subprocess.Popen(['/usr/bin/time', '-v', str(OPENROAD), '-exit', '-no_splash', '-threads', '2',
                                                 str(ROOT / 'integration/student-mini/detail_route_fresh.tcl')],
                                                cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                        while proc.poll() is None:
                            heartbeat('detailed-route')
                            if time.monotonic() - started > args.timeout:
                                proc.terminate()
                                proc.wait(60)
                                raise TimeoutError(f'detailed route exceeded {args.timeout} s')
                            time.sleep(20)
                    drt_log = (work / 'drt.log').read_text(errors='replace')
                    violations = re.findall(r'Number of violations = (\d+)', drt_log)
                    peak = re.findall(r'Maximum resident set size \(kbytes\): (\d+)', drt_log)
                    if proc.returncode or 'STUDENT_MINI_DRT_COMPLETE' not in drt_log or not violations:
                        raise RuntimeError('detailed route failed; see drt.log')
                    drc = int(violations[-1])
                    result['detailed_route'] = dict(process='fresh', drc=drc, peak_rss_bytes=int(peak[-1]) * 1024 if peak else None)
                else:
                    code = run(base + [route_target], 'make.log', 'ORFS-route')
                    if code:
                        result['make_exit_code'] = code
                        raise RuntimeError('ORFS flow failed before antenna repair; see make.log')
                    drc = int(last_metric(logs / '5_2_route.json', 'detailedroute__route__drc_errors'))
                rounds = []
                first = 1
                if args.post_route_eco and drc:
                    # the ECO starts from a zero-DRC route; the antenna rounds clean up first, the sign-off decides
                    result['post_route_eco_skipped'] = f'detailed route left {drc} DRC violations'
                elif args.post_route_eco:
                    result['post_route_eco'] = post_route_eco(args, work, results, reports, route_odb, run_config.read_text(),
                                                              max_layer, heartbeat, started)
            for index in range(first, first + args.antenna_rounds):
                # A round is kept only with zero DRC.  A round that leaves violations (a few stubborn markers
                # around new diodes), or that removes no antenna violation at all (long single-layer wires the
                # default repair keeps re-diode-ing), is retried from the same accepted database with jumpers
                # only, then diodes only; among the zero-DRC results the one with the fewest antenna nets is
                # kept.  The run fails when every mode leaves DRC violations; rounds stop when no mode makes
                # progress (the final antenna audit then decides).  Then 'upsize' gives a violating gate the next drive
                # strength whose larger gate area covers the ratio; last resort per round: 'split' moves each
                # violating gate pin behind buffers along its long single-layer wire (antenna_round.tcl).
                accepted_entry, skipped, stalled = None, False, False
                for mode in ('', 'jumper', 'diode', 'upsize', 'split'):
                    suffix = f'-{mode}' if mode else ''
                    out = results / f'5_2_route.antenna{index}{suffix}.odb'
                    env = dict(STUDENT_MINI_ODB=str(route_odb), STUDENT_MINI_OUT=str(out), PATH='/usr/bin:/bin', LD_PRELOAD=str(JEMALLOC),
                               STUDENT_MINI_MAX_LAYER=max_layer, STUDENT_MINI_DRT_BATCH_SIZE=DRT_BATCH_SIZE, STUDENT_MINI_ANTENNA_MODE=mode,
                               STUDENT_MINI_DRC=str(reports / f'5_route_drc.antenna{index}{suffix}.rpt'),
                               STUDENT_MINI_ANT=str(reports / f'drt_antennas.antenna{index}{suffix}.log'))
                    log_name = f'antenna{index}{suffix}.log'
                    with (work / log_name).open('x') as log:
                        proc = subprocess.Popen(['/usr/bin/time', '-v', str(OPENROAD), '-exit', '-no_splash', '-threads', '2',
                                                 str(ROOT / 'integration/student-mini/antenna_round.tcl')],
                                                cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                        while proc.poll() is None:
                            heartbeat(f'antenna-round-{index}{suffix}')
                            if time.monotonic() - started > args.timeout:
                                proc.terminate()
                                proc.wait(60)
                                raise TimeoutError(f'antenna round {index}{suffix} exceeded {args.timeout} s')
                            time.sleep(20)
                    text_log = (work / log_name).read_text(errors='replace')
                    before = re.findall(r'^STUDENT_MINI_ANTENNA_BEFORE (\d+)', text_log, re.M)
                    peak = re.findall(r'Maximum resident set size \(kbytes\): (\d+)', text_log)
                    if proc.returncode or not before:
                        raise RuntimeError(f'antenna round {index}{suffix} failed; see {log_name}')
                    entry = dict(round=index, mode=mode or 'default', log=log_name, antenna_nets_before=int(before[0]), drc_before=drc,
                                 peak_rss_bytes=int(peak[-1]) * 1024 if peak else None)
                    rounds.append(entry)
                    result['antenna_rounds'] = rounds
                    if 'STUDENT_MINI_ANTENNA_ROUND_SKIPPED' in text_log:
                        skipped = True
                        break
                    after = re.findall(r'^STUDENT_MINI_ANTENNA_AFTER (\d+)', text_log, re.M)
                    violations = re.findall(r'Number of violations = (\d+)', text_log)
                    diodes = re.findall(r'Inserted (\d+) diodes', text_log)
                    round_drc = int(violations[-1]) if violations else None
                    entry.update(antenna_nets_after=int(after[-1]) if after else None, drc_after=round_drc,
                                 diodes_inserted=int(diodes[-1]) if diodes else 0, accepted=round_drc == 0)
                    if round_drc == 0 and entry['antenna_nets_after'] is not None and (
                            accepted_entry is None or entry['antenna_nets_after'] < accepted_entry[0]['antenna_nets_after']):
                        accepted_entry = (entry, out)
                    if (round_drc == 0 and entry['antenna_nets_after'] is not None
                            and entry['antenna_nets_after'] < entry['antenna_nets_before']):
                        break
                if skipped:
                    break
                if accepted_entry is None:
                    raise RuntimeError(f'antenna round {index} left DRC violations in every repair mode')
                entry, out = accepted_entry
                for e in rounds:
                    if e['round'] == index:
                        e['accepted'] = e is entry
                stalled = entry['antenna_nets_after'] >= entry['antenna_nets_before']
                shutil.move(str(route_odb), str(results / f'5_2_route.before-antenna{index}.odb'))
                shutil.move(str(out), str(route_odb))
                drc = 0
                if stalled:
                    break
            result['antenna_rounds'] = rounds
            result['route_drc_errors'] = drc
            code = run(base + ['finish'] + (['do-generate_abstract'] if args.abstract else []), 'make-finish.log', 'ORFS-finish')
            result['make_exit_code'] = code
            result['stage_seconds'] = {}
            for stage in STAGES:
                path = logs / (stage + '.log')
                if path.is_file():
                    found = re.findall(r'Elapsed time: (?:(\d+):)?(\d+):([\d.]+)', path.read_text(errors='replace'))
                    if found:
                        h, m, s = found[-1]
                        result['stage_seconds'][stage] = int(h or 0) * 3600 + int(m) * 60 + float(s)
            if code:
                raise RuntimeError('ORFS finish failed; see make-finish.log')
        verify()
        finish = json.loads((logs / '6_report.json').read_text())
        sdc = (results / '6_final.sdc').read_text()
        # DRC of the accepted route database (ORFS route stage or the last accepted antenna round);
        # antenna counts come from the post-route audit of 6_final.odb (check_antennas) below.
        detailed_final = {'detailedroute__route__drc_errors': result['route_drc_errors'],
                          'detailedroute__antenna__violating__nets': None, 'detailedroute__antenna__violating__pins': None}
        finish_final = {'finish__timing__setup__ws': last_metric(logs / '6_report.json', 'finish__timing__setup__ws')}
        hold = last_metric(logs / '6_report.json', 'finish__timing__hold__ws')
        # A GPU quadrant block is timed against its boundary budgets only, and the hierarchical GPU top
        # (four block abstracts + channel logic) against the same budgets; the GPU's setup/hold sign-off is
        # the full-chip STA of the assembled design (integration/student-mini/gpu_fullchip_sta.tcl,
        # scripts/run_student_mini_gpu_fullchip_sta.py), so these runs record their slacks without gating.
        block_timing = args.platform in ('gpu-block', 'gpu')
        if not block_timing and (hold is None or not math.isfinite(hold) or hold < 0):
            raise ValueError('hold timing not closed')
        for key in ('finish__power__total', 'finish__design__instance__area', 'finish__design__instance__count__stdcell',
                    'finish__design__instance__count__macros', 'finish__design__die__area'):
            result.setdefault('report_metrics', {})[key] = last_metric(logs / '6_report.json', key)
        audit_log = work / 'audit.log'
        with audit_log.open('x') as log:
            code = subprocess.call([str(OPENROAD), '-exit', str(ROOT / 'integration/student-mini/audit_platform_route.tcl')],
                                   env={'STUDENT_MINI_ROUTE_ODB': str(results / '6_final.odb'), 'PATH': '/usr/bin:/bin'},
                                   stdout=log, stderr=subprocess.STDOUT)
        audit = audit_log.read_text(errors='replace')
        with (work / 'audit-pins.log').open('x') as log:
            pins_code = subprocess.call([str(OPENROAD), '-python', '-exit', '-no_splash',
                                         str(ROOT / 'integration/student-mini/audit_macro_pins.py')],
                                        env={'STUDENT_MINI_ROUTE_ODB': str(results / '6_final.odb'), 'PATH': '/usr/bin:/bin'},
                                        stdout=log, stderr=subprocess.STDOUT)
        pins_audit = (work / 'audit-pins.log').read_text(errors='replace')
        pin_summary = re.findall(r'^PLATFORM_AUDIT_PINS reached=(\d+) not_reached=(\d+) floating=(\d+)$', pins_audit, re.M)
        if pins_code or len(pin_summary) != 1 or 'PLATFORM_AUDIT_PINS_COMPLETE' not in pins_audit:
            raise ValueError('macro pin audit did not complete')
        reached, no_access, floating = map(int, pin_summary[0])
        summary = re.findall(r'^PLATFORM_AUDIT_MACROS macros=(\d+) supply_ok=(\d+) supply_bad=(\d+) signals=(\d+) '
                             r'unrouted=(\d+)$', audit, re.M)
        pdn = dict(re.findall(r'^PLATFORM_AUDIT_PDN net=(\w+) status=(\w+)', audit, re.M))
        if code or len(summary) != 1 or 'PLATFORM_AUDIT_COMPLETE' not in audit:
            raise ValueError('post-route audit did not complete')
        macros, supply_ok, supply_bad, signals, unrouted = map(int, summary[0])
        if reached + no_access + floating != signals:
            raise ValueError('macro pin audit and route audit disagree on the signal pin count')
        antenna = re.findall(r'^PLATFORM_AUDIT_ANTENNA nets=(\d+)$', audit, re.M)
        if len(antenna) != 1:
            raise ValueError('final antenna check missing')
        pins = re.findall(r'ANT-0001\] Found (\d+) pin violations', audit)
        detailed_final['detailedroute__antenna__violating__nets'] = int(antenna[0])
        detailed_final['detailedroute__antenna__violating__pins'] = int(pins[-1]) if pins else 0
        if block_timing:
            # one 10 ns core_clock (plus the virtual io_clock of the chip-edge budgets)
            clocks = {n: float(p) for n, p in re.findall(r'^create_clock\b[^\n]*?-name\s+(\S+)[^\n]*?-period\s+([0-9.]+)', sdc, re.M)}
            if clocks.get('core_clock') != 10.0 or not set(clocks) <= {'core_clock', 'io_clock'}:
                raise ValueError('block SDC must define the 10 ns core_clock (and the virtual io_clock) only')
            for key in ('detailedroute__route__drc_errors', 'detailedroute__antenna__violating__nets',
                        'detailedroute__antenna__violating__pins'):
                if type(detailed_final.get(key)) is not int or detailed_final[key] != 0:
                    raise ValueError('route signoff failed: ' + key)
            result['route_metrics'] = dict(clock_period_ns=10, drc=0, antenna_nets=0, antenna_pins=0,
                                           budget_setup_ws_ns=finish_final['finish__timing__setup__ws'],
                                           budget_hold_ws_ns=hold, timing_signoff='full-chip STA')
        else:
            result['route_metrics'] = check_metrics(detailed_final, finish_final, sdc)
            result['route_metrics']['hold_wns_ns'] = hold
        result['macro_audit'] = dict(macros=macros, supply_pins_connected=supply_ok, supply_pins_bad=supply_bad,
                                     connected_signal_pins=signals, pins_reached_by_route=reached,
                                     pins_without_access=no_access, unrouted_pins=unrouted,
                                     floating_output_pins=floating, power_grid=pdn)
        if (macros != args.expected_macros or supply_bad or supply_ok != 2 * macros or no_access or unrouted
                or pdn != {'VDD': 'PASS', 'VSS': 'PASS'}):
            raise ValueError('macro access / supply / power-grid audit failed')
        if max_layer != 'met5':
            # hard blocks keep the layers above max_layer for the top level (power straps): no signal
            # wire of the route stage or of any accepted antenna round may use them
            routed = [src / 'drt.log' if args.fresh_drt else logs / '5_2_route.log'] + [logpath(r.get('log', f'antenna{r["round"]}.log')) for r in result['antenna_rounds']
                                                  if r.get('accepted')]
            routed += [d / e['drt_log'] for d, v in [(work, result)] + chain for e in v.get('post_route_eco', [])
                       if e.get('accepted') and 'drt_log' in e]
            above = [f'met{k}' for k in range(int(max_layer[3:]) + 1, 6)]
            for path in routed:
                for name in above:
                    found = re.findall(rf'Total wire length on LAYER {name} = (\d+) um', path.read_text(errors='replace'))
                    if found and int(found[-1]):
                        raise ValueError(f'{path.name} routes signals on {name} ({found[-1]} um) above {max_layer}')
            result['max_routing_layer'] = max_layer
        if args.abstract:
            abstract = {'lef': results / f'{design}.lef', 'lib': results / f'{design}_typ.lib'}
            if not all(p.is_file() and p.stat().st_size for p in abstract.values()):
                raise ValueError('abstract views missing')
            result['abstract'] = {k: str(v) for k, v in abstract.items()}
        result['artifacts'] = {str(p): sha(p) for p in
                               [*(results / ('6_final.' + s) for s in ('def', 'v', 'sdc', 'spef', 'odb')),
                                (src / 'drt.log') if args.fresh_drt else (logs / '5_2_route.json'),
                                logs / '6_report.json', src / 'make.log',
                                logpath('make-finish.log'), audit_log, work / 'audit-pins.log',
                                *sorted({*work.glob('antenna*.log'), *(f for d, _ in chain for f in d.glob('antenna*.log'))}),
                                *sorted({*work.glob('eco*.log'), *(f for d, _ in chain for f in d.glob('eco*.log'))}),
                                *sorted(reports.glob('*.antenna*.*')),
                                *([results / f'{design}.lef', results / f'{design}_typ.lib'] if args.abstract else [])]}
        verify()
        result.update(status='PLATFORM_PHYSICAL_ROUTE_STAGE_PASS',
                      reason='10 ns setup/hold, DRC/antenna zero, macro access and PDN connectivity pass; workload power remains')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic() - started
    heartbeat(result['status'])
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'],
                          metrics=result.get('route_metrics'))), flush=True)
    return 0 if result['status'] == 'PLATFORM_PHYSICAL_ROUTE_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
