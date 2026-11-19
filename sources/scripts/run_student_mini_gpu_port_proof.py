"""Source-bound two-port seam proof, not a whole-core equivalence claim."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_gpu_port_packing import restore_core_port_order,verify_export_order


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary',type=Path,required=True);args=parser.parse_args()
    export=args.boundary.resolve()/'project-banked.v'
    verify_export_order(export.read_text())
    tool=Path('/home/soclab/tools/oss-cad-suite/bin/iverilog')
    top=ROOT/'shared/rtl/vortex_physical_top.sv'
    bench=ROOT/'tests/rtl/student_mini_gpu_port_packing.sv'
    adapters=[ROOT/'shared/rtl'/name for name in ('vortex_command_adapter.sv','vortex_memory_adapter.sv')]
    paths=[Path(__file__),ROOT/'scripts/student_mini_gpu_port_packing.py',export,tool,tool.with_name('vvp'),top,bench,*adapters]
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-port-proof'/identity;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',whole_core_equivalence=False,formal_baseline=False,bindings=bindings,records=[],created_at=datetime.now(timezone.utc).isoformat())
    try:
        for label,source in [('original',top.read_text()),('fixed',restore_core_port_order(top.read_text()))]:
            path=work/(label+'.sv');path.write_text(source);binary=work/(label+'.vvp')
            compile_result=subprocess.run([str(tool),'-g2012','-s','bench','-o',str(binary),str(path),str(bench),*map(str,adapters)],capture_output=True,text=True,timeout=30)
            (work/(label+'-compile.log')).write_text(compile_result.stdout+compile_result.stderr)
            if compile_result.returncode:raise RuntimeError('seam compilation failed')
            for seed in range(1,11):
                observed=subprocess.run([str(tool.with_name('vvp')),str(binary),f'+seed={seed}'],capture_output=True,text=True,timeout=10)
                output=work/f'{label}-{seed}.log';output.write_text(observed.stdout+observed.stderr)
                accepted=(observed.returncode!=0 and 'PORT_REQUEST_MISMATCH' in observed.stdout) if label=='original' else (observed.returncode==0 and f'PORT_PACKING_PASS seed={seed} trials=64' in observed.stdout)
                result['records'].append(dict(variant=label,seed=seed,accepted=accepted,returncode=observed.returncode,output=str(output),sha256=sha(output)))
                if not accepted:raise ValueError('port seam expectation failed')
        if any(sha(Path(p))!=s for p,s in bindings.items()):raise ValueError('source changed')
        result.update(status='GPU_PORT_PACKING_SEAM_STAGE_PASS',reason='Original fails all ten seeds; six core-side slices fix requests/responses/backpressure/reset; external ABI unchanged')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='GPU_PORT_PACKING_SEAM_STAGE_PASS' else 1

if __name__=='__main__':raise SystemExit(main())
