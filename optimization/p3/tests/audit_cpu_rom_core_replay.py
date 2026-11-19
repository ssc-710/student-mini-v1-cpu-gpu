"""Independently bind the new ROM pair to the previously executed CSA workload."""
import hashlib
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
folder = BASE/'runs/cpu-current-rom-core-replay'
receipt = folder/'receipt.json'
preparation = folder/'preparation.json'
report = json.loads(receipt.read_text())
assert report['status'] == 'MATCHED_CURRENT_CSA_ROM_FULL_CORE_REPLAY_PASS'
for document in [report, json.loads(preparation.read_text())]:
    for name, digest in document['bindings'].items():
        assert sha(Path(name)) == digest, name
parent = BASE/'runs/cpu-rtl-comparison.json'
for name, digest in json.loads(parent.read_text())['bindings'].items():
    assert sha(ROOT/name) == digest, name
parent_log = BASE/'runs/cpu-rtl-diagnostic.log'

def parse(path):
    text = path.read_text()
    states = [dict(re.findall(r'(\w+)=([^ ]+)',line)) for line in text.splitlines()
              if line.startswith('STUDENT_NATIVE_TOKEN ')]
    assert [int(s['step']) for s in states] == list(range(11))
    assert [int(s['token']) for s in states] == [67,69,84,97,90,56,71,51,82,8,4]
    assert all(len(s['hidden'].split(',')) == 16 and len(s['logits'].split(',')) == 256 for s in states)
    assert len(re.findall(r'^STUDENT_NATIVE_CPU_COMPLETE count=11\b',text,re.M)) == 1
    timing = re.findall(r'^STUDENT_NATIVE_CPU status=0 count=11 cycles=(\d+):(\d+)',text,re.M)
    assert len(timing) == 1
    return states, (int(timing[0][0])<<32)+int(timing[0][1])

reference, cycles = parse(parent_log)
assert cycles == 11030645
for variant in ['original','banked']:
    states, measured = parse(folder/(variant+'-execute.log'))
    assert states == reference and measured == cycles
    assert report['results'][variant]['states'] == [line for line in (folder/(variant+'-execute.log')).read_text().splitlines()
                                                     if line.startswith('STUDENT_NATIVE_TOKEN ')]
    assert report['results'][variant]['generation_cycles'] == cycles
    assert report['results'][variant]['replay_cycles'] == 22527835
    work = BASE/'build/cpu-current-rom-core-replay'/variant
    for source in (BASE/'build/cpu-rtl/soc/gateware').glob('*.init'):
        assert sha(source) == sha(work/source.name)
output = folder/'independent-audit.json'
inputs = [Path(__file__),receipt,preparation,parent,parent_log,
          folder/'original-execute.log',folder/'banked-execute.log']
output.write_text(json.dumps(dict(status='PARENT_BOUND_CURRENT_ROM_CORE_REPLAY_AUDIT_PASS',
    variants=2,token_count=11,generation_cycles=cycles,replay_cycles=22527835,
    driven_clock=dict(period_ticks=10000,timeprecision_seconds=1e-12,period_ns=10,
                      firmware_configured_clock_hz=1000000,
                      warning='Driver clock differs from firmware constant; cycle equality only, not 1MHz driven time.'),
    bindings={str(f):sha(f) for f in inputs},
    limitation='Current CSA root5 RTL only. Does not establish unmapped-address equivalence, general instruction correctness, physical timing or power.'),indent=2)+'\n')
print('CPU_CURRENT_ROM_CORE_INDEPENDENT_AUDIT_PASS')
