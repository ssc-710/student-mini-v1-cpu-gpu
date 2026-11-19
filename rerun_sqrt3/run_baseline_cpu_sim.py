import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

here=Path(__file__).resolve().parent
out=here/'fresh-baselines'
work=Path('/mnt/d/sqrt3-rerun/baselines-cpu/soc/gateware')
binary=work/'obj_dir/Vsim'
for _ in range(1800):
    if binary.is_file():break
    time.sleep(2)
else:raise TimeoutError('CPU build did not produce simulator')
started=time.monotonic()
with (out/'cpu-console.log').open('x') as f:
    p=subprocess.Popen([str(binary)],cwd=work,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
    complete=False
    try:
        while p.poll() is None and time.monotonic()-started<3600:
            if 'STUDENT_CPU_COMPLETE count=1000' in (out/'cpu-console.log').read_text(errors='replace'):
                complete=True;break
            time.sleep(2)
    finally:
        if p.poll() is None:
            os.killpg(p.pid,signal.SIGTERM)
            p.wait(timeout=10)
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
(out/'cpu-run-receipt.json').write_text(json.dumps(dict(complete=complete,seconds=time.monotonic()-started,
    simulator_sha256=sha(binary),input_sha256=sha(out/'inputs.bin'),console_sha256=sha(out/'cpu-console.log'),
    stopped_after_completion=complete,exit_code=p.returncode),indent=2))
subprocess.run([os.sys.executable,str(here/'check_fresh_baselines.py')],check=True)
