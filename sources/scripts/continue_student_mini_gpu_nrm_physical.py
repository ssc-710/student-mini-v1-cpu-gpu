"""Fresh synthesis/placement after the exact 31-cycle repaired whole GPU replay."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.continue_student_mini_gpu_repaired_synthesis import derive as prior_synthesis


def synthesis_source(source, root):
    text = prior_synthesis(source, root)
    old = "prior['arithmetic_latency']!=30"
    if text.count(old) != 1:
        raise ValueError('31-cycle synthesis prerequisite seam changed')
    text = text.replace(old, "prior['arithmetic_latency']!=31")
    old = 'paths=[Path(__file__),'
    if text.count(old) != 1:
        raise ValueError('synthesis source binding seam changed')
    return text.replace(old, old + "ROOT/'scripts/continue_student_mini_gpu_nrm_physical.py',")


def placement_source(source, root):
    changes = {
        'ROOT = Path(__file__).resolve().parents[1]': 'ROOT = Path(' + repr(str(root)) + ')',
        'files = [Path(__file__),': "files = [Path(__file__), ROOT/'scripts/continue_student_mini_gpu_nrm_physical.py', ROOT/'scripts/place_student_mini_repaired_gpu.py',",
    }
    for old, new in changes.items():
        if source.count(old) != 1:
            raise ValueError('placement source seam changed: ' + old)
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-continuation', type=Path, required=True)
    args = parser.parse_args(); replay = args.replay_continuation.resolve()
    original = ROOT/'scripts/run_student_mini_gpu_cut_synthesis.py'
    placement = ROOT/'scripts/place_student_mini_repaired_gpu.py'
    paths = [Path(__file__), original, placement, replay/'inputs.json',
             ROOT/'scripts/continue_student_mini_gpu_repaired_synthesis.py']
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-nrm-physical-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    synth_producer = work/'synthesis-producer.py'; synth_producer.write_text(synthesis_source(original.read_text(), ROOT))
    place_producer = work/'placement-producer.py'; place_producer.write_text(placement_source(placement.read_text(), ROOT))
    bindings.update({str(p): sha(p) for p in (synth_producer, place_producer)})
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False,
                  physical_evidence_complete=False, arithmetic_latency=31)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n')
    begin = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    def execute(producer, phase, arguments):
        verify(bindings); heartbeat(phase.upper()); log = work/(phase+'.log')
        with log.open('x') as output:
            code = subprocess.call([sys.executable, str(producer), *arguments],
                                   cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        rows = [json.loads(line) for line in log.read_text().splitlines() if line.startswith('{')]
        if rows:
            result[phase] = rows[-1]
        if code or not rows:
            raise ValueError(phase+' failed; child HOLD retained')
        packet = Path(rows[-1]['work'])/'completion.json'; value = json.loads(packet.read_text())
        verify(value['bindings']); bindings.update(value['bindings']); bindings[str(packet)] = sha(packet)
        verify(bindings)
        return rows[-1], value
    try:
        heartbeat('WAITING_FOR_31_CYCLE_WHOLE_REPLAY')
        print(json.dumps(dict(work=str(work), stage='WAITING_FOR_31_CYCLE_WHOLE_REPLAY')), flush=True)
        packet = replay/'completion.json'
        while not packet.is_file():
            if time.monotonic()-begin > 43200:
                raise TimeoutError('bounded whole replay wait expired')
            time.sleep(10)
        parent = json.loads(packet.read_text())
        if parent['status'] != 'GPU_NRM_REPRESENTATIVE_REPLAY_STAGE_PASS' or parent['arithmetic_latency'] != 31:
            raise ValueError('normalization whole-core representative replay not qualified')
        verify(parent['bindings']); bindings.update(parent['bindings']); bindings[str(packet)] = sha(packet)
        replay_packet = Path(parent['replay_continuation'])/'completion.json'
        replay_value = json.loads(replay_packet.read_text()); bindings[str(replay_packet)] = sha(replay_packet)
        if replay_value['status'] != 'REPAIRED_31_CYCLE_GPU_REPRESENTATIVE_STAGE_PASS':
            raise ValueError('actual 31-cycle replay receipt differs')
        child = Path(replay_value['replay']['work'])/'completion.json'
        synthesis, value = execute(synth_producer, 'synthesis', ['--boundary', parent['boundary'], '--replay-proof', str(child)])
        if value['status'] != 'RETIMED_GPU_SYNTHESIS_STAGE_PASS':
            raise ValueError('new synthesis stage incomplete')
        receipt = work/'synthesis-receipt'; receipt.mkdir()
        summary = dict(status='REPAIRED_GPU_SYNTHESIS_PREFLIGHT_STAGE_PASS', arithmetic_latency=31,
                       formal_baseline=False, physical_evidence_complete=False, synthesis=synthesis,
                       bindings=dict(bindings))
        for name in ('inputs.json', 'completion.json'):
            (receipt/name).write_text(json.dumps(summary, indent=2)+'\n')
            bindings[str(receipt/name)] = sha(receipt/name)
        placed, value = execute(place_producer, 'placement', ['--synthesis-continuation', str(receipt)])
        if value['status'] != 'REPAIRED_GPU_PLACEMENT_PREFLIGHT_STAGE_PASS':
            raise ValueError('new 100 MHz placement not qualified')
        result.update(status='GPU_NRM_PHYSICAL_PREFLIGHT_STAGE_PASS',
            reason='Replayed 31-cycle complete boundary passes synthesis and placement; route, activity and complete acceptance remain')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-begin
    result['artifacts'] = {p.relative_to(work).as_posix(): sha(p) for p in work.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'GPU_NRM_PHYSICAL_PREFLIGHT_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
