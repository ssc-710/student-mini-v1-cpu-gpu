"""Run every frozen Nano test question on the final mapped CPU (ROM hard-block boundary).

For each of the 12 test questions the selected-stage image and its passing C
preflight (found by exact image-manifest binding) are replayed through the
unchanged compiled CPU replay binary of a passing ROM-block full replay; only
the external SDRAM model input changes.  The existing selected-replay producer
is reused verbatim except for the accepted parent stage.  Each session is then
joined by assemble_student_mini_selected_session.py --platform cpu.
"""
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
from scripts.run_student_mini_nano_test_sessions import find_image, last_json

ACCEPTED = ('CPU_ROM_BANKS_COLD_START_REPLAY_STAGE_PASS', 'CPU_ROM_BLOCK_COLD_START_REPLAY_STAGE_PASS', 'CPU_MACRO_PACKED_COLD_START_REPLAY_STAGE_PASS')


def derive(source, parent_status):
    old = "if parent.get('status')!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS':raise ValueError('actual mapped CPU parent required')"
    if source.count(old) != 1:
        raise ValueError('selected CPU replay seam changed')
    source = source.replace(old, f"if parent.get('status')!={parent_status!r}:raise ValueError('final mapped CPU parent required')")
    seam = "paths=[Path(__file__),prior/'completion.json',"
    if source.count(seam) != 1:
        raise ValueError('selected CPU replay binding seam changed')
    source = source.replace(seam, "paths=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_nano_sessions.py',prior/'completion.json',")
    header = "checked_header((old_image/'student_mini_native_image.h').read_text(),(image/'student_mini_native_image.h').read_text())"
    if source.count(header) != 1:
        raise ValueError('selected CPU replay header seam changed')
    source = source.replace(header, "__import__('scripts.student_mini_cpu_v2_header',fromlist=['x']).checked_header_v2("
                            "(old_image/'student_mini_native_image.h').read_text(),(image/'student_mini_native_image.h').read_text())")
    # The ROM-bank replay binary is built with the fail-fast driver, which takes
    # the executed CPU's reference console (baseline payloads) as its argument.
    run = """command=['bash','-c','ulimit -c 0; cd -- "$1" || exit; exec "$2"','selected-cpu',str(work),str(binary)]"""
    if source.count(run) != 1:
        raise ValueError('selected CPU replay command seam changed')
    source = source.replace(run, """command=['bash','-c','ulimit -c 0; cd -- "$1" || exit; exec "$2" "$3"','selected-cpu',str(work),str(binary),"""
                                 """str(Path(json.loads((prior/'completion.json').read_text())['parent_cpu'])/'console.log')]""")
    root = 'ROOT=Path(__file__).resolve().parents[1]'
    if source.count(root) != 1:
        raise ValueError('selected CPU replay root seam changed')
    return source.replace(root, 'ROOT=Path(' + repr(str(ROOT)) + ')')


def find_preflight(image):
    manifest = str(image / 'manifest.json')
    found = []
    for report in sorted((ROOT / 'build/student-mini/selected-native-c-preflight').glob('*/report.json')):
        value = json.loads(report.read_text(encoding='utf-8'))
        if value.get('status') == 'SELECTED_NATIVE_C_PREFLIGHT_STAGE_PASS' and value['bindings'].get(manifest) == sha(image / 'manifest.json'):
            found.append(report)
    if not found:
        raise ValueError('no passing preflight for ' + manifest)
    return found[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True, help='passing final CPU replay directory')
    parser.add_argument('--old-image-dir', type=Path, required=True, help='model image compiled into the executed ROM run')
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--first', type=int, default=0)
    args = parser.parse_args()
    replay = args.replay.resolve()
    parent = json.loads((replay / 'completion.json').read_text())
    if parent.get('status') not in ACCEPTED:
        raise ValueError('final mapped CPU replay required')
    candidate = args.candidate.resolve()
    quality = json.loads(candidate.read_text(encoding='utf-8'))['quality']['ptq_exact']
    questions = [row['question'] for row in quality]
    original = ROOT / 'scripts/run_student_mini_selected_cpu_replay.py'
    joiner = ROOT / 'scripts/assemble_student_mini_selected_session.py'
    cpu_run = Path(parent['parent_cpu'])
    if not any(Path(p).name == 'student_mini_native_session_v2.c' for p in json.loads((cpu_run / 'inputs.json').read_text())['bindings']):
        raise ValueError('question-independent (v2) CPU firmware required')
    bindings = {str(p): sha(p) for p in (Path(__file__), original, joiner, candidate, replay / 'completion.json',
                                         ROOT / 'scripts/student_mini_cpu_v2_header.py')}
    plan = dict(bindings=bindings, replay=str(replay), questions=questions, first=args.first)
    identity = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    work = ROOT / 'build/student-mini/cpu-nano-sessions' / identity
    work.mkdir(parents=True, exist_ok=False)
    producer = work / 'selected-producer.py'
    producer.write_text(derive(original.read_text(), parent['status']))
    bindings[str(producer)] = sha(producer)
    (work / 'inputs.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    started = time.monotonic()
    result = dict(status='HOLD', bindings=bindings, questions=[], platform='cpu')

    def run(label, command):
        if any(sha(Path(p)) != v for p, v in bindings.items()):
            raise ValueError('batch input changed')
        (work / 'heartbeat.json').write_text(json.dumps(dict(stage=label, updated_at=datetime.now(timezone.utc).isoformat())) + '\n')
        log = work / (label + '.log')
        with log.open('x') as stream:
            code = subprocess.call([sys.executable, *map(str, command)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if code:
            raise RuntimeError(f'{label} exited {code}')
        return last_json(log.read_text(errors='replace'))

    try:
        for index, question in enumerate(questions):
            if index < args.first:
                continue
            image = find_image(question, candidate)
            if image is None:
                raise ValueError(f'missing exported image for question {index}')
            preflight = find_preflight(image)
            executed = run(f'q{index:02d}-cpu-execute', [producer, '--replay', replay, '--image-dir', image,
                                                          '--old-image-dir', args.old_image_dir.resolve(),
                                                          '--candidate', candidate, '--preflight', preflight])
            if executed.get('status') != 'SELECTED_MAPPED_CPU_NUMERICAL_STAGE_PASS':
                raise ValueError(f'CPU session failed for question {index}: {executed.get("reason")}')
            joined = run(f'q{index:02d}-cpu-join', [joiner, '--run', executed['work'], '--image-dir', image,
                                                    '--candidate', candidate, '--platform', 'cpu'])
            result['questions'].append(dict(index=index, question=question, image=str(image), run=executed['work'], session=joined))
            print(json.dumps(dict(question=index, session=joined.get('path'))), flush=True)
        result.update(status='CPU_NANO_TEST_SESSIONS_EXECUTED', reason='All requested questions executed on the final mapped CPU')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic() - started
    (work / 'completion.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'CPU_NANO_TEST_SESSIONS_EXECUTED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
