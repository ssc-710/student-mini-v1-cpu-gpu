"""Replay actual mapped SRAM views, without claiming whole-core equivalence.

Reads are checked at the next rising-edge setup boundary (100 MHz). The
OpenRAM behavioral model intentionally drives X after the sampling edge; idle
output stability and same-address read/write collision semantics are not proved.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import execute_locked_route


def transactions(shape, seed):
    width, depth, lanes = (shape[k] for k in ('width', 'depth', 'write_enable_width'))
    if width <= 0 or depth < 2 or lanes <= 0 or width % lanes or not 1 <= seed <= 10:
        raise ValueError('invalid memory shape/seed')
    dual = shape['module'] == 'VX_dp_ram_asic'
    if shape['module'] not in ('VX_sp_ram_asic', 'VX_dp_ram_asic'):
        raise ValueError('unsupported memory interface')
    rng = random.Random(seed)
    memory = [None]*depth
    rows = []
    def add(label, reset=0, read=0, write=0, mask=0, wa=0, ra=0, data=0):
        if not dual: ra = wa
        if read and write and wa == ra: raise ValueError('undefined collision excluded')
        expected = 0 if reset else memory[ra] if read else None
        if read and expected is None: raise ValueError('uninitialized read')
        if write:
            old = memory[wa] or 0
            for lane in range(lanes):
                bits = ((1 << (width//lanes))-1) << (lane*width//lanes)
                if mask & (1 << lane): old = (old & ~bits) | (data & bits)
            memory[wa] = old
        rows.append(dict(index=len(rows), label=label, seed=seed, reset=reset,
            read=read, write=write, mask=mask, write_address=wa, read_address=ra,
            input_hex=f'{data:x}', golden_hex=None if expected is None else f'{expected:x}'))
    add('cold-reset', reset=1)
    for addr in range(depth):
        add('initialize-all-addresses', write=1, mask=(1<<lanes)-1, wa=addr, data=rng.getrandbits(width))
    for addr in range(depth): add('read-all-addresses', read=1, wa=addr, ra=addr)
    for lane in range(lanes):
        addr = lane % depth
        add('one-mask-lane', write=1, mask=1<<lane, wa=addr, data=rng.getrandbits(width))
        add('read-mask-lane', read=1, wa=addr, ra=addr)
    add('zero-mask', write=1, mask=0, wa=depth-1, data=(1<<width)-1)
    add('read-zero-mask', read=1, wa=depth-1, ra=depth-1)
    for step in range(256):
        wa = rng.randrange(depth)
        ra = (wa + 1 + rng.randrange(depth-1)) % depth
        write = step % 3 != 0
        read = dual or not write
        add('random-independent-ports' if dual else 'random-single-port',
            read=int(read), write=int(write), mask=rng.getrandbits(lanes),
            wa=wa, ra=ra, data=rng.getrandbits(width))
    add('recovery-reset', reset=1)
    add('reset-idle', reset=1)
    add('idle-after-reset')
    for addr in range(depth): add('read-retained-after-reset', read=1, wa=addr, ra=addr)
    return rows


def bench(shape):
    width, depth, lanes = (shape[k] for k in ('width', 'depth', 'write_enable_width'))
    address = '.waddr(wa), .raddr(ra)' if shape['module']=='VX_dp_ram_asic' else '.addr(wa)'
    return f'''`timescale 1ns/1ps
module memory_witness;
  reg clk=0, reset=0, rd=0, wr=0;
  reg [{lanes-1}:0] mask=0;
  reg [$clog2({depth})-1:0] wa=0, ra=0;
  reg [{width-1}:0] data=0, expected;
  wire [{width-1}:0] actual;
  integer fd, count, index, check;
  reg [4095:0] input_path;
  always #5 clk=~clk;
  {shape['module']} #(.DATAW({width}), .SIZE({depth}), .WRENW({lanes})) dut
    (.clk(clk), .reset(reset), .read(rd), .write(wr), .wren(mask),
     {address}, .wdata(data), .rdata(actual));
  initial begin
    if (!$value$plusargs("input=%s", input_path)) $fatal(1,"missing input");
    fd=$fopen(input_path,"r");
    if (!fd) $fatal(1,"cannot open input");
    index=0;
    while (!$feof(fd)) begin
      @(negedge clk); #1;
      count=$fscanf(fd,"%d %d %d %h %h %h %h %d %h\\n",reset,rd,wr,mask,wa,ra,data,check,expected);
      if (count!=9) $fatal(1,"malformed input");
      @(posedge clk); @(negedge clk); #4;
      $display("MEMORY_SAMPLE index=%0d check=%0d golden=%h actual=%h",index,check,expected,actual);
      if (check && actual !== expected) $fatal(1,"memory result mismatch index=%0d",index);
      index=index+1;
    end
    $fclose(fd);
    $display("MEMORY_COMPLETE count=%0d",index);
    $finish;
  end
endmodule
'''


def parse_log(text, rows):
    samples = []
    pattern = re.compile(r'^MEMORY_SAMPLE index=(\d+) check=([01]) golden=([0-9a-fx]+) actual=([0-9a-fx]+)$')
    for line in text.splitlines():
        match = pattern.fullmatch(line)
        if not match: continue
        index, check, golden, actual = match.groups()
        if int(index) != len(samples) or int(index) >= len(rows): raise ValueError('duplicate/unordered sample')
        row = rows[int(index)]
        required = row['golden_hex'] is not None
        if int(check) != int(required): raise ValueError('check mask changed')
        if required and (int(golden,16) != int(row['golden_hex'],16) or 'x' in actual or int(actual,16) != int(golden,16)):
            raise ValueError('golden/actual mismatch')
        samples.append(dict(**row, actual_hex=actual, checked=required, delta=0 if required else None))
    terminal = [line for line in text.splitlines() if line.startswith('MEMORY_COMPLETE')]
    if len(samples) != len(rows) or terminal != [f'MEMORY_COMPLETE count={len(rows)}']:
        raise ValueError('incomplete memory replay')
    return samples


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary',type=Path,required=True)
    args=parser.parse_args(); boundary=args.boundary.resolve()
    parent_path=boundary/'completion.json'; parent=json.loads(parent_path.read_text())
    if parent.get('boundary_complete') is not True: raise ValueError('mapped boundary incomplete')
    bindings=dict(parent['bindings'])
    for name,digest in parent['artifacts'].items():
        if sha(boundary/name)!=digest: raise ValueError('mapped artifact changed')
    staged=ROOT/'grading/evidence/vortex-physical/staged-openram-banked-manifest.json'
    models=[Path(row['path']) for macro in json.loads(staged.read_text())['macros']
            for name,row in macro['artifacts'].items() if name.endswith('.v')]
    toolroot=Path('/home/soclab/tools/oss-cad-suite')
    paths=[Path(__file__),ROOT/'scripts/retry_student_mini_route.py',parent_path,boundary/'bindings.sv',
        ROOT/'shared/rtl/vortex_banked_large_sram_wrappers.sv',*models]
    paths += [toolroot/folder/name for folder in ('bin','libexec') for name in ('iverilog','vvp')]
    bindings.update({str(p):sha(p) for p in paths})
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-memory-witness'/identity; work.mkdir(parents=True,exist_ok=False)
    report=dict(status='HOLD',whole_core_equivalence=False,physical_evidence_complete=False,
        scope='Mapped SRAM behavioral models; checked read-valid/reset samples only; no collision or idle stability proof',
        clock_period_ns=10,seeds=list(range(1,11)),prng='Python random.Random MT19937',bindings=bindings,records=[])
    started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        if any(sha(Path(p))!=digest for p,digest in bindings.items()): raise ValueError('bound memory source changed')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX); fresh()
            for index,shape in enumerate(parent['logical_shapes']):
                directory=work/str(index); directory.mkdir()
                testbench=directory/'witness.sv'; testbench.write_text(bench(shape))
                executable=directory/'witness.vvp'
                command=[str(toolroot/'bin/iverilog'),'-g2012','-s','memory_witness','-o',str(executable),
                    str(testbench),str(boundary/'bindings.sv'),str(ROOT/'shared/rtl/vortex_banked_large_sram_wrappers.sv'),*map(str,models)]
                if execute_locked_route(command,directory/'compile.log',60,heartbeat): raise RuntimeError('memory witness compile failed')
                for seed in range(1,11):
                    rows=transactions(shape,seed); inputs=directory/f'seed-{seed}.txt'
                    inputs.write_text(''.join(f"{r['reset']} {r['read']} {r['write']} {r['mask']:x} {r['write_address']:x} {r['read_address']:x} {r['input_hex']} {int(r['golden_hex'] is not None)} {r['golden_hex'] or '0'}\n" for r in rows))
                    log=directory/f'seed-{seed}.log'
                    code=execute_locked_route([str(toolroot/'bin/vvp'),str(executable),'+input='+str(inputs)],log,60,heartbeat)
                    if code: raise RuntimeError(f'memory replay failed: shape {index}, seed {seed}; see {log.name}')
                    samples=parse_log(log.read_text(),rows)
                    output=directory/f'seed-{seed}.json'; output.write_text(json.dumps(samples,indent=2)+'\n')
                    report['records'].append(dict(shape=shape,seed=seed,samples=len(samples),checked=sum(r['checked'] for r in samples),output=str(output),sha256=sha(output)))
            fresh()
        report.update(status='MAPPED_MEMORY_WITNESS_STAGE_PASS',reason='All actual reachable shapes and seeds replayed; whole-core ASIC equivalence remains required')
    except Exception as error: report['reason']=f'{type(error).__name__}: {error}'
    heartbeat(report['status']); report['elapsed_seconds']=time.monotonic()-started
    report['artifacts']={p.relative_to(work).as_posix():sha(p) for p in work.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=report['status'],reason=report['reason'])),flush=True)
    return 0 if report['status']=='MAPPED_MEMORY_WITNESS_STAGE_PASS' else 1


if __name__=='__main__': raise SystemExit(main())
