"""Small syntax/elaboration check only; not a real-core fault qualification."""
import hashlib
import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
run = BASE / 'runs/gpu-fault-wrapper-lint'
run.mkdir(parents=True, exist_ok=False)
(run / 'VX_define.vh').write_text('''`define SCOPE_IO_DECL
`define SCOPE_IO_SWITCH(n)
`define SCOPE_IO_BIND(n)
''')
package = '''package VX_gpu_pkg;
localparam VX_MEM_PORTS=2, VX_MEM_BYTEEN_WIDTH=64, VX_MEM_ADDR_WIDTH=26,
VX_MEM_DATA_WIDTH=512, VX_MEM_TAG_WIDTH=12, VX_DCR_ADDR_WIDTH=12,
VX_DCR_DATA_WIDTH=32;
endpackage
'''
wrapper = BASE / 'src/rtl/p3_gpu_fault_wrapper.sv'
body = wrapper.read_text()
ports = body.split('    localparam integer PENDING')[0]
stub = ports.replace('p3_gpu_fault_wrapper', 'Vortex') + '\nendmodule\n'
(run / 'stub.sv').write_text(package + stub)
adapter = ROOT / 'sources/integration/student-mini/gpu_fault_memory_adapter.sv'
verilator = ROOT / 'rerun_sqrt3/tools/verilator/bin/verilator'
command = [str(verilator), '--lint-only', '--assert', '-Wno-fatal',
           '-I' + str(run), '--top-module', 'p3_gpu_fault_wrapper',
           str(run / 'stub.sv'), str(adapter), str(wrapper)]
result = subprocess.run(command, cwd=run, capture_output=True, text=True)
(run / 'lint.log').write_text(result.stdout + result.stderr)
report = dict(status='LINT_PASS' if result.returncode == 0 else 'FAIL',
              exit_code=result.returncode, command=command,
              bindings={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in [wrapper, adapter, run / 'stub.sv']},
              limitation='Mock core/package syntax and elaboration only; no real Vortex, fault '
              'transaction, per-launch polling, target load, or protocol qualification.')
(run / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
if result.returncode:
    raise SystemExit(result.returncode)
