"""Expected-vs-actual event attestation for every student-mini record.

Each golden record lists expected events.  An event is attested only from a
named piece of evidence of the platform's own execution; anything not
attested stays missing and keeps the record HOLD.  Evidence kinds:
  * the record's own execution (status, output payload, counters, DMA log);
  * the protocol qualification run of the same case/seed (MINI-31/32/33);
  * a primitive witness executed on the platform's numeric RTL (accelerator).
"""
from __future__ import annotations

NORMAL = ('exactly-one-completion', 'stable-response-until-ready')
ERROR = ('error-response', 'no-output-commit', 'no-new-payload-dma-after-error')


def scenario(row):
    return row['case']['id'].split('-', 1)[1]


def _normal(observation, stalls_tested=False):
    """Plain records: one completion; ready was held high so every response was
    accepted the cycle it appeared (stability under stall is MINI-31/32)."""
    return {'exactly-one-completion': 'one completion record for this case/seed in the execution transcript',
            'stable-response-until-ready': ('checked under stalls by the protocol run' if stalls_tested else
                                            'response accepted when presented (ready held high; stall behaviour qualified by MINI-31/32)')}


def accelerator_events(row, raw, witness):
    """raw: the testbench row (status, transactions, reset_observation); witness: component-RTL witness row or None."""
    expected = row['golden']['expected_events']
    out = {}
    ok = row['comparison']['status'] == 'PASS'
    transactions = raw.get('transactions') or []
    if raw.get('actual_status') == 'OK':
        if ok:
            out.update(_normal(raw, stalls_tested=row['inputs']['protocol']['response_hold_cycles'] > 0))
            if row['inputs']['protocol']['backpressure_probability'] > 0:
                out['stable-response-until-ready'] = 'memory model stalled ready with the seeded probability; command completed bit-exact'
        reset = raw.get('reset_observation')
        if reset and reset.get('command_accepted'):
            out['no-spurious-pre-reset-completion'] = (f"probe command accepted, no response for {reset['abort_after_cycles']} cycles "
                                                       f"before reset and {reset['silent_post_reset_cycles']} after")
            if ok:
                out['reissued-command-passes'] = 'reissued command completed bit-exact after the reset'
    else:
        if raw.get('actual_status') == row['golden']['expected_status']:
            out['error-response'] = f"status {raw['actual_status']}"
            if transactions and not any(write for _, write in transactions):
                out['no-output-commit'] = 'DMA log contains no write transaction'
                out['no-new-payload-dma-after-error'] = (f'DMA log ends at the transaction that exposed the error '
                                                         f'(0x{transactions[-1][0]:x}); the response followed')
    if 'primitive-witness-executed-on-target' in expected and witness and witness.get('status') == 'PASS' \
            and witness.get('expected') == witness.get('actual') and not witness.get('bit_mismatch'):
        out['primitive-witness-executed-on-target'] = (f"{witness['auxiliary_kind']} executed on the accelerator platform's numeric RTL "
                                                       f"(component-level, {witness.get('source')}); result {witness['actual']} = expected")
    return out


def _own_primitive(row, out, who):
    """CPU/GPU execute the primitive witness inside the record's own firmware/kernel run."""
    golden = row['golden']
    if 'primitive_witness_result' in golden and row['observation'].get('primitive') == golden['primitive_witness_result']:
        out['primitive-witness-executed-on-target'] = (f"primitive computed by the {who} during this record "
                                                       f"(primitive={row['observation']['primitive']} = expected)")


def cpu_events(row, protocol):
    """protocol: the CPU protocol-session row for MINI-31/32/33 records, else None."""
    obs = row['observation']
    out = {}
    ok = row['comparison']['status'] == 'PASS'
    name = scenario(row)
    if obs['actual_status'] == 'OK':
        if ok and name not in ('MINI-31', 'MINI-32', 'MINI-33'):
            out.update(_normal(obs))
    elif obs['actual_status'] == row['golden']['expected_status']:
        out['error-response'] = f"status {obs['actual_status']}"
        if not obs.get('actual_bits'):
            out['no-output-commit'] = 'status-only record: no output payload reported'
            dma = obs.get('dma_bytes')
            if dma == 0:
                out['no-new-payload-dma-after-error'] = 'DMA byte counter 0: the error was raised before any payload transfer'
            elif dma == 16 and obs['actual_status'] == 'BUS_ERROR':
                out['no-new-payload-dma-after-error'] = 'DMA byte counter 16: only the faulting 128-bit beat was transferred'
    _own_primitive(row, out, 'VexRiscv firmware')
    if protocol is not None and protocol.get('status') == 'PASS':
        for event in protocol['actual_events']:
            out[event] = f"CPU protocol session ({protocol['setting']}): {protocol['events']}"
    return out


def gpu_events(row, protocol):
    obs = row['observation']
    out = {}
    ok = row['comparison']['status'] == 'PASS'
    name = scenario(row)
    if obs['actual_status'] == 'OK':
        if ok and name not in ('MINI-31', 'MINI-32', 'MINI-33'):
            out.update(_normal(obs))
    elif obs['actual_status'] == row['golden']['expected_status']:
        out['error-response'] = f"status {obs['actual_status']}" + (' (device status register bus-fault bit)' if obs.get('device_fault') else '')
        if not obs.get('actual_bits'):
            out['no-output-commit'] = 'status-only result: no output payload stored'
            out['no-new-payload-dma-after-error'] = ('the kernel validates/faults before touching payload; only the status '
                                                     'record is written (student_mini_host_fault.inc)')
    _own_primitive(row, out, 'Vortex kernel')
    if protocol is not None and protocol.get('status') == 'PASS':
        for event in protocol['actual_events']:
            out[event] = f"GPU protocol run ({protocol['setting']}): {protocol['events']}"
    return out


def attest(row, events):
    expected = row['golden']['expected_events']
    missing = [e for e in expected if e not in events]
    return dict(expected_events=expected, actual_events={e: events[e] for e in expected if e in events}, missing_events=missing)
