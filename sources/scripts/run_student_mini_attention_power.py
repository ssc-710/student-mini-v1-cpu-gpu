"""Analyze ten distinct post-route workloads using actual VCD and SPEF."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.collect_openroad_activity_power import parse_activity_annotation,parse_power_json,validate_vcd_window
from scripts.run_student_mini_attention_activity import check_transcript

def opensta_scope(scope):
    # The simulator hierarchy is recorded with dots. Locked OpenSTA builds its
    # VCD path with '/' (VcdCountReader::makeVar); passing dots matches no pins.
    if not isinstance(scope,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)+',scope):
        raise ValueError('unsupported or ambiguous VCD scope')
    return scope.replace('.', '/')

def validate_samples(activity):
    if activity.get('mode')!='gate' or activity.get('activity_complete') is not True:
        raise ValueError('post-route gate activity required, not RTL or synthesis activity')
    rows=activity['records']
    if sorted(r['seed'] for r in rows)!=list(range(1,11)):raise ValueError('missing/duplicate per-seed workload')
    if any(r.get('clock_hz')!=100000000 or not r.get('input_sha256') for r in rows):raise ValueError('wrong clock or unbound workload')
    if len({r['activity_sha256'] for r in rows})!=10:raise ValueError('activity copied across seeds')
    return rows

def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement',type=Path,required=True)
    parser.add_argument('--activity',type=Path,required=True)
    args=parser.parse_args();placement=args.placement.resolve();activity_path=args.activity.resolve()
    activity=json.loads(activity_path.read_text());rows=validate_samples(activity)
    parent=json.loads((placement/'completion.json').read_text())
    source=json.loads((placement/'inputs.json').read_text())
    route_path=placement/'route/completion.json';route=json.loads(route_path.read_text())
    if route.get('exit_code')!=0 or not route.get('source_freshness_verified'):raise ValueError('route incomplete')
    result_dir=Path(parent['result_directory']);logs=Path(parent['metrics_directory']);orfs=logs.parents[4]
    files={key:result_dir/('6_final.'+key) for key in ('v','odb','sdc','spef')}
    if activity['bindings'].get(str(files['v']))!=sha(files['v']):raise ValueError('activity netlist differs from route')
    for path in files.values():
        if route['artifacts'].get(str(path))!=sha(path):raise ValueError('unbound route artifact: '+str(path))
    timing=route['metrics']
    metrics=logs/'5_2_route.json'
    if route['artifacts'].get(str(metrics))!=sha(metrics):raise ValueError('unbound route metrics')
    detailed=json.loads(metrics.read_text())
    if timing['finish__timing__setup__ws']<0 or any(detailed[key]!=0 for key in ('detailedroute__route__drc_errors','detailedroute__antenna__violating__nets','detailedroute__antenna__violating__pins')):
        raise ValueError('route timing/DRC/antenna signoff failed')
    bindings={**source['files'],**activity['bindings']}
    paths=[activity_path,route_path,placement/'config.mk',Path(__file__),ROOT/'scripts/student_mini_activity_power.tcl',ROOT/'scripts/collect_openroad_activity_power.py',ROOT/'scripts/run_student_mini_attention_activity.py',ROOT/'ppa/common/activity_power.mk',*files.values()]
    for name,digest in activity['artifacts'].items():
        path=activity_path.parent/name
        if sha(path)!=digest:raise ValueError('activity artifact changed')
        bindings[str(path)]=digest
    for path in paths:bindings[str(path)]=sha(path)
    for name,digest in bindings.items():
        if sha(Path(name))!=digest:raise ValueError('power source changed: '+name)
    manifest_paths=[Path(p) for p in activity['bindings'] if Path(p).name=='manifest.json']
    if len(manifest_paths)!=1:raise ValueError('ambiguous workload manifest')
    samples=json.loads(manifest_paths[0].read_text())['samples']
    expected={r['seed']:r for r in samples}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    out=ROOT/'build/student-mini/attention-power'/identity;out.mkdir(parents=True,exist_ok=False)
    openroad=next(Path(p) for p in source['files'] if Path(p).name=='openroad')
    result=dict(status='HOLD',physical_evidence_complete=False,bindings=bindings,records=[])
    started=time.monotonic()
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(out),status='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX)
            for row in rows:
                seed=row['seed'];folder=out/f'seed-{seed}';folder.mkdir()
                checked=check_transcript((activity_path.parent/f'seed-{seed}.log').read_text(),expected[seed])
                if any(checked[key]!=row[key] for key in checked):raise ValueError('activity transcript metadata mismatch')
                if row['input_sha256']!=expected[seed]['input_sha256']:raise ValueError('wrong seed workload')
                vcd=activity_path.parent/row['activity']
                if sha(vcd)!=row['activity_sha256']:raise ValueError('VCD changed')
                validate_vcd_window(vcd,row['begin_ns'],row['end_ns'])
                annotation=folder/'annotation.rpt';power=folder/'power.json'
                command=['make','-C',str(orfs/'flow'),'-f','Makefile','-f',str(ROOT/'ppa/common/activity_power.mk'),'strict-activity-power',
                         f'DESIGN_CONFIG={placement}/config.mk',f'FLOW_VARIANT={result_dir.name}',f'COURSE_ROOT={ROOT}',f'OPENROAD_EXE={openroad}','NUM_CORES=2',
                         f'POWER_TCL={ROOT}/scripts/student_mini_activity_power.tcl',f'POWER_ODB={files["odb"]}',f'POWER_SDC={files["sdc"]}',f'POWER_SPEF={files["spef"]}',
                         f'POWER_ACTIVITY={vcd}',f'POWER_ACTIVITY_SCOPE={opensta_scope(row["scope"])}',f'POWER_ACTIVITY_BEGIN_NS={row["begin_ns"]}',f'POWER_ACTIVITY_END_NS={row["end_ns"]}',
                         f'POWER_ANNOTATION_REPORT={annotation}',f'POWER_RAW_JSON={power}']
                with (folder/'openroad.log').open('x') as log:completed=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=300)
                if completed.returncode:raise RuntimeError(f'OpenROAD power seed {seed} exited {completed.returncode}')
                annotated,total,coverage=parse_activity_annotation(annotation.read_text(),'VCD')
                if coverage<95:raise ValueError('VCD annotation below 95 percent')
                dynamic,leakage,total_mw=parse_power_json(power)
                result['records'].append(dict(seed=seed,case_id=row['case_id'],operator=activity['operator'],input_sha256=row['input_sha256'],activity_sha256=sha(vcd),
                                              netlist_sha256=sha(files['v']),spef_sha256=sha(files['spef']),frequency_hz=100000000,
                                              power_w=total_mw/1000,dynamic_mw=dynamic,leakage_mw=leakage,annotation_percent=coverage,
                                              annotated_pins=annotated,total_pins=total,begin_ns=row['begin_ns'],end_ns=row['end_ns'],
                                              energy_j=(row['end_ns']-row['begin_ns'])*1e-9*total_mw/1000))
                print(json.dumps(dict(seed=seed,total_mw=total_mw,coverage=coverage)),flush=True)
            if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('power source changed during execution')
            result.update(power_complete=True,reason='Ten source-bound post-route powers measured; whole physical/package qualification remains separate')
    except Exception as error:result.update(power_complete=False,reason=f'{type(error).__name__}: {error}')
    result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()}
    (out/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(out),complete=result['power_complete'],reason=result['reason'])),flush=True)
    return 0 if result['power_complete'] else 1

if __name__=='__main__':raise SystemExit(main())
