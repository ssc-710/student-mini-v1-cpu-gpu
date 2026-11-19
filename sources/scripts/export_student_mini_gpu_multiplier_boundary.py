"""Export an independent whole GPU source after both arithmetic local proofs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.export_student_mini_gpu_sign_boundary import derive as sign_export
from scripts.student_mini_gpu_multiplier_overlay import validate_proof


def derive(source,root,proof):
    value=sign_export(source,root)
    changes={
        'from scripts.student_mini_gpu_sign_overlay import CONFIGS,checked_config,create_overlay':
        'from scripts.student_mini_gpu_multiplier_overlay import CONFIGS,checked_config,create_overlay,validate_proof',
        'files += [Path(__file__),':
        "files += [Path(__file__),ROOT/'scripts/export_student_mini_gpu_multiplier_boundary.py',ROOT/'scripts/student_mini_gpu_multiplier_overlay.py',ROOT/'scripts/student_mini_gpu_multiplier_cut.py',ROOT/'integration/student-mini/gpu_signed33_mul3.sv',Path("+repr(str(proof))+"),",
        "'build/student-mini/gpu-sign-boundary'":"'build/student-mini/gpu-multiplier-boundary'",
        "        overlay=work/'source';":
        "        mul_packet=Path("+repr(str(proof))+")\n"
        "        mul=json.loads(mul_packet.read_text())\n"
        "        validate_proof(mul,sha(ROOT/'integration/student-mini/gpu_signed33_mul3.sv'))\n"
        "        from scripts.retry_student_mini_route import verify\n"
        "        verify(mul['bindings']);bindings.update(mul['bindings'])\n"
        "        result.update(integer_multiplier_latency=3,old_counters_reusable=False)\n"
        "        overlay=work/'source';",
        '17 -> 57 enabled cycles (NR sign/update and normalization registers)':
        '17 -> 57 enabled cycles (NR sign/update and normalization registers); integer signed33 product split with unchanged 3 enabled clocks',
    }
    for old,new in changes.items():
        if value.count(old)!=1:raise ValueError('GPU multiplier export seam changed: '+old)
        value=value.replace(old,new)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-work',type=Path,required=True);parser.add_argument('--multiplier-proof',type=Path,required=True)
    args=parser.parse_args();proof=args.multiplier_proof.resolve()
    parsed=json.loads(proof.read_text());validate_proof(parsed,sha(ROOT/'integration/student-mini/gpu_signed33_mul3.sv'));verify(parsed['bindings'])
    original=ROOT/'scripts/export_student_mini_gpu_cut_boundary.py'
    paths=[Path(__file__),original,ROOT/'scripts/export_student_mini_gpu_sign_boundary.py',
        ROOT/'scripts/student_mini_gpu_multiplier_overlay.py',proof,args.unit_work.resolve()/'inputs.json']
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-multiplier-export-continuation'/key;work.mkdir(parents=True,exist_ok=False)
    private=work/'producer.py';private.write_text(derive(original.read_text(),ROOT,proof));bindings[str(private)]=sha(private)
    result=dict(status='HOLD',bindings=bindings,physical_evidence_complete=False,formal_baseline=False,
                arithmetic_latency=57,integer_multiplier_latency=3,old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='MULTIPLIER_GPU_EXPORT_QUEUED')),flush=True)
    with (work/'export.log').open('x') as log:
        code=subprocess.call([sys.executable,str(private),'--unit-work',str(args.unit_work.resolve())],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'export.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['export']=rows[-1]
    verify(bindings)
    if code==0 and result.get('export',{}).get('complete') is True:result['status']='GPU_MULTIPLIER_SOURCE_EXPORT_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('export'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
