"""Run every frozen Nano test question on the GPU (SimX) and accelerator (RTL).

For each of the 12 regression/test questions of the selected candidate this
exports the selected-stage image (or reuses the identical existing export),
runs the C preflight, executes the whole session on each platform through the
existing producers and joins the actual tokens/states to the selected model.
Every child producer owns the common serial queue; nothing here substitutes a
reference output for a platform output.  The CPU platform is run separately on
the final CPU hardware mapping.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha

PLATFORMS = ('gpu', 'accelerator')


def last_json(text):
    rows = [line for line in text.splitlines() if line.startswith('{')]
    if not rows:
        raise ValueError('child produced no JSON receipt')
    return json.loads(rows[-1])


def find_image(question, candidate):
    """Reuse an existing export only if it is the same question and candidate."""
    rel = candidate.relative_to(ROOT).as_posix()
    for manifest in sorted((ROOT / 'build/student-mini/selected-native-image').glob('*/manifest.json')):
        value = json.loads(manifest.read_text(encoding='utf-8'))
        if value.get('question') == question and value.get('bindings', {}).get(rel) == sha(candidate):
            if sha(manifest.parent / 'image.bin') == value['image_sha256']:
                return manifest.parent
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--quality-audit', type=Path, required=True)
    for op in ('p1', 'p2', 'p3'):
        parser.add_argument('--' + op + '-placement', type=Path, required=True)
    parser.add_argument('--platform', choices=PLATFORMS, action='append')
    parser.add_argument('--first', type=int, default=0, help='resume at this question index')
    args = parser.parse_args()
    platforms = args.platform or list(PLATFORMS)
    candidate = args.candidate.resolve()
    audit = args.quality_audit.resolve()
    quality = json.loads(candidate.read_text(encoding='utf-8'))['quality']['ptq_exact']
    questions = [row['question'] for row in quality]
    if len(questions) != 12 or len(set(questions)) != 12:
        raise ValueError('expected 12 distinct frozen test questions')
    names = ['export_student_mini_selected_image.py', 'preflight_student_mini_selected_nano.py',
             'prepare_student_mini_native_gpu.py', 'run_student_mini_native_gpu.py',
             'assemble_student_mini_selected_session.py', 'run_student_mini_native_accelerator.py',
             'assemble_student_mini_selected_accelerator_session.py']
    bindings = {str(p): sha(p) for p in [Path(__file__), candidate, audit, *[ROOT / 'scripts' / n for n in names]]}
    plan = dict(bindings=bindings, platforms=platforms, questions=questions, first=args.first,
                placements={op: str(getattr(args, op + '_placement').resolve()) for op in ('p1', 'p2', 'p3')})
    identity = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    work = ROOT / 'build/student-mini/nano-test-sessions' / identity
    work.mkdir(parents=True, exist_ok=False)
    (work / 'inputs.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    started = time.monotonic()
    result = dict(status='HOLD', bindings=bindings, platforms=platforms, questions=[], accepted_nano_session=False)

    def run(label, script, arguments):
        if any(sha(Path(p)) != v for p, v in bindings.items()):
            raise ValueError('batch input changed')
        (work / 'heartbeat.json').write_text(json.dumps(dict(stage=label, updated_at=datetime.now(timezone.utc).isoformat())) + '\n')
        log = work / (label + '.log')
        with log.open('x') as stream:
            code = subprocess.call([sys.executable, str(ROOT / 'scripts' / script), *map(str, arguments)],
                                   cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if code:
            raise RuntimeError(f'{label} exited {code}')
        return last_json(log.read_text(errors='replace'))

    try:
        for index, question in enumerate(questions):
            if index < args.first:
                continue
            row = dict(index=index, question=question, domain=quality[index]['domain'])
            result['questions'].append(row)
            image = find_image(question, candidate)
            if image is None:
                image = Path(run(f'q{index:02d}-export', names[0], ['--candidate', candidate, '--quality-audit', audit,
                                                                    '--question', question])['work'])
            row['image'] = str(image)
            try:
                preflight = run(f'q{index:02d}-preflight', names[1], ['--candidate', candidate, '--image-dir', image])
            except RuntimeError:
                # The identical (candidate, image) preflight may already exist;
                # accept only its own recorded PASS, never assume one.
                text = (work / f'q{index:02d}-preflight.log').read_text(errors='replace')
                found = re.findall(r"File exists: '([^']+/selected-native-c-preflight/[0-9a-f]{64})'", text)
                if len(found) != 1:
                    raise
                prior = json.loads((Path(found[0]) / 'report.json').read_text())
                preflight = dict(work=found[0], status=prior['status'], reused=True)
            if preflight['status'] != 'SELECTED_NATIVE_C_PREFLIGHT_STAGE_PASS':
                raise ValueError('C preflight failed for question %d' % index)
            if 'gpu' in platforms:
                prepared = Path(run(f'q{index:02d}-gpu-prepare', names[2], ['--image-dir', image])['work'])
                executed = run(f'q{index:02d}-gpu-execute', names[3], ['--work', prepared])
                if executed.get('complete') is not True:
                    raise ValueError('GPU session incomplete for question %d' % index)
                row['gpu'] = run(f'q{index:02d}-gpu-join', names[4], ['--run', executed['work'], '--image-dir', image,
                                                                      '--candidate', candidate, '--platform', 'gpu'])
            if 'accelerator' in platforms:
                executed = run(f'q{index:02d}-accelerator-execute', names[5],
                               ['--image-dir', image, *[x for op in ('p1', 'p2', 'p3')
                                                        for x in ('--' + op + '-placement', plan['placements'][op])]])
                if executed.get('complete') is not True:
                    raise ValueError('accelerator session incomplete for question %d' % index)
                row['accelerator'] = run(f'q{index:02d}-accelerator-join', names[6],
                                         ['--run', executed['work'], '--image-dir', image, '--candidate', candidate])
            print(json.dumps(dict(question=index, **{p: row.get(p, {}).get('path') for p in platforms})), flush=True)
        result.update(status='NANO_TEST_SESSIONS_EXECUTED',
                      reason='All 12 frozen test questions executed and joined per platform; acceptance is decided by the release assembler')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic() - started
    (work / 'completion.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'NANO_TEST_SESSIONS_EXECUTED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
