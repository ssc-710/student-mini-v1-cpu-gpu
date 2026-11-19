"""Fix private-producer root resolution; retain the failed launch unchanged."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_cpu_inflight_reset import producer_source
from scripts.resume_student_mini_interrupted import replace_once


def derive(source,root):
    source=producer_source(source)
    source=replace_once(source,'ROOT = Path(__file__).resolve().parents[1]',f'ROOT = Path({str(root)!r})')
    return replace_once(source,'paths = [Path(__file__),',
        "paths = [Path(__file__), ROOT/'scripts/run_student_mini_cpu_inflight_reset_v2.py',")


def main():
    original=ROOT/'scripts/run_student_mini_cpu_warm_reset.py'
    bindings={str(p):sha(p) for p in (Path(__file__),original,ROOT/'scripts/student_mini_cpu_inflight_reset.py',
        ROOT/'scripts/run_student_mini_cpu_inflight_reset.py')}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-inflight-reset-launch'/key;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT))
    bindings[str(producer)]=sha(producer)
    (work/'inputs.json').write_text(json.dumps(dict(bindings=bindings,arguments=sys.argv[1:],formal_baseline=False),indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status='QUEUED')),flush=True)
    with (work/'child.log').open('x') as output:
        code=subprocess.call([sys.executable,str(producer),*sys.argv[1:]],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    if any(sha(Path(p))!=v for p,v in bindings.items()):raise ValueError('in-flight reset source changed')
    (work/'completion.json').write_text(json.dumps(dict(exit_code=code,bindings=bindings,
        child_log_sha256=sha(work/'child.log'),formal_baseline=False),indent=2)+'\n')
    return code


if __name__=='__main__':raise SystemExit(main())
