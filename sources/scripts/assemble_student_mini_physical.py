"""Assemble a portable accelerator physical package from raw, joined signoff.

No result is inferred from file presence. Route, gate execution, fresh PDK
geometry and pre-bound timing/power replay must agree on the exact artifacts.
This does not grant a whole-platform B0 or authorize student ZIP publication.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.audit_student_mini_route import check_metrics
from scripts.audit_student_mini_pdk import lef_blocks,compare_geometry,components
from scripts.run_student_mini_sourcebound_power import parse_worst_slack,validate_samples
from scripts.collect_openroad_activity_power import parse_activity_annotation,parse_power_json,validate_vcd_window
from scripts.run_student_mini_p3_activity import check_transcript
from scripts.run_student_mini_attention_activity import check_transcript as check_attention


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def check_bindings(bindings):
    if not bindings:raise ValueError('empty source binding set')
    for name,digest in bindings.items():
        path=Path(name)
        if not path.is_file() or sha(path)!=digest:raise ValueError('source missing or changed: '+name)


def check_artifacts(base,artifacts):
    for name,digest in artifacts.items():
        path=Path(name) if Path(name).is_absolute() else base/name
        if not path.is_file() or sha(path)!=digest:raise ValueError('raw artifact changed: '+name)


def validate_power_join(records,samples,netlist_sha,spef_sha,operator):
    if sorted(r['seed'] for r in records)!=list(range(1,11)):raise ValueError('power seed coverage incomplete')
    by_seed={r['seed']:r for r in samples}
    if len(by_seed)!=10:raise ValueError('activity seed coverage incomplete')
    for row in records:
        sample=by_seed[row['seed']]
        if row.get('operator')!=operator or row.get('netlist_sha256')!=netlist_sha or row.get('spef_sha256')!=spef_sha:
            raise ValueError('cross-operator/netlist/parasitics power')
        for key in ('input_sha256','activity_sha256','case_id','begin_ns','end_ns'):
            if not sample.get(key) or row.get(key)!=sample[key]:raise ValueError('workload power join differs: '+key)
        if row.get('frequency_hz')!=100000000:raise ValueError('100 MHz required')
        for key in ('power_w','energy_j','annotation_percent','worst_setup_slack_ns'):
            value=row.get(key)
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('nonfinite power/timing metric')
        if row['power_w']<=0 or row['energy_j']<=0 or row['annotation_percent']<95 or row['worst_setup_slack_ns']<0:
            raise ValueError('power/activity/timing signoff failed')
        energy=row['power_w']*(row['end_ns']-row['begin_ns'])*1e-9
        if not math.isclose(energy,row['energy_j'],rel_tol=1e-12,abs_tol=0):raise ValueError('energy does not match the workload window')


def assemble(placement,activity_path,power_path,pdk_path,output_root):
    placement=placement.resolve();activity_path=activity_path.resolve();power_path=power_path.resolve();pdk_path=pdk_path.resolve()
    source=read(placement/'inputs.json');parent=read(placement/'completion.json')
    route_path=placement/'route/completion.json';route=read(route_path)
    activity=read(activity_path);power=read(power_path);pdk=read(pdk_path)
    operator=activity.get('operator','p3')
    tops={'p1':'p1_b2_bf16_pipeline_litex_top','p2':'p2_student_mini_top','p3':'p3_b12_output_row_base_litex_top'}
    if operator not in tops or source['design']['top']!=tops[operator]:raise ValueError('physical operator differs')
    if route.get('exit_code')!=0 or route.get('source_freshness_verified') is not True:raise ValueError('route incomplete')
    if route.get('parent_input_sha256')!=placement.name:raise ValueError('route belongs to a different source parent')
    if power.get('power_complete') is not True:raise ValueError('power incomplete')
    if pdk.get('status')!='PDK_GEOMETRY_STAGE_PASS' or pdk.get('geometry_matches') is not True or pdk.get('macro_count')!=0:
        raise ValueError('PDK geometry/macro access unqualified')
    samples=validate_samples(activity)
    check_bindings(source['files'])
    for evidence in (activity,power,pdk):check_bindings(evidence['bindings'])
    for base,evidence in ((activity_path.parent,activity),(power_path.parent,power),(pdk_path.parent,pdk)):
        check_artifacts(base,evidence['artifacts'])
    result_dir=Path(parent['result_directory']);log_dir=Path(parent['metrics_directory'])
    physical={name:result_dir/('6_final.'+suffix) for name,suffix in
              [('def','def'),('netlist','v'),('sdc','sdc'),('spef','spef'),('odb','odb')]}
    raw_metrics={'detailed':log_dir/'5_2_route.json','finish':log_dir/'6_report.json'}
    for path in [*physical.values(),*raw_metrics.values()]:
        if route['artifacts'].get(str(path))!=sha(path):raise ValueError('unbound route artifact')
    for name in ('def','odb'):
        if pdk['bindings'].get(str(physical[name]))!=sha(physical[name]):raise ValueError('PDK audit belongs to a different route')
    libraries=[]
    for folder in ('fresh-pdk','routed-db'):
        data={}
        for path in sorted((pdk_path.parent/folder).glob('library*.lef')):
            for key,value in lef_blocks(path.read_text()).items():
                if key in data and data[key]!=value:raise ValueError('conflicting raw PDK library snapshots')
                data[key]=value
        libraries.append(data)
    used,count=components(physical['def'])
    geometry=compare_geometry(*libraries,used)
    if any(pdk.get(key)!=value for key,value in geometry.items()) or pdk.get('component_count')!=count:
        raise ValueError('PDK summary differs from raw geometry snapshots')
    if activity['bindings'].get(str(physical['netlist']))!=sha(physical['netlist']):raise ValueError('gate execution used a different netlist')
    if power['bindings'].get(str(activity_path))!=sha(activity_path):raise ValueError('power belongs to a different activity run')
    route_metrics=check_metrics(read(raw_metrics['detailed']),read(raw_metrics['finish']),physical['sdc'].read_text())
    validate_power_join(power['records'],samples,sha(physical['netlist']),sha(physical['spef']),operator)
    manifests=[Path(p) for p in activity['bindings'] if Path(p).name=='manifest.json']
    if len(manifests)!=1:raise ValueError('ambiguous workload manifest')
    workload=read(manifests[0]);expected={r['seed']:r for r in workload['samples']}
    if len(workload['samples'])!=10 or sorted(expected)!=list(range(1,11)) or workload['operator']!=operator:raise ValueError('workload definition differs')
    checker=check_transcript if operator=='p3' else check_attention
    for sample in samples:
        seed=sample['seed'];measured=next(r for r in power['records'] if r['seed']==seed)
        if sha(manifests[0].parent/expected[seed]['image'])!=expected[seed]['image_sha256']:
            raise ValueError('workload input image changed')
        checked=checker((activity_path.parent/f'seed-{seed}.log').read_text(),expected[seed])
        if any(sample[key]!=value for key,value in checked.items()) or sample['input_sha256']!=expected[seed]['input_sha256']:
            raise ValueError('gate transcript/workload metadata differs')
        vcd=activity_path.parent/sample['activity']
        if sha(vcd)!=sample['activity_sha256']:raise ValueError('VCD changed')
        validate_vcd_window(vcd,sample['begin_ns'],sample['end_ns'])
        folder=power_path.parent/f'seed-{seed}'
        dynamic,leakage,total=parse_power_json(folder/'power.json')
        _,_,coverage=parse_activity_annotation((folder/'annotation.rpt').read_text(),'VCD')
        slack=parse_worst_slack((folder/'openroad.log').read_text())
        if not math.isclose(measured['power_w'],total/1000,rel_tol=1e-12) or measured['annotation_percent']!=coverage or measured['worst_setup_slack_ns']!=slack:
            raise ValueError('power or timing summary does not match raw reports')
        if measured['dynamic_mw']!=dynamic or measured['leakage_mw']!=leakage:raise ValueError('power components differ')
    boundary={p:source['files'][str(ROOT/p)] for p in source['design']['sources']}
    for name,digest in source['files'].items():
        path=Path(name)
        if path.suffix=='.svh' or path.name==source['design']['lut']:
            boundary[path.relative_to(ROOT).as_posix()]=digest
    hardware_sha=hashlib.sha256(json.dumps(dict(design=source['design'],rtl=boundary),sort_keys=True).encode()).hexdigest()
    proofs=[placement/'inputs.json',placement/'completion.json',route_path,activity_path,power_path,pdk_path,manifests[0],Path(__file__)]
    identity=hashlib.sha256(json.dumps({str(p):sha(p) for p in proofs},sort_keys=True).encode()).hexdigest()
    output=output_root.resolve()/('accelerator-'+operator)/identity
    output.mkdir(parents=True,exist_ok=False)
    artifacts={}
    def copy(path,name):
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        if sha(target)!=sha(path):raise ValueError('copy verification failed')
        return dict(path=target.relative_to(output).as_posix(),sha256=sha(target),bytes=target.stat().st_size)
    for name,path in physical.items():artifacts[name]=copy(path,'design/'+path.name)
    for name,path in raw_metrics.items():artifacts[name+'_metrics']=copy(path,'raw/'+name+'.json')
    artifacts['route_log']=copy(placement/'route/route.log','raw/route.log')
    if route['artifacts'].get(str(placement/'route/route.log'))!=artifacts['route_log']['sha256']:
        raise ValueError('route log not bound to signoff')
    for index,path in enumerate(proofs):copy(path,f'lineage/{index}-{path.name}')
    for folder in ('fresh-pdk','routed-db'):
        for path in (pdk_path.parent/folder).iterdir():
            if path.is_file():copy(path,'pdk-replay/'+folder+'/'+path.name)
    source_records={name:copy(ROOT/name,'sources/'+name) for name in boundary}
    loads=[]
    for row in power['records']:
        seed=row['seed'];sample=next(r for r in samples if r['seed']==seed)
        folder=power_path.parent/f'seed-{seed}'
        load=dict(row,backend='rtl',hardware_boundary_sha256=hardware_sha)
        load['activity']=copy(activity_path.parent/sample['activity'],f'loads/seed-{seed}/activity.vcd.gz')
        for name in ('power.json','annotation.rpt','openroad.log'):
            load[name.replace('.','_')]=copy(folder/name,f'loads/seed-{seed}/'+name)
        load['gate_log']=copy(activity_path.parent/f'seed-{seed}.log',f'loads/seed-{seed}/gate.log')
        load['input_image']=copy(manifests[0].parent/expected[seed]['image'],f'loads/seed-{seed}/input.hex')
        loads.append(load)
    # External tool executables are referenced by measured SHA, never bundled.
    toolchain={name:digest for name,digest in {**source['files'],**activity['bindings'],**power['bindings']}.items()
               if Path(name).name in ('openroad','yosys','iverilog','vvp')}
    if len({Path(p).name for p in toolchain})!=4:raise ValueError('tool binary SHA set incomplete')
    profile=dict(schema='student-mini-physical-v2',profile='mini',platform='accelerator',operator=operator,
        process='sky130hd',physical_evidence_complete=True,formal_baseline=False,
        hardware_boundary_sha256=hardware_sha,clock_period_ns=10,frequency_hz=100000000,
        route_metrics=route_metrics,macro_count=0,macro_pin_access='NOT_APPLICABLE_NO_MACROS',
        artifacts=artifacts,rtl_sources=source_records,loads=loads,external_tool_binary_sha256=toolchain,
        proof_semantics='Historical route and actual gate workloads joined to freshly bound PDK geometry and timing/power replay',
        other_release_gates_complete=False)
    profile['package_files']={p.relative_to(output).as_posix():dict(sha256=sha(p),bytes=p.stat().st_size)
                              for p in output.rglob('*') if p.is_file()}
    (output/'profile.json').write_text(json.dumps(profile,indent=2)+'\n')
    return output/'profile.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement',type=Path,required=True)
    parser.add_argument('--activity',type=Path,required=True)
    parser.add_argument('--power',type=Path,required=True)
    parser.add_argument('--pdk-audit',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=ROOT/'build/student-mini/physical-packages')
    args=parser.parse_args()
    result=assemble(args.placement,args.activity,args.power,args.pdk_audit,args.output_root)
    print(json.dumps(dict(path=str(result),sha256=sha(result),physical_evidence_complete=True,formal_baseline=False)))


if __name__=='__main__':main()
