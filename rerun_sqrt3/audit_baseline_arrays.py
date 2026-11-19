from pathlib import Path
import json
import numpy as np

root=Path(__file__).resolve().parent.parent
out=root/'rerun_sqrt3/baseline-audit'
vectors=[json.loads(s) for s in (root/'data/golden/vectors.jsonl').read_text().splitlines()]
checks=[]
def check(label,ok):
    checks.append(dict(check=label,passed=bool(ok)))
for platform in ('cpu','gpu'):
    rows=[json.loads(s) for s in (root/f'data/records/{platform}.jsonl').read_text().splitlines()]
    with np.load(root/f'data/arrays/{platform}.npz',allow_pickle=False) as a:
        check(platform+':array_rows',all(len(a[k])==1000 for k in a.files))
        for i,r in enumerate(rows):
            g=vectors[r['ordinal']];bits=g['golden'].get('output_bits') or [];n=len(bits)
            check(f'{platform}:{i}:npz',a['ordinal'][i]==r['ordinal'] and a['seed'][i]==r['seed'] and a['length'][i]==n
                  and a['golden_bits'][i,:n].tolist()==bits and a['actual_bits'][i,:n].tolist()==r['observation']['actual_bits']
                  and np.all(a['signed_delta'][i,:n]==0))
            if r['case']['scenario'] not in ('backpressure','response-hold','reset-recovery'):
                continue
            e=r['observation']['protocol_events'];p=g['inputs']['protocol'];s=r['case']['scenario']
            ok=e['stability_violations']==0
            if platform=='cpu':
                ok=ok and e['completions']==1
                if s in ('backpressure','response-hold'):
                    ok=ok and e['stalled_cycles']>0
                else:
                    ok=ok and e['completions_before_reset']==0 and e['reset_cycle']>e['armed_cycle'] and e['payload_match']==1
            else:
                ok=ok and e['complete'] and e['commands']==e['responses'] and e['frames']>0
                if s=='backpressure':
                    ok=ok and e['stalled_req_cycles']>0 and e['stalled_rsp_cycles']>0
                elif s=='response-hold':
                    ok=ok and e['responses']>0 and e['held_rsp_cycles']==p['response_hold_cycles']*e['responses']
                else:
                    ok=ok and len(e['resets'])==1 and e['resets'][0]['busy_at_reset']==1 and len(e['reissues'])==1 and e['reissues'][0]['busy_after_start']==1
            check(f'{platform}:{i}:protocol_raw_counters',ok)
result=dict(scope='NPZ cross-check and packaged protocol counter consistency; not fresh execution',
            checks=len(checks),passed=sum(c['passed'] for c in checks),failures=[c for c in checks if not c['passed']])
(out/'arrays-and-protocol.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
