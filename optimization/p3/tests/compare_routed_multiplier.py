"""Bind matched local routed evidence without extrapolating whole-core Fmax."""
import hashlib
import argparse
import json
from pathlib import Path
import re
BASE=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--verify-existing',action='store_true');p.add_argument('--report-id',default='gpu-multiplier-routed-outputbound-comparison');args=p.parse_args()
assert args.report_id not in ['.','..'] and not any(c in args.report_id for c in '/\\')
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
records={};bindings={};common_inputs=[];sdcs=[]
for label,route_id,case,extract_id in [
    ('vendor','gpu-multiplier-route-vendor','vendor-u30','gpu-multiplier-extract-vendor-u30'),
    ('limb','gpu-multiplier-route-hilomap','candidate-u30','gpu-multiplier-extract-limb-u30-outputbound')]:
    route=BASE/'physical'/route_id;extract=BASE/'physical'/extract_id
    receipt=json.loads((route/'receipt.json').read_text())
    selected=[r for r in receipt['records'] if r['case']==case];assert len(selected)==1
    row=selected[0];assert row['complete'] and row['exit_code']==0 and row['final_drt_violations']==0
    extracted=json.loads((extract/'receipt.json').read_text());assert extracted['status']=='LOCAL_EXTRACTED_STA_ONLY'
    for name,digest in extracted['outputs'].items():assert sha(extract/name)==digest, name
    shared={name:digest for name,digest in extracted['bindings'].items() if name.endswith(('openroad','local_extract.tcl','.lib','setRC.tcl','rcx_patterns.rules'))}
    assert len(shared)==5
    for name,digest in shared.items():assert sha(Path(name))==digest, name
    common_inputs.append(shared)
    assert extracted['bindings'][str(route/case/'routed.odb')]==sha(route/case/'routed.odb')
    wns=re.fullmatch(r'worst slack (-?[\d.]+)\s*',(extract/'wns-extracted.rpt').read_text());assert wns
    hold=re.findall(r'(-?[\d.]+)\s+slack \(MET\)',(extract/'hold-extracted.rpt').read_text());assert hold
    assert not (extract/'constraints-check.rpt').read_text().strip()
    records[label]=dict(wns_ns=float(wns[1]),hold_slack_ns=float(hold[-1]),routed_cell_area_um2=row['routed_cell_area_um2'],router_violations=0)
    for path in [route/'receipt.json',extract/'receipt.json',extract/'wns-extracted.rpt',extract/'hold-extracted.rpt',route/case/'routed.sdc']:
        bindings[str(path.relative_to(BASE))]=sha(path)
    constraints=(route/case/'routed.sdc').read_text()
    sdcs.append([line.strip() for line in constraints.splitlines() if line.strip() and not line.lstrip().startswith('#')])
    # Different instance/pin names are expected; common explicit timing budgets
    # must nevertheless be present on both elaborations.
    assert re.search(r'create_clock.*-period 10',constraints)
    assert 'set_input_delay' in constraints and 'set_output_delay' in constraints
assert common_inputs[0]==common_inputs[1] and sdcs[0]==sdcs[1], 'Tool/PDK/RC or timing budget mismatch'
result=dict(status='LOCAL_VENDOR_LIMB_ROUTED_COMPARISON',clock_ns=10,initial_utilization=0.30,
    corner='SKY130HD TT 1.8V 25C',records=records,
    wns_delta_ns=records['limb']['wns_ns']-records['vendor']['wns_ns'],
    routed_cell_area_ratio=records['limb']['routed_cell_area_um2']/records['vendor']['routed_cell_area_um2'],bindings=bindings,
    limitation='Same target/corner/density/delay budgets, real CTS/route/OpenRCX. Local arithmetic only; IO source slew/load not actual whole-core boundary. No whole-chip Fmax, activity power, antenna, PDN, LVS or corner signoff claim. Same-application RTL cycles were unchanged.')
out=BASE/'physical'/(args.report_id+'.json')
if args.verify_existing:
    assert json.loads(out.read_text())==result, 'Stored comparison differs from verified evidence'
else:
    assert not out.exists();out.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
