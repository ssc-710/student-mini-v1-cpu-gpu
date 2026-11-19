"""Fail-closed mini physical evidence validation, separate from evidence production.

This validator is not yet the whole-package release verifier. It does not route
hardware or generate power from estimates. Every signoff record refers to files.
"""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1048576),b''):digest.update(block)
    return digest.hexdigest()


def bound_file(root,record):
    relative=PurePosixPath(record['path'])
    if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative) or ':' in str(relative):raise ValueError('unsafe artifact path')
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('artifact escapes package')
    if not path.is_file() or path.stat().st_size==0 or sha(path)!=record['sha256']:raise ValueError('missing/empty/tampered artifact')
    return path


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def validate(root,profile,*,platform,operators,hardware_boundary_sha256):
    root=Path(root)
    if profile.get('schema')!='student-mini-physical-v1' or profile.get('profile')!='mini' or profile.get('platform')!=platform:raise ValueError('legacy/wrong-platform physical profile')
    if profile.get('hardware_boundary_sha256')!=hardware_boundary_sha256:raise ValueError('hardware boundary mismatch')
    if profile.get('process')!='sky130hd':raise ValueError('wrong process')
    artifacts=profile['artifacts']
    required=('def','netlist','sdc','spef','metrics','toolchain','input_manifest','route_log','macro_pin_access')
    paths={name:bound_file(root,artifacts[name]) for name in required}
    metrics=json.loads(paths['metrics'].read_text())
    if metrics.get('clock_period_ns')!=10 or not finite(metrics.get('wns_ns')) or metrics['wns_ns']<0:raise ValueError('100 MHz timing failed')
    if any(type(metrics.get(key)) is not int or metrics[key]!=0 for key in ('drc_count','antenna_count')):raise ValueError('DRC/antenna failed')
    for key in ('def','netlist','sdc','spef','toolchain','input_manifest'):
        if metrics.get(key+'_sha256')!=artifacts[key]['sha256']:raise ValueError('unbound signoff metrics')
    pins=json.loads(paths['macro_pin_access'].read_text())
    if pins.get('def_sha256')!=artifacts['def']['sha256'] or pins.get('accessible') is not True:raise ValueError('macro pins not verified')
    expected={(operator,seed) for operator in operators for seed in range(1,11)}
    observed=set()
    for load in profile['loads']:
        key=(load['operator'],load['seed'])
        if key not in expected or key in observed:raise ValueError('duplicate/unexpected activity load')
        observed.add(key)
        if load.get('hardware_boundary_sha256')!=hardware_boundary_sha256:raise ValueError('cross-hardware activity')
        if load.get('backend')!=('rtlsim' if platform=='gpu' else 'rtl'):raise ValueError('non-RTL activity source')
        activity=bound_file(root,load['activity']);power_path=bound_file(root,load['power_report'])
        if activity.suffix.lower() not in ('.vcd','.saif'):raise ValueError('actual VCD/SAIF required')
        power=json.loads(power_path.read_text())
        if power.get('frequency_hz')!=100000000 or not finite(power.get('power_w')) or power['power_w']<=0:raise ValueError('invalid 100 MHz power')
        if power.get('activity_sha256')!=load['activity']['sha256'] or power.get('netlist_sha256')!=artifacts['netlist']['sha256']:raise ValueError('power source mismatch')
        if (power.get('operator'),power.get('seed'))!=key:raise ValueError('power copied across operator/seed')
        if power.get('input_sha256')!=load.get('input_sha256') or not load.get('input_sha256'):raise ValueError('unbound workload power')
    if observed!=expected:raise ValueError('missing per-operator/seed activity and power')
    # These checks establish metadata consistency, not a routed design. The
    # qualified OpenROAD/source-closure assembler must still verify raw reports,
    # exact design inputs and the activity-generation boundary before release.
    return {'status':'HOLD','binding_checks_passed':True,'physical_evidence_complete':False,
            'load_count':len(observed),'formal_baseline':False,
            'reason':'Mini route producer and raw signoff/source-closure integration are not qualified'}
