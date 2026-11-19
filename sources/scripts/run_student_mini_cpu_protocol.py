"""CPU protocol qualification (MINI-31 backpressure, MINI-32 response hold, MINI-33 reset recovery).

The final CPU mapping is compiled exactly as in its passing full replay
(same sources, reference memory environment, mapped netlist and macro model);
the bridge only gains two testbench inputs: the ready of the CPU's UART result
stream and an extra reset OR-ed into asic_reset_i.  Driver:
tests/rtl/student_mini_cpu_protocol_main.cpp.

The firmware (ROM, physically implemented) walks the 1000-record input image
from slot 0, reads each record only from its slot and prints the slot index as
the ordinal.  Each session's SDRAM image therefore holds the target record's
frozen bytes in slot 0 (byte-identical copy), so the target executes right after
boot; the session ends when the target record completes.  Per target:
  MINI-31  ready low with the case's probability from its backpressure seed
  MINI-32  every result byte held `response_hold_cycles` cycles
  MINI-33  reset 2000 cycles after the target record started; after reboot
           the CPU re-executes and the target must complete exactly once
The target's UART record must equal the executed CPU's reference record and,
independently, the frozen golden (status, bits, selection, primitive).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify

RECORD_BYTES = 1936
MAGIC = 0x31494e4d
COLUMNS = 512          # LiteDRAM sim SDRAM: 16-byte lines, row/bank/column interleave
DRIVER = ROOT / 'tests/rtl/student_mini_cpu_protocol_main.cpp'
CASES = ('MINI-31', 'MINI-32', 'MINI-33')
RESET_AFTER = 2000
LINE = re.compile(r'^STUDENT_CPU_PROTOCOL (.*)$', re.M)


def bridge_source(text):
    head = 'module cpu_boundary_replay(input wire sys_clk,output wire [7:0] uart_data,output wire uart_valid);'
    if text.count(head) != 1:
        raise ValueError('replay bridge header changed')
    text = text.replace(head, head.replace('output wire uart_valid);', 'output wire uart_valid,input wire uart_ready,input wire tb_reset);'))
    start = text.index(' actual(')
    end = text.index(');', start)
    inst = text[start:end]
    for old, new in (('.serial_source_ready(1\'b1)', '.serial_source_ready(uart_ready)'),
                     ('.asic_reset_i(independent_memory.build_soc_coursesimsoc_int_rst)',
                      '.asic_reset_i(independent_memory.build_soc_coursesimsoc_int_rst | tb_reset)')):
        if inst.count(old) != 1:
            raise ValueError('actual instance connection changed: ' + old)
        inst = inst.replace(old, new)
    return text[:start] + inst + text[end:]


def image_lines(banks, offset, length):
    """(bank, line, byte offset in line) for each 16-byte line of [offset, offset+length)."""
    out = []
    for line in range(offset // 16, (offset + length + 15) // 16):
        col, bank, row = line % COLUMNS, (line // COLUMNS) % 4, line // (4 * COLUMNS)
        out.append((bank, row * COLUMNS + col, line))
    return out


def read_image(banks, offset, length):
    data = bytearray()
    for bank, index, line in image_lines(banks, offset, length):
        data += bytes.fromhex(banks[bank][index])[::-1] if index < len(banks[bank]) else bytes(16)
    start = offset - 16 * (offset // 16)
    return bytes(data[start:start + length])


def write_image(banks, offset, payload):
    lines = image_lines(banks, offset, len(payload))
    first = lines[0][2] * 16
    buffer = bytearray(read_image(banks, first, 16 * len(lines)))
    buffer[offset - first:offset - first + len(payload)] = payload
    for k, (bank, index, line) in enumerate(lines):
        while len(banks[bank]) <= index:
            banks[bank].append('0' * 32)
        banks[bank][index] = bytes(buffer[16 * k:16 * k + 16])[::-1].hex()


def golden_match(vector, observed):
    """Same acceptance as assemble_student_mini_cpu_results.join for one record."""
    import struct
    from scripts.student_mini import compare_outputs
    golden, case = vector['golden'], vector['case']
    if not golden['output_values']:
        return observed['actual_status'] == golden['expected_status'] and not observed['actual_bits']
    actual = [struct.unpack('<f', struct.pack('<I', b << 16))[0] for b in observed['actual_bits']]
    comparison = compare_outputs(golden['output_values'], actual, golden['output_bits'], observed['actual_bits'])
    match = comparison['status'] == 'PASS' and observed['actual_status'] == golden['expected_status']
    if case['operator'] == 'p1':
        match = match and observed['selected'] == [x for ids in golden['selected_token_ids'] for x in ids]
    if 'primitive_witness_result' in golden:
        match = match and observed['primitive'] == golden['primitive_witness_result']
    return match


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True, help='passing ROM-bank full replay child directory')
    parser.add_argument('--vectors', type=Path, required=True)
    parser.add_argument('--ordinals', type=int, nargs='*')
    parser.add_argument('--parallel', type=int, default=2)
    args = parser.parse_args()
    replay = args.replay.resolve()
    child = json.loads((replay / 'completion.json').read_text())
    if child['status'] != 'CPU_ROM_BANKS_COLD_START_REPLAY_STAGE_PASS' or child['transcript_join']['baseline_records'] != 1000:
        raise ValueError('passing complete ROM-bank replay required')
    verify(child['bindings'])
    for name, digest in child['artifacts'].items():
        if sha(replay / name) != digest:
            raise ValueError('replay artifact changed: ' + name)
    cpu = Path(child['parent_cpu'])
    loader = cpu / 'loader.bin'
    reference = (cpu / 'console.log').read_text()
    vectors = [json.loads(line) for line in args.vectors.read_text().splitlines()]
    targets = args.ordinals or [i for i, v in enumerate(vectors) if v['case']['id'].split('-', 1)[1] in CASES]
    command = list(child['compile_command'])
    bindings = {str(p): sha(p) for p in (Path(__file__), DRIVER, replay / 'completion.json', loader, cpu / 'console.log',
                                         args.vectors.resolve(), ROOT / 'scripts/assemble_student_mini_cpu_results.py')}
    key = hashlib.sha256(json.dumps(dict(bindings=bindings, targets=targets), sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/cpu-protocol' / key
    work.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    result = dict(status='HOLD', bindings=bindings, targets=targets, target_slot=0, reset_after_cycles=RESET_AFTER,
                  interface='CPU die UART result stream (ready/valid) and asic_reset_i; DFI has no handshake', records=[])
    try:
        bridge = work / 'bridge.sv'
        bridge.write_text(bridge_source((replay / 'bridge.sv').read_text()))
        old_bridge, old_driver = str(replay / 'bridge.sv'), str(ROOT / 'tests/rtl/student_mini_cpu_failfast_main.cpp')
        if command.count(old_bridge) != 1 or command.count(old_driver) != 1:
            raise ValueError('replay compile command layout changed')
        command[command.index(old_bridge)] = str(bridge)
        command[command.index(old_driver)] = str(DRIVER)
        command[command.index('--Mdir') + 1] = str(work / 'obj')
        result['compile_command'] = command
        with (work / 'compile.log').open('x') as log:
            if subprocess.call(command, cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=3600):
                raise RuntimeError('protocol replay compile failed')
        binary = work / 'obj/Vcpu_boundary_replay'
        image = loader.read_bytes()
        banks0 = [(replay / f'sim_mem_{k}.init').read_text().split() for k in range(1, 5)]
        for i in range(1000):
            if read_image(banks0, i * RECORD_BYTES, 4) != MAGIC.to_bytes(4, 'little') or \
                    int.from_bytes(read_image(banks0, i * RECORD_BYTES + 8, 4), 'little') != i:
                raise ValueError(f'record {i} not found at its image slot')
            if image[i * RECORD_BYTES:(i + 1) * RECORD_BYTES] != read_image(banks0, i * RECORD_BYTES, RECORD_BYTES):
                raise ValueError(f'SDRAM image differs from the loader at record {i}')

        def session(target):
            folder = work / f'{target:04d}'
            folder.mkdir()
            banks = [list(b) for b in banks0]
            write_image(banks, 0, image[target * RECORD_BYTES:(target + 1) * RECORD_BYTES])
            if read_image(banks, 0, RECORD_BYTES) != image[target * RECORD_BYTES:(target + 1) * RECORD_BYTES]:
                raise ValueError('slot-0 placement failed')
            for k in range(4):
                (folder / f'sim_mem_{k + 1}.init').write_text('\n'.join(banks[k]) + '\n')
            for name in ('sim_mem.init', 'sim_rom.init', 'sim_sram.init'):
                shutil.copyfile(replay / name, folder / name)
            expected = [l for l in reference.splitlines() if l.startswith(f'STUDENT_CPU ordinal={target} ')]
            if len(expected) != 1:
                raise ValueError(f'no unique reference record for {target}')
            (folder / 'expected.txt').write_text(expected[0].replace(f'ordinal={target} ', 'ordinal=0 ', 1) + '\n')
            p = vectors[target]['inputs']['protocol']
            setting = f"0,{int(round(p['backpressure_probability'] * 256))},{p['backpressure_seed']}," \
                      f"{p['response_hold_cycles']},{RESET_AFTER if p['reset_and_reissue'] else 0}"
            then = time.monotonic()
            warnings = 0
            with (folder / 'console.log').open('x') as log:
                child = subprocess.Popen([str(binary), str(folder / 'expected.txt')], cwd=folder, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, env=dict(os.environ, STUDENT_MINI_CPU_PROTOCOL=setting), text=True,
                                         errors='replace')
                for text_line in child.stdout:
                    # OpenRAM behavioural-model notices (same-address read/write) are counted, not logged.
                    if 'WARNING: Writing and reading' in text_line:
                        warnings += 1
                    else:
                        log.write(text_line)
                code = child.wait(timeout=7200)
            for k in range(1, 5):
                (folder / f'sim_mem_{k}.init').unlink()
            text = (folder / 'console.log').read_text(errors='replace')
            summary = LINE.findall(text)
            events = {k: int(v) for k, v in (kv.split('=') for kv in summary[-1].split())} if summary else {}
            line = [l.replace('STUDENT_CPU ordinal=0 ', f'STUDENT_CPU ordinal={target} ', 1)
                    for l in text.splitlines() if l.startswith('STUDENT_CPU ordinal=0 ')]
            return dict(ordinal=target, case_id=vectors[target]['case']['id'], seed=vectors[target]['seed'], setting=setting,
                        exit_code=code, seconds=time.monotonic() - then, events=events, record_line=line[-1] if line else None,
                        console_sha256=sha(folder / 'console.log'), macro_model_notices=warnings)

        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            for row in pool.map(session, targets):
                result['records'].append(row)
                (work / 'progress.json').write_text(json.dumps(result['records'], indent=1) + '\n')
                print(json.dumps({k: row[k] for k in ('ordinal', 'case_id', 'seed', 'exit_code', 'seconds')}), flush=True)
        verify(bindings)
        # Independent check of each target record against the frozen golden.
        from scripts.assemble_student_mini_cpu_results import parse
        rows = sorted(result['records'], key=lambda r: r['ordinal'])
        for r in rows:
            if r['record_line'] is None:
                raise ValueError(f'target {r["ordinal"]} produced no record')
            text = r['record_line'].replace(f'ordinal={r["ordinal"]} ', 'ordinal=0 ', 1) + '\nSTUDENT_CPU_COMPLETE count=1\n'
            r['observation'] = parse(text, 1)[0]
            r['numeric_match'] = golden_match(vectors[r['ordinal']], r['observation'])
        failures = []
        for r in rows:
            e = r['events']
            p = vectors[r['ordinal']]['inputs']['protocol']
            checks = {'exactly-one-completion': e.get('completions') == 1,
                      'stable-response-until-ready': e.get('stability_violations') == 0 and
                          (e.get('stalled_cycles', 0) > 0 if (p['backpressure_probability'] or p['response_hold_cycles']) else True)}
            if p['reset_and_reissue']:
                checks.update({'no-spurious-pre-reset-completion': e.get('completions_before_reset') == 0 and e.get('reset_cycle', -1) > e.get('armed_cycle', 0),
                               'reissued-command-passes': bool(e.get('payload_match')) and r['numeric_match'] is True})
            r['actual_events'] = sorted(k for k, ok in checks.items() if ok)
            r['expected_events'] = vectors[r['ordinal']]['golden']['expected_events']
            r['status'] = 'PASS' if (r['exit_code'] == 0 and all(checks.values()) and r['numeric_match'] is True
                                     and sorted(r['expected_events']) == r['actual_events']) else 'FAIL'
            if r['status'] != 'PASS':
                failures.append(r['ordinal'])
        result.update(records=rows, failures=failures,
                      status='CPU_PROTOCOL_QUALIFICATION_PASS' if not failures else 'CPU_PROTOCOL_QUALIFICATION_FAIL')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic() - started
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], failures=result.get('failures'), reason=result.get('reason'))), flush=True)
    return 0 if result['status'] == 'CPU_PROTOCOL_QUALIFICATION_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
