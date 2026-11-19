"""Bounded proof of the actual full-word Wishbone CSR bridge, not the full SoC."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import execute_locked_route

MUTATIONS = [
    ('request-hold', 'state_q == REQUEST;', 'state_q == REQUEST && csr_req_ready_i;'),
    ('wrong-address', '{wb_adr_i[5:0], 2\'b00}', '{wb_adr_i[5:0], 2\'b01}'),
    ('wrong-data', 'wdata_q <= wb_dat_w_i;', 'wdata_q <= wb_dat_w_i ^ 1;'),
    ('wrong-direction', 'write_q <= wb_we_i;', 'write_q <= !wb_we_i;'),
    ('wrong-response', 'wb_dat_r_o <= csr_rdata_i;', 'wb_dat_r_o <= csr_rdata_i ^ 1;'),
    ('early-ack', 'wb_ack_o = state_q == ACK;', 'wb_ack_o = state_q == RESPONSE;'),
    ('error-bit', "wb_err_o = 1'b0;", "wb_err_o = 1'b1;"),
    ('reset-state', 'state_q <= IDLE;', 'state_q <= REQUEST;'),
]


def mutate(source, name):
    _, old, new = next(row for row in MUTATIONS if row[0] == name)
    expected = 3 if name == 'reset-state' else 1
    if source.count(old) != expected:
        raise ValueError('mutation target multiplicity differs: '+name)
    # Only the reset assignment is first; do not mutate the ACK/default paths.
    return source.replace(old, new, 1)


def main():
    import fcntl
    rtl = ROOT/'shared/rtl/litex_wishbone_csr_bridge.sv'
    harness = ROOT/'shared/formal/student_mini_wishbone_contract_harness.sv'
    toolroot = Path('/home/soclab/tools/oss-cad-suite/bin')
    paths = [rtl, harness, Path(__file__), ROOT/'scripts/retry_student_mini_route.py']
    paths += [toolroot/name for name in ('yosys', 'sby', 'yosys-smtbmc', 'boolector')]
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/wishbone-formal'/identity
    work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', formal_baseline=False, whole_soc_protocol=False,
        scope='Full-word Wishbone classic CSR bridge only; partial byte writes and LiteDRAM controller are NOT proved',
        assumptions=['wb_sel=0xf', 'master holds request until ACK or reset'],
        depth=32, bindings=bindings, records=[])
    started = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        if any(sha(Path(p)) != digest for p, digest in bindings.items()):
            raise ValueError('formal source changed')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE')
            print(json.dumps(dict(work=str(work), stage='WAITING_FOR_SERIAL_QUEUE')), flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
            fresh()
            for name in ['baseline', *(row[0] for row in MUTATIONS)]:
                directory = work/name
                directory.mkdir()
                (directory/rtl.name).write_text(rtl.read_text() if name=='baseline' else mutate(rtl.read_text(), name))
                (directory/harness.name).write_text(harness.read_text())
                for mode in (['bmc', 'cover'] if name=='baseline' else ['bmc']):
                    config = directory/(mode+'.sby')
                    config.write_text(f'[options]\nmode {mode}\ndepth 32\n[engines]\nsmtbmc boolector\n[script]\nread -formal {rtl.name} {harness.name}\nprep -top student_mini_wishbone_contract_harness\n[files]\n{directory/rtl.name}\n{directory/harness.name}\n')
                    command = ['env', 'PATH='+str(toolroot)+':/usr/local/bin:/usr/bin:/bin',
                        str(toolroot/'sby'), '-d', str(directory/mode), str(config)]
                    code = execute_locked_route(command, directory/(mode+'.log'), 180,
                                                lambda _: heartbeat(name+'-'+mode))
                    statusfile = directory/mode/'status'
                    status = statusfile.read_text().split()[0] if statusfile.is_file() else 'ERROR'
                    expected = 'PASS' if name=='baseline' else 'FAIL'
                    row = dict(name=name, mode=mode, status=status, expected=expected,
                               accepted=status==expected, exit_code=code)
                    result['records'].append(row)
                    if not row['accepted']:
                        raise ValueError('proof/mutation expectation not met: '+name)
            fresh()
        result.update(status='ADAPTER_PROTOCOL_STAGE_PASS', reason='32-step bounded proof and eight mutations passed; complete SoC qualification remains separate')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic()-started
    heartbeat(result['status'])
    result['artifacts'] = {p.relative_to(work).as_posix(): sha(p) for p in work.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status']=='ADAPTER_PROTOCOL_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
