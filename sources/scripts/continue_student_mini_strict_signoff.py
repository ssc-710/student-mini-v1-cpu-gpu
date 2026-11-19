"""Strict route -> gate -> PDK -> source-bound power -> verified raw bundle.

Unlike a subprocess-success continuation, antenna/DRC/timing failures stop
before expensive workloads are queued. A raw physical bundle is not formal B0.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.audit_student_mini_route import check_metrics
from scripts.retry_student_mini_route import execute_locked_route, verify


def check_parent(placement):
    route_path = placement/'route/completion.json'
    route = json.loads(route_path.read_text())
    parent = json.loads((placement/'completion.json').read_text())
    source = json.loads((placement/'inputs.json').read_text())
    if route.get('exit_code') != 0 or route.get('source_freshness_verified') is not True:
        raise ValueError('completed fresh route required')
    if route.get('parent_input_sha256') != placement.name or parent.get('input_sha256') != placement.name:
        raise ValueError('route parent identity differs')
    verify(source['files'])
    logs = Path(parent['metrics_directory']); results = Path(parent['result_directory'])
    paths = [logs/'5_2_route.json', logs/'6_report.json', results/'6_final.sdc']
    for path in paths:
        if route['artifacts'].get(str(path)) != sha(path): raise ValueError('unbound route signoff report')
    metrics = check_metrics(json.loads(paths[0].read_text()), json.loads(paths[1].read_text()), paths[2].read_text())
    return {str(p): sha(p) for p in [route_path, *paths]}, metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--sky130-library-root', type=Path, required=True)
    parser.add_argument('--wait-seconds', type=int, default=54000)
    args = parser.parse_args()
    if not 60 <= args.wait_seconds <= 64800: raise ValueError('bounded continuation required')
    placement = args.placement.resolve(); manifest = args.manifest.resolve()
    dependencies = ['student_mini.py','audit_student_mini_route.py','retry_student_mini_route.py',
        'run_student_mini_attention_activity.py','run_student_mini_p3_activity.py',
        'audit_student_mini_pdk.py','run_student_mini_sourcebound_power.py',
        'student_mini_sourcebound_power.tcl','collect_openroad_activity_power.py',
        'continue_student_mini_physical_bundle.py','assemble_student_mini_physical.py',
        'verify_student_mini_physical_bundle.py','validate_student_mini_physical.py']
    paths = [Path(__file__), manifest, placement/'inputs.json', placement/'completion.json',
             placement/'config.mk', *[ROOT/'scripts'/name for name in dependencies]]
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(dict(bindings=bindings, wait_seconds=args.wait_seconds), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/strict-signoff-continuation'/identity; work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', physical_evidence_complete=False, formal_baseline=False,
        release_complete=False, bindings=bindings, stages=[])
    begin = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-begin))+'\n')
    def execute(name, script, parameters):
        remaining = args.wait_seconds-(time.monotonic()-begin)
        if remaining < 1: raise TimeoutError('strict signoff continuation budget expired')
        verify(bindings)
        log = work/(name+'.log')
        code = execute_locked_route([sys.executable, str(ROOT/'scripts'/script), *map(str, parameters)],
            log, remaining, lambda _: heartbeat(name))
        result['stages'].append(dict(name=name, exit_code=code, log_sha256=sha(log)))
        if code: raise RuntimeError(name+' failed; inspect preserved log')
        output = json.loads(log.read_text().splitlines()[-1])
        verify(bindings)
        return output
    try:
        print(json.dumps(dict(work=str(work), stage='WAITING_FOR_STRICT_ROUTE_SIGNOFF')), flush=True)
        while not (placement/'route/completion.json').exists():
            heartbeat('WAITING_FOR_STRICT_ROUTE_SIGNOFF')
            if time.monotonic()-begin > args.wait_seconds: raise TimeoutError('route wait expired')
            time.sleep(10)
        extra, metrics = check_parent(placement); bindings.update(extra); result['route_metrics'] = metrics
        route_audit = execute('route-audit','audit_student_mini_route.py',['--placement',placement])
        result['route_audit'] = route_audit
        # P1/P2 gate workloads: attention activity; P3: MoE activity (same CLI), chosen by the placement's operator
        operator = json.loads((placement/'completion.json').read_text()).get('operator')
        if operator not in ('p1', 'p2', 'p3'): raise ValueError(f'unknown placement operator {operator}')
        gate_script = 'run_student_mini_p3_activity.py' if operator == 'p3' else 'run_student_mini_attention_activity.py'
        gate = execute('gate-workloads',gate_script,[
            '--placement',placement,'--manifest',manifest,'--mode','gate','--sky130-library-root',args.sky130_library_root.resolve()])
        if gate.get('complete') is not True: raise ValueError('gate workloads incomplete')
        activity = Path(gate['work'])/'completion.json'; bindings[str(activity)] = sha(activity)
        pdk = execute('pdk-geometry','audit_student_mini_pdk.py',['--placement',placement])
        if pdk.get('status') != 'PDK_GEOMETRY_STAGE_PASS': raise ValueError('PDK geometry differs')
        pdk_path = Path(pdk['work'])/'audit.json'; bindings[str(pdk_path)] = sha(pdk_path)
        power = execute('sourcebound-power','run_student_mini_sourcebound_power.py',['--placement',placement,'--activity',activity])
        if power.get('complete') is not True: raise ValueError('source-bound power incomplete')
        power_path = Path(power['work'])/'completion.json'; bindings[str(power_path)] = sha(power_path)
        bundle = execute('physical-bundle','continue_student_mini_physical_bundle.py',[
            '--placement',placement,'--activity',activity,'--power',power_path,'--pdk-audit',pdk_path,'--wait-seconds','60'])
        report_path = Path(bundle['work'])/'completion.json'; report = json.loads(report_path.read_text())
        if report.get('status') != 'PHYSICAL_BUNDLE_VERIFIED' or report.get('physical_evidence_complete') is not True:
            raise ValueError('independent physical bundle verification incomplete')
        bindings[str(report_path)] = sha(report_path)
        result.update(status='RAW_PHYSICAL_SIGNOFF_STAGES_COMPLETE', raw_bundle_verified=True,
            profile=report['profile'], reason='Strict raw physical stages complete; complete toolchain, protocol, Nano and formal baseline gates remain separate')
    except Exception as error: result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic()-begin; heartbeat(result['status'])
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result.get('raw_bundle_verified') else 1


if __name__ == '__main__': raise SystemExit(main())
