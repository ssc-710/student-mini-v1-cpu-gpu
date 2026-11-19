"""Local real-ROM proof for a two-edge read; not whole-CPU qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.student_mini_cpu_rom_request_cut import project
from scripts.student_mini_cpu_rom_cut import ADDRESS, DATA


def isolated(source):
    """Extract verbatim initialized storage and the actual bank read logic."""
    pattern = r"  reg \[31:0\] rom \[(\d+):0\];\n  initial begin\n((?:    rom\[\d+\] = 32'd\d+;\n)+)  end\n"
    blocks = list(re.finditer(pattern, source))
    if len(blocks) != 1 or int(blocks[0][1]) != 12557:
        raise ValueError('exact frozen 12558-word ROM required')
    block = blocks[0]
    rows = re.findall(r"rom\[(\d+)\] = 32'd(\d+);", block[2])
    if [int(a) for a, _ in rows] != list(range(12558)):
        raise ValueError('ROM words missing or reordered')
    start = source.index('  reg [31:0] mini_rom_bank_data [0:24];')
    end = source.index(f'  assign {DATA} = mini_rom_bank_data[mini_rom_bank_q];', start)
    bank = source[start:end] + '  assign data = mini_rom_bank_data[mini_rom_bank_q];\n'
    if bank.count('mini_rom_request_address') != 2 or ADDRESS in bank:
        raise ValueError('read must use captured address only')
    header = '''module actual_rom(input clk, reset, cyc, stb, input [14:0] address,
    output ack, output [31:0] data);
  wire sys_clk=clk;
  wire [14:0] mini_rom_request_address;
  student_mini_cpu_rom_request_cut request(.clk(clk),.reset(reset),.cyc(cyc),.stb(stb),
    .address(address),.rom_address(mini_rom_request_address),.ack(ack));
'''
    # The asynchronous oracle is independent of the candidate's request/bank logic.
    oracle = 'module golden_rom(input [14:0] address, output [31:0] data);\n'+block.group()+'  assign data=rom[address];\nendmodule\n'
    return header+block.group()+bank+'endmodule\n'+oracle


def check_rows(text):
    rows = [x for x in text.splitlines() if x.startswith('ROM_REQUEST_ROW ')]
    if len(rows) != 37888 or text.splitlines().count('ROM_REQUEST_WORDS_PASS addresses=32768 seeds=10 random_rows=5120') != 1:
        raise ValueError('incomplete real-ROM coverage')
    for index, line in enumerate(rows):
        m = re.fullmatch(r'ROM_REQUEST_ROW seed=(\d+) address=(\d+) golden=([0-9a-fx]{8}) actual=([0-9a-fx]{8})', line)
        if not m or m[3] != m[4]: raise ValueError('complete ROM word mismatch')
        expected_seed = 0 if index < 32768 else 1+(index-32768)//512
        if int(m[1]) != expected_seed or not 0 <= int(m[2]) < 32768:
            raise ValueError('ROM seed/address coverage changed')
        if index < 32768 and int(m[2]) != index: raise ValueError('exhaustive address missing')
    return dict(records=len(rows), exhaustive_addresses=32768, random_seeds=list(range(1,11)),
                random_rows=5120, initialized_words=12558, undefined_addresses_checked_as_unknown=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping',type=Path,required=True)
    args=parser.parse_args(); parent=args.mapping.resolve(); receipt=parent/'completion.json'
    previous=json.loads(receipt.read_text())
    if previous.get('status')!='CPU_TAG_BANK_MAPPING_STAGE_PASS' or previous.get('macro_count')!=29:
        raise ValueError('qualified 29-macro bank-tag source required')
    bindings=dict(previous['bindings']); verify(bindings)
    for name,digest in previous['artifacts'].items():
        if sha(parent/name)!=digest: raise ValueError('parent artifact changed')
        bindings[str(parent/name)]=digest
    tools=Path('/home/soclab/tools/oss-cad-suite/bin')
    module=ROOT/'tests/rtl/student_mini_cpu_rom_request_cut.sv'
    bench=ROOT/'tests/rtl/student_mini_cpu_rom_request_words_tb.sv'
    handshake=ROOT/'tests/rtl/student_mini_cpu_rom_request_cut_tb.sv'
    paths=[Path(__file__),ROOT/'scripts/student_mini_cpu_rom_request_cut.py',receipt,module,bench,handshake,
           tools/'iverilog',tools/'vvp']
    bindings.update({str(p):sha(p) for p in paths})
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-rom-request-proof'/identity;work.mkdir(parents=True,exist_ok=False)
    mapped=work/'candidate.v';mapped.write_text(project((parent/'mapped.v').read_text(),module.read_text()))
    rom=work/'rom.sv';rom.write_text(isolated(mapped.read_text())+module.read_text())
    bindings.update({str(p):sha(p) for p in (mapped,rom)})
    result=dict(status='HOLD',bindings=bindings,parent=str(parent),formal_baseline=False,
                physical_evidence_complete=False,whole_core_equivalence=False,read_latency_cycles=2)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
    def run(name,sources):
        binary=work/(name+'.vvp')
        compiled=subprocess.run([str(tools/'iverilog'),'-g2012','-s','bench','-o',str(binary),*map(str,sources)],capture_output=True,text=True,timeout=60)
        (work/(name+'-compile.log')).write_text(compiled.stdout+compiled.stderr)
        if compiled.returncode: raise ValueError('compile failed: '+name)
        executed=subprocess.run([str(tools/'vvp'),str(binary)],capture_output=True,text=True,timeout=60)
        (work/(name+'.log')).write_text(executed.stdout+executed.stderr)
        return executed
    try:
        actual=run('real-rom',[rom,bench])
        if actual.returncode: raise ValueError('real ROM word/timing proof failed')
        result['real_rom']=check_rows(actual.stdout)
        positive=run('handshake',[module,handshake])
        if positive.returncode or positive.stdout.count('ROM_REQUEST_CUT_PASS seeds=10 transactions=1300 cancel_reset_recovery=20')!=1:
            raise ValueError('handshake positive control failed')
        mutations={
            'wrong-address': ('rom_address <= address;', "rom_address <= address+15'd1;"),
            'early-ack': ('(state == 2)', '(state == 1)'),
            'ignore-cancel': ('reset || !cyc || !stb', 'reset'),
            'ignore-reset': ('reset || !cyc || !stb', '!cyc || !stb'),
        }
        killed=[]
        for name,(old,new) in mutations.items():
            text=module.read_text()
            if text.count(old)!=1: raise ValueError('mutation seam changed: '+name)
            mutant=work/(name+'.sv');mutant.write_text(text.replace(old,new))
            negative=run(name,[mutant,handshake])
            if negative.returncode==0: raise ValueError('surviving handshake mutation: '+name)
            killed.append(name)
        result.update(status='CPU_ROM_REQUEST_LOCAL_PROOF_STAGE_PASS',mutations_killed=killed,
                      reason='Real ROM complete words and two-edge handshake verified locally; whole CPU, protocol/formal and physical closure remain')
        verify(bindings)
    except Exception as error: result['reason']=f'{type(error).__name__}: {error}'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_ROM_REQUEST_LOCAL_PROOF_STAGE_PASS' else 1


if __name__=='__main__': raise SystemExit(main())
