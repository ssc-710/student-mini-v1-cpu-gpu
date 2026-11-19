"""Compare unchanged Nano values while preserving all changed hardware counters."""
import re
from scripts.student_mini_cpu_latency_replay import compare_transcripts as compare_payloads

FIELDS=('cycles','instructions','ibus_bytes','dbus_bytes','dma_bytes')


def counter(value):
    if not re.fullmatch(r'\d+:\d+',value):raise ValueError('invalid hardware counter format')
    hi,lo=map(int,value.split(':'))
    if hi>=2**32 or lo>=2**32:raise ValueError('hardware counter word overflow')
    return (hi<<32)|lo


def native_measurements(text):
    rows=text.splitlines()
    summary=[x for x in rows if x.startswith('STUDENT_NATIVE_CPU status=')]
    pattern=r'STUDENT_NATIVE_CPU status=0 count=(\d+)'+''.join(' '+key+r'=(\d+:\d+)' for key in FIELDS)
    match=re.fullmatch(pattern,summary[0]) if len(summary)==1 else None
    if not match or not 1<=int(match[1])<=12:raise ValueError('one complete successful Nano counter record required')
    result={key:counter(value) for key,value in zip(FIELDS,match.groups()[1:],strict=True)}
    if result['cycles']<=0 or result['instructions']<=0:raise ValueError('non-progressing Nano counters')
    steps=[x for x in rows if x.startswith('STUDENT_NATIVE_TOKEN ')]
    if len(steps)!=int(match[1]):raise ValueError('Nano count/state records differ')
    elapsed=[]
    for step,line in enumerate(steps):
        found=re.match(r'STUDENT_NATIVE_TOKEN step=(\d+) token=\d+ elapsed_cycles=(\d+:\d+) hidden=',line)
        if not found or int(found[1])!=step:raise ValueError('missing/reordered Nano step counters')
        value=counter(found[2])
        if value<=0 or (elapsed and value<=elapsed[-1]):raise ValueError('nonmonotonic Nano counters')
        elapsed.append(value)
    if elapsed[-1]>result['cycles']:raise ValueError('token duration exceeds full session')
    operators=[x for x in rows if x.startswith('STUDENT_NATIVE_OPERATOR ')]
    if len(operators)!=3:raise ValueError('three separate operator measurements required')
    measured={}
    for op,line in enumerate(operators,1):
        found=re.fullmatch(r'STUDENT_NATIVE_OPERATOR op=(\d+) cycles=(\d+:\d+)',line)
        if not found or int(found[1])!=op:raise ValueError('missing/duplicate/reordered Nano operator counters')
        measured[str(op)]=counter(found[2])
    if sum(measured.values())>result['cycles']:raise ValueError('operator intervals exceed full session')
    result.update(token_elapsed_cycles=elapsed,operator_cycles=measured)
    return result


def compare_transcripts(reference,actual):
    old=native_measurements(reference);new=native_measurements(actual)
    def without_measured_summary(text):
        # Only measurement-only rows are handled separately. Full original logs
        # are never rewritten; token values/states and call counts stay checked.
        return '\n'.join(x for x in text.splitlines() if not x.startswith(
            ('STUDENT_NATIVE_CPU status=','STUDENT_NATIVE_OPERATOR ')))
    result=compare_payloads(without_measured_summary(reference),without_measured_summary(actual))
    result['native_counter_comparison']=dict(reference=old,actual=new,
        delta={key:new[key]-old[key] for key in FIELDS})
    return result
