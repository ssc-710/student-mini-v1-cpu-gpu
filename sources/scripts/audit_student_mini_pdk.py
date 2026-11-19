"""Compare routed OpenDB library/technology geometry to freshly loaded PDK.

This captures current PDK hashes honestly; it does not claim they were recorded
before the historical route. Agreement is checked against the actual routed
database. Library timing/power replay and complete physical qualification remain.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha


def lef_blocks(text):
    blocks={}
    for match in re.finditer(r'^(MACRO|LAYER|VIA) (\S+)(?: DEFAULT| GENERATED)?[ \t]*$',text,re.M):
        kind,name=match.groups()
        end=re.search(r'^END '+re.escape(name)+r'\s*$',text[match.end():],re.M)
        if not end:raise ValueError('unterminated LEF block '+name)
        block=text[match.start():match.end()+end.end()]
        # Whitespace is not geometry. Numbers, pin shapes and rules stay exact.
        canonical=' '.join(block.split())
        key=kind+':'+name
        if key in blocks and blocks[key]!=canonical:raise ValueError('conflicting LEF definition '+key)
        blocks[key]=canonical
    return blocks


def compare_geometry(reference,routed,used_masters):
    for key,value in reference.items():
        if routed.get(key)!=value:raise ValueError('routed PDK definition differs: '+key)
    if not any(key.startswith('LAYER:') for key in reference):raise ValueError('missing technology layers')
    if not used_masters:raise ValueError('empty routed design')
    for master in used_masters:
        key='MACRO:'+master
        if key not in reference or not master.startswith(('sky130_fd_sc_hd__','sky130_ef_sc_hd__')):
            raise ValueError('nonstandard/unknown macro requires explicit pin-access proof: '+master)
        block=reference[key]
        if not re.search(r'\bCLASS CORE(?: \w+)? ;',block):
            raise ValueError('macro is not a standard CORE cell: '+master)
    unexpected=[key for key in routed if key not in reference and not key.startswith('VIA:')]
    if unexpected:raise ValueError('unexpected routed geometry: '+','.join(unexpected[:5]))
    return dict(geometry_matches=True,standard_cell_master_count=len(used_masters),macro_count=0,
        macro_pin_access='NOT_APPLICABLE_NO_MACROS',
        generated_route_vias=sorted(key[4:] for key in routed if key.startswith('VIA:') and key not in reference),
        compared_definitions=len(reference))


def components(path):
    masters=set();declared=None;count=0;active=False;closed=False
    with path.open() as handle:
        for line in handle:
            line=line.strip()
            match=re.fullmatch(r'COMPONENTS\s+(\d+)\s*;',line)
            if match:declared=int(match[1]);active=True;continue
            if line=='END COMPONENTS':closed=active;active=False;break
            if active and line.startswith('- '):
                words=line.split()
                if len(words)<3:raise ValueError('malformed DEF component')
                masters.add(words[2]);count+=1
    if not declared or count!=declared or not closed:raise ValueError('incomplete DEF component inventory')
    return masters,count


def fresh_commands(pdk,probe):
    return [f'read_liberty {{{pdk}/lib/sky130_fd_sc_hd__tt_025C_1v80.lib}}',
        f'read_lef {{{pdk}/lef/sky130_fd_sc_hd.tlef}}',
        f'read_lef {{{pdk}/lef/sky130_fd_sc_hd_merged.lef}}',
        f'read_verilog {{{probe}}}', 'link_design pdk_geometry_probe',
        f'source {{{pdk}/setRC.tcl}}']


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement',type=Path,required=True)
    args=parser.parse_args();placement=args.placement.resolve()
    route_path=placement/'route/completion.json';route=json.loads(route_path.read_text())
    parent=json.loads((placement/'completion.json').read_text())
    if route.get('exit_code')!=0 or route.get('source_freshness_verified') is not True:raise ValueError('route not complete')
    result_dir=Path(parent['result_directory']);odb=result_dir/'6_final.odb';deffile=result_dir/'6_final.def'
    for path in (odb,deffile):
        if route['artifacts'].get(str(path))!=sha(path):raise ValueError('unbound routed geometry')
    pdk=Path('/home/soclab/src/orfs-clean-aabf2a/flow/platforms/sky130hd')
    lefs=[pdk/'lef/sky130_fd_sc_hd.tlef',pdk/'lef/sky130_fd_sc_hd_merged.lef']
    tool=Path('/home/soclab/.local/bin/openroad').resolve()
    bindings={str(p):sha(p) for p in [Path(__file__),route_path,odb,deffile,tool,*lefs,
        pdk/'config.mk',pdk/'lib/sky130_fd_sc_hd__tt_025C_1v80.lib',pdk/'rcx_patterns.rules',pdk/'setRC.tcl']}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/pdk-audit'/identity;work.mkdir(parents=True,exist_ok=False)
    # set_wire_rc needs a linked network even when only PDK LEF data is exported.
    # This fresh buffer design never imports cells/technology from the routed DB.
    probe=work/'pdk-probe.v'
    probe.write_text('module pdk_geometry_probe(input A, output X);\n  sky130_fd_sc_hd__buf_1 b (.A(A), .X(X));\nendmodule\n')
    result=dict(status='HOLD',physical_evidence_complete=False,bindings=bindings)
    started=time.monotonic()
    def run(name,commands):
        folder=work/name;folder.mkdir()
        script=folder/'audit.tcl'
        script.write_text('\n'.join([*commands,f'write_lef {{{folder}/library.lef}}','exit'])+'\n')
        with (folder/'openroad.log').open('x') as log:
            code=subprocess.run([str(tool),'-exit',str(script)],cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=180).returncode
        if code:raise RuntimeError(name+' OpenROAD replay failed')
        data={}
        for path in sorted(folder.glob('library*.lef')):
            for key,value in lef_blocks(path.read_text()).items():
                if key in data and data[key]!=value:raise ValueError('inconsistent library snapshot')
                data[key]=value
        return data
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX)
            if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('audit source changed while queued')
            # ORFS explicitly overrides LEF electrical defaults. Reproduce the
            # same bound RC setup; do not strip differences out of the comparison.
            expected=run('fresh-pdk',fresh_commands(pdk,probe))
            observed=run('routed-db',[f'read_db {{{odb}}}'])
            used,count=components(deffile)
            result.update(compare_geometry(expected,observed,used),component_count=count)
            if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('audit source changed during replay')
            result.update(status='PDK_GEOMETRY_STAGE_PASS',reason='Routed database geometry matches freshly read PDK; no macro pins in this standard-cell design. Timing-library/power/source qualification remains separate')
    except Exception as error:result.update(geometry_matches=False,reason=f'{type(error).__name__}: {error}')
    result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in work.rglob('*') if p.is_file()}
    (work/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result.get('geometry_matches') else 1


if __name__=='__main__':raise SystemExit(main())
